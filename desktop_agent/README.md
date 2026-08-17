# Sadhana Desktop Focus Agent

OS-level enforcement for **Super Power Saving Mode**. A Django website cannot
kill apps or reliably prevent application switching, so the Focus Agent runs on
the child's PC and does the actual enforcement while Django handles
authentication, permissions, notifications and session data.

## What it does

- Polls the Sadhana server for the active focus session + block/allow rules.
- **Blacklist mode** (default): terminates restricted applications (e.g.
  `Discord.exe`, `Steam.exe`) while the lock is active, unless the parent
  approved temporary access.
- **Whitelist mode** (optional, strict): terminates anything that is not on the
  whitelist or approved by the parent. Essential OS processes are never killed.
- Detects when the focus window is minimized / desktop is shown and reports it
  to the server (the parent gets a notification immediately). Best effort only —
  it cannot defeat a determined user, but it records every attempt.
- Batches all lock events into the device heartbeat endpoint.

## Setup

1. Install Python 3.9+ and install dependencies:

   ```bash
   cd desktop_agent
   pip install -r requirements.txt
   ```

2. Copy the config template and fill it in:

   ```bash
   cp config.example.json config.json
   ```

   In the Sadhana Focus page, open **Super Power Lock & Devices → Register a
   device**, choose *Desktop Agent*, and paste the generated token into
   `config.json` (field `device_token`). Set `server_url` to your Django server
   (e.g. `http://127.0.0.1:8000`).

3. Run it:

   ```bash
   python agent.py
   # or with a custom config:
   python agent.py --config my-config.json
   ```

## Config options

| Option | Default | Description |
| ------ | ------- | ----------- |
| `server_url` | `http://127.0.0.1:8000` | Your Sadhana Django server |
| `device_token` | — | Token from the Focus page device registration |
| `poll_interval_seconds` | `5` | How often to poll the server |
| `process_check_interval_seconds` | `3` | How often to scan & terminate processes |
| `mode` | `blacklist` | `blacklist` or `whitelist` |
| `allow_system_processes` | `true` | Never kill essential OS processes |
| `restore_focus_window` | `true` | Best-effort restore of the focus window |

## Limitations

- Websites are blocked by the **Focus Guard browser extension**
  (`extensions/focus-guard`), not the agent.
- Alt+Tab, Win key and OS-level shortcuts cannot be fully blocked from a normal
  user-mode process. The agent records and reports the attempt and re-focuses
  the window. For true kiosk-grade enforcement, run the child's desktop in a
  dedicated locked account / Windows Family Safety.