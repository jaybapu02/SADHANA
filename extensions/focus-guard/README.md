# Sadhana Focus Guard (Browser Extension)

Super Power Saving Mode enforcement for Sadhana Focus Sessions. This extension:

- **Blocks restricted websites** using `declarativeNetRequest` while a locked focus session is active.
- **Allows only whitelisted + parent-approved sites.**
- **Detects tab switching, window minimize, window close and leave attempts** and reports
  each one to the Django server, which immediately notifies the linked parent.
- **Keeps the focus window in front** while the lock is active (best effort).

## Install (developer mode)

1. Open `chrome://extensions` (or `edge://extensions`).
2. Enable **Developer mode**.
3. Click **Load unpacked** and select this `focus-guard` folder.
4. Open the extension **Options** and set:
   - **Server URL** — e.g. `http://127.0.0.1:8000`
   - **Device Token** — generated in the Sadhana Focus page under
     *Super Power Lock & Devices → Register a device* (type `Browser Extension`).
5. Click **Test connection**.

The extension polls the server every ~5s. When the child starts a session with
Super Power Saving Mode enabled, the extension automatically applies the
blocking rules and starts monitoring. When the session ends, it releases the lock.

## Notes

- The extension can only control the browser. OS-level apps (e.g. Discord, games)
  are handled by the Desktop Focus Agent in `desktop_agent/`.
- Some shortcuts (Alt+Tab, Win key) cannot be fully blocked from an extension.
  The extension re-focuses the window and records the attempt instead.