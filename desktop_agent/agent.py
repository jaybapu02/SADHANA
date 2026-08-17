#!/usr/bin/env python3
"""Sadhana Desktop Focus Agent — OS-level enforcement for Super Power Saving Mode.

Responsibilities:
  * Poll the Django server for the child's active focus session + lock rules.
  * Kill restricted application processes (blacklist mode) or kill everything
    that is not whitelisted (strict whitelist mode).
  * Temporarily allow apps the parent approved.
  * Detect window minimize / loss of focus and report it to the server so the
    parent is notified. Best effort: restores focus when possible.
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
import sys
import time
from datetime import datetime, timezone

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

EVENT_TYPES = {
    "APP_BLOCKED": "APP_BLOCKED",
    "MINIMIZE": "MINIMIZE",
    "LEAVE_ATTEMPT": "LEAVE_ATTEMPT",
    "TAB_SWITCH": "TAB_SWITCH",
    "WINDOW_CLOSE": "WINDOW_CLOSE",
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
        }
        self.pending_events = []
        self.seen_events = set()
        self.last_poll = 0.0

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
                    ts = datetime.fromisoformat(granted).replace(tzinfo=timezone.utc).timestamp()
                    if ts <= now:
                        continue
                except (ValueError, TypeError):
                    continue
            if a.get("app_name"):
                self.state["approved_apps"].append(a["app_name"].lower())

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

    def monitor_focus(self):
        if not (self.state["active"] and self.state["lock_enabled"]):
            return
        if not self.is_windows():
            return
        title = self.foreground_window_title() or ""
        # The focus browser window should have a normal title. If the foreground
        # is the desktop / task switching, treat it as a minimize / leave attempt.
        desktop_titles = {"program manager", "", "task switching", "task switching"}
        if title.strip().lower() in desktop_titles:
            self.queue_event(
                "MINIMIZE",
                "Focus window minimized or desktop shown",
                dedup_key="minimize",
            )
            if self.config["restore_focus_window"]:
                self._restore_focus()

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
                self.send_heartbeat()

            if now - last_process_check >= self.config["process_check_interval_seconds"]:
                last_process_check = now
                self.enforce_processes()
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