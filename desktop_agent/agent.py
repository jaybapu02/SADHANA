#!/usr/bin/env python3
"""Sadhana Desktop Focus Agent — OS-level enforcement for Super Power Saving Mode.

Responsibilities:
  * Poll the Django server for the child's active focus session + lock rules.
  * Kill restricted application processes (blacklist mode) or kill everything
    that is not whitelisted (strict whitelist mode).
  * Temporarily allow apps the parent approved.
  * Detect window minimize / loss of focus / unauthorized app switching and
    report it to the server so the parent is notified. Best effort: restores
    focus when possible.
  * Enforce a grace period for accidental window switches before recording
    violations.
  * Batches lock events into the device heartbeat.

The agent is best-effort. It cannot fully defeat a determined user; it is meant
to make accidental/impulsive distraction impossible and to *record* attempts.

Usage:
    python agent.py [--config config.json]

Requirements: pip install -r requirements.txt  (requests, psutil)
"""

import argparse
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from ctypes import wintypes

import requests
import psutil

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("focus-agent")

DEFAULT_CONFIG = {
    "server_url": "http://127.0.0.1:8000",
    "device_token": "",
    "poll_interval_seconds": 5,
    "process_check_interval_seconds": 3,
    "mode": "blacklist",          # "blacklist" | "whitelist"
    "allow_system_processes": True,
    "restore_focus_window": True,
    "focus_grace_period_seconds": 5,  # seconds before a focus loss counts as violation
    # Optional: exact paths for apps the child may launch through Sadhana,
    # e.g. {"calculator": "calc.exe", "pdf reader": "C:/.../SumatraPDF.exe"}
    "app_paths": {},
}

# Executables that are never killed even in strict whitelist mode (essential OS).
SYSTEM_EXES = {
    "explorer.exe", "taskmgr.exe", "cmd.exe", "conhost.exe", "powershell.exe",
    "dwm.exe", "winlogon.exe", "csrss.exe", "lsass.exe", "services.exe",
    "svchost.exe", "smss.exe", "fontdrvhost.exe", "sihost.exe", "runtimebroker.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "ctfmon.exe", "dllhost.exe", "spoolsv.exe",
    "msedgewebview2.exe", "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe",
    "opera.exe", "code.exe", "python.exe", "pythonw.exe",
}

# Browser executable names — these are the focus window hosts.
BROWSER_EXES = {
    "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe",
}

EVENT_TYPES = {
    "APP_BLOCKED": "APP_BLOCKED",
    "MINIMIZE": "MINIMIZE",
    "LEAVE_ATTEMPT": "LEAVE_ATTEMPT",
    "TAB_SWITCH": "TAB_SWITCH",
    "WINDOW_CLOSE": "WINDOW_CLOSE",
    "UNAUTHORIZED_ACTIVITY": "UNAUTHORIZED_ACTIVITY",
}


class FocusAgent:
    def __init__(self, config_path):
        self.config = dict(DEFAULT_CONFIG)
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                self.config.update(json.load(f))
        self.server_url = self.config["server_url"].rstrip("/")
        self.token = self.config["device_token"]
        self.base = f"{self.server_url}/focus/api"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

        self.state = {
            "active": False,
            "lock_enabled": False,
            "session_id": None,
            "blacklist_apps": [],   # [app_name]
            "whitelist_apps": [],
            "approved_apps": [],    # [app_name]
            "approval_active": False,  # child is inside an approved app right now
            "paused": False,
            "commands": [],         # queued LAUNCH_APP commands from the focus page
        }
        self.pending_events = []
        self.seen_events = set()
        self.last_poll = 0.0

        # Focus enforcement state
        self._left_focus_at = 0.0        # timestamp when child left focus (0 = in focus)
        self._last_foreground_pid = 0    # PID of the last known foreground process
        self._last_foreground_name = ""  # name of the last known foreground process
        self._violation_recorded = False  # True once we've recorded a violation for this leave
        self._grace_seconds = self.config.get("focus_grace_period_seconds", 5)

    # ── API ──────────────────────────────────────────────────────────────

    def fetch_status(self):
        try:
            r = self.session.get(f"{self.base}/device-status/", timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            log.warning("Could not reach server: %s", exc)
            return None

    def send_heartbeat(self):
        if not self.pending_events:
            return
        try:
            r = self.session.post(
                f"{self.base}/device-heartbeat/",
                json={"events": self.pending_events},
                timeout=10,
            )
            if r.status_code < 500:
                self.pending_events = []
        except requests.RequestException as exc:
            log.warning("Heartbeat failed: %s", exc)

    def ack_command(self, command_id, ok, detail=""):
        try:
            r = self.session.post(
                f"{self.base}/device/command-ack/",
                json={"command_id": command_id, "ok": ok, "detail": detail},
                timeout=10,
            )
            if r.status_code >= 400:
                log.warning("Command ack rejected (%s): %s", r.status_code, r.text[:200])
        except requests.RequestException as exc:
            log.warning("Command ack failed: %s", exc)

    def queue_event(self, event_type, detail="", metadata=None, dedup_key=None):
        key = dedup_key or f"{event_type}:{detail}"
        if key in self.seen_events:
            return
        self.seen_events.add(key)
        self.pending_events.append({
            "event_type": event_type,
            "detail": detail,
            "metadata": metadata or {},
        })

    # ── Lock state ───────────────────────────────────────────────────────

    def update_state(self, data):
        active = data.get("active", False)
        lock_enabled = data.get("lock_enabled", False)
        self.state["active"] = active
        self.state["lock_enabled"] = lock_enabled
        self.state["session_id"] = data.get("session_id")
        # While an approved app is in use the child is ALLOWED to be outside
        # the focus window - minimize detection must stand down.
        self.state["approval_active"] = bool(data.get("approval_active"))
        self.state["paused"] = bool(data.get("paused"))
        self.state["commands"] = data.get("commands") or []

        self.state["blacklist_apps"] = [
            b.get("app_name", "").lower()
            for b in data.get("blacklist", [])
            if b.get("category") == "APP" and b.get("app_name")
        ]
        self.state["whitelist_apps"] = [
            w.get("app_name", "").lower()
            for w in data.get("whitelist", [])
            if w.get("category") == "APP" and w.get("app_name")
        ]
        now = time.time()
        self.state["approved_apps"] = []
        for a in data.get("approved", []):
            if a.get("category") != "APP":
                continue
            granted = a.get("granted_until")
            if granted:
                try:
                    dt = datetime.fromisoformat(granted)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt.timestamp() <= now:
                        continue
                except (ValueError, TypeError):
                    continue
            if a.get("app_name"):
                self.state["approved_apps"].append(a["app_name"].lower())

    # ── App launching (Focus Stage icons → real desktop apps) ───────────

    def _resolve_app(self, app_name):
        """Map a friendly app name to something launchable."""
        key = (app_name or "").strip().lower()
        # 1. Explicit mapping from config.json wins.
        paths = self.config.get("app_paths") or {}
        if key in paths:
            return paths[key]
        for alias, path in paths.items():
            if alias in key or key in alias:
                return path
        # 2. On PATH / App Paths registry (os.startfile resolves both).
        found = shutil.which(app_name)
        if found:
            return found
        return app_name

    def _launch_app(self, app_name):
        target = self._resolve_app(app_name)
        try:
            if self.is_windows():
                os.startfile(target)  # noqa: S606 - sanctioned launch via Sadhana
            else:
                subprocess.Popen([target])  # noqa: S603
            log.info("Launched approved/allowed app: %s", app_name)
            return True, f"launched {target}"
        except FileNotFoundError:
            return False, f"'{target}' not found on this computer"
        except OSError as exc:
            return False, f"could not launch '{target}': {exc}"

    def run_pending_commands(self):
        commands, self.state["commands"] = self.state["commands"], []
        for cmd in commands:
            if cmd.get("command_type") != "LAUNCH_APP":
                self.ack_command(cmd.get("id"), False, "unknown command_type")
                continue
            ok, detail = self._launch_app(cmd.get("app_name", ""))
            self.ack_command(cmd.get("id"), ok, detail)

    # ── Process enforcement ──────────────────────────────────────────────

    def enforce_processes(self):
        if not (self.state["active"] and self.state["lock_enabled"]):
            return
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = (proc.info.get("name") or "").lower()
                exe = (proc.info.get("exe") or "").lower()
                target = name or os.path.basename(exe)
                if not target:
                    continue
                if target in SYSTEM_EXES and self.config["allow_system_processes"]:
                    continue
                self._handle_process(proc, target)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def _handle_process(self, proc, target):
        if target in self.state["approved_apps"] or target in self.state["whitelist_apps"]:
            return
        mode = self.config["mode"]
        if mode == "whitelist" and target not in SYSTEM_EXES:
            # Strict mode: anything not whitelisted gets terminated.
            if target not in self.state["whitelist_apps"] and target not in self.state["approved_apps"]:
                self._kill(proc, target)
        elif mode == "blacklist":
            # Kill only processes that are explicitly blacklisted.
            if target in self.state["blacklist_apps"] and target not in self.state["approved_apps"]:
                self._kill(proc, target)

    def _kill(self, proc, target):
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except (psutil.TimeoutExpired, psutil.NoSuchProcess):
                proc.kill()
            log.info("Blocked restricted app: %s", target)
            self.queue_event(
                "APP_BLOCKED",
                f"Restricted app blocked: {target}",
                {"process": target},
                dedup_key=f"app:{target}",
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # ── Window / focus monitoring (best effort) ─────────────────────────

    def is_windows(self):
        return sys.platform == "win32"

    def foreground_window_title(self):
        if not self.is_windows():
            return None
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            return buf.value
        except Exception:
            return None

    def get_foreground_process_info(self):
        """Return (pid, process_name, window_title) of the foreground window.
        Returns (0, '', '') on failure."""
        if not self.is_windows():
            return 0, '', ''
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return 0, '', ''

            # Get window title
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value

            # Get window thread process ID
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid = pid.value

            if pid <= 0:
                return 0, '', title

            # Get process name from PID
            try:
                proc = psutil.Process(pid)
                name = proc.name()
                return pid, name, title
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return pid, '', title

        except Exception:
            return 0, '', ''

    def is_focus_browser_window(self, process_name, window_title):
        """Check if the foreground window belongs to a browser that could
        be hosting the Sadhana focus page."""
        name_lower = (process_name or '').lower()
        if name_lower in BROWSER_EXES:
            return True
        # Also check if the title contains Sadhana-related keywords
        title_lower = (window_title or '').lower()
        if 'sadhana' in title_lower or 'focus' in title_lower:
            return True
        return False

    def is_unauthorized_app(self, process_name):
        """Check if the given process is a blacklisted (unauthorized) app.
        Returns (is_unauthorized, app_name) tuple."""
        name_lower = (process_name or '').lower()
        if not name_lower:
            return False, ''

        # Approved apps are always allowed
        if name_lower in self.state["approved_apps"]:
            return False, name_lower
        if name_lower in self.state["whitelist_apps"]:
            return False, name_lower

        # Check blacklist
        if name_lower in self.state["blacklist_apps"]:
            return True, name_lower

        # In whitelist mode, anything not whitelisted is unauthorized
        mode = self.config["mode"]
        if mode == "whitelist" and name_lower not in SYSTEM_EXES:
            if name_lower not in self.state["whitelist_apps"] and name_lower not in self.state["approved_apps"]:
                return True, name_lower

        return False, name_lower

    def monitor_focus(self):
        """Monitor the foreground window to detect unauthorized activity.

        Detection flow:
        1. Get the foreground process (pid, name, title).
        2. If it's a browser hosting Sadhana → child is focused → reset state.
        3. If it's an approved app or allowed app → child is sanctioned → reset state.
        4. If it's a blacklisted/unauthorized app → start grace timer.
        5. If grace period expires while still outside → record violation.
        6. When child returns to focus → record the return event.
        """
        if not (self.state["active"] and self.state["lock_enabled"]):
            self._reset_focus_state()
            return
        # Approved use: the child is legitimately outside the focus window.
        if self.state["approval_active"] or self.state["paused"]:
            self._reset_focus_state()
            return
        if not self.is_windows():
            return

        pid, proc_name, title = self.get_foreground_process_info()
        now = time.time()

        # --- Check 1: Is the focus browser window in the foreground? ---
        if self.is_focus_browser_window(proc_name, title):
            # Child is in the focus environment
            if self._left_focus_at > 0:
                # Child just returned from an interruption
                self._handle_focus_returned(now)
            self._left_focus_at = 0.0
            self._last_foreground_pid = pid
            self._last_foreground_name = proc_name
            self._violation_recorded = False
            return

        # --- Check 2: Is this an authorized app (launched through Sadhana)? ---
        is_unauth, app_name = self.is_unauthorized_app(proc_name)
        if not is_unauth:
            # Authorized app — not a violation
            if self._left_focus_at > 0:
                self._handle_focus_returned(now)
            self._left_focus_at = 0.0
            self._last_foreground_pid = pid
            self._last_foreground_name = proc_name
            self._violation_recorded = False
            return

        # --- Check 3: Unauthorized app detected ---
        # Start the grace timer if this is a new departure
        if self._left_focus_at == 0.0:
            self._left_focus_at = now
            self._violation_recorded = False
            log.info(
                "Focus lost — unauthorized app detected: %s (grace period: %ds)",
                proc_name or title or 'Unknown',
                self._grace_seconds,
            )
            self._last_foreground_pid = pid
            self._last_foreground_name = proc_name
            return

        # Still outside focus — check if grace period has expired
        elapsed = now - self._left_focus_at
        if elapsed >= self._grace_seconds and not self._violation_recorded:
            self._violation_recorded = True
            detail = f"Unauthorized app in foreground: {proc_name or title or 'Unknown'}"
            log.warning("GRACE PERIOD EXPIRED — recording violation: %s", detail)

            # Queue the violation event
            self.queue_event(
                "UNAUTHORIZED_ACTIVITY",
                detail,
                {
                    "process": proc_name or '',
                    "window_title": title or '',
                    "grace_period_seconds": self._grace_seconds,
                    "elapsed_seconds": round(elapsed),
                },
                dedup_key=f"unauth:{proc_name}",
            )

            # Also queue a MINIMIZE event since the child is not in the focus window
            self.queue_event(
                "MINIMIZE",
                f"Focus window not in foreground — {proc_name or title or 'Unknown'} is active",
                dedup_key="minimize",
            )

            # Best effort: try to restore focus
            if self.config["restore_focus_window"]:
                self._restore_focus()

        # Also detect desktop/task switching (empty or Program Manager title)
        desktop_titles = {"program manager", "", "task switching"}
        if (title or '').strip().lower() in desktop_titles:
            if self._left_focus_at == 0.0:
                self._left_focus_at = now
                self._violation_recorded = False
            elif (now - self._left_focus_at) >= self._grace_seconds and not self._violation_recorded:
                self._violation_recorded = True
                self.queue_event(
                    "MINIMIZE",
                    "Focus window minimized or desktop shown",
                    dedup_key="minimize",
                )
                if self.config["restore_focus_window"]:
                    self._restore_focus()

    def _reset_focus_state(self):
        """Reset focus tracking state when enforcement is not active."""
        self._left_focus_at = 0.0
        self._last_foreground_pid = 0
        self._last_foreground_name = ""
        self._violation_recorded = False

    def _handle_focus_returned(self, now):
        """Handle the child returning to the focus environment after being away."""
        if self._left_focus_at <= 0:
            return
        away_seconds = now - self._left_focus_at
        log.info("Child returned to focus after %.1f seconds away", away_seconds)
        # If a violation was recorded, we don't need to do anything special —
        # the server already has the event. Just log the return.
        if self._violation_recorded:
            log.info("Violation was already recorded for this leave event")
        self._left_focus_at = 0.0
        self._violation_recorded = False

    def _restore_focus(self):
        # Bring the front-most browser-like window back (best effort on Windows).
        try:
            if not self.is_windows():
                return
            # Find a visible top-level window owned by a browser process.
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                if name in {"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe"}:
                    try:
                        ctypes.windll.user32.ShowWindow(proc.info["pid"], 9)
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self):
        log.info("Sadhana Desktop Focus Agent started (server=%s)", self.server_url)
        if not self.token:
            log.error("No device token configured. Add one to %s", config_path)
            return
        last_process_check = 0.0
        last_focus_check = 0.0
        focus_check_interval = 1.0  # Check focus every 1 second for responsive detection
        while True:
            now = time.time()
            data = self.fetch_status()
            if data is not None:
                was_locked = self.state["lock_enabled"]
                self.update_state(data)
                if self.state["lock_enabled"] and not was_locked:
                    log.info("Lock ACTIVE (session #%s)", self.state["session_id"])
                if not self.state["lock_enabled"] and was_locked:
                    log.info("Lock released")
                    self._reset_focus_state()
                if self.state["commands"]:
                    self.run_pending_commands()
                self.send_heartbeat()

            if now - last_process_check >= self.config["process_check_interval_seconds"]:
                last_process_check = now
                self.enforce_processes()

            # Focus monitoring runs more frequently for responsive detection
            if now - last_focus_check >= focus_check_interval:
                last_focus_check = now
                self.monitor_focus()

            time.sleep(self.config["poll_interval_seconds"])


def parse_args():
    parser = argparse.ArgumentParser(description="Sadhana Desktop Focus Agent")
    parser.add_argument("--config", default="config.json",
                        help="Path to config.json (default: config.json)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    global config_path
    config_path = args.config
    agent = FocusAgent(config_path)
    try:
        agent.run()
    except KeyboardInterrupt:
        log.info("Stopped by user.")