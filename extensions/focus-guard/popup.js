// Popup status view for Sadhana Focus Guard.
const statusBox = document.getElementById('statusBox');
const statusTitle = document.getElementById('statusTitle');
const taskEl = document.getElementById('task');
const sessionEl = document.getElementById('sessionId');
const blockedEl = document.getElementById('blocked');
const violationsEl = document.getElementById('violations');
const deviceEl = document.getElementById('device');

async function getConfig() {
  return chrome.storage.sync.get(['serverUrl', 'token']);
}

async function refresh() {
  const { serverUrl, token } = await getConfig();
  deviceEl.textContent = token ? token.slice(0, 8) + '…' : 'Not set';
  if (!serverUrl || !token) {
    statusBox.className = 'status-box idle';
    statusTitle.textContent = 'Not configured. Open Options.';
    return;
  }
  try {
    const res = await fetch(`${serverUrl.replace(/\/+$/, '')}/focus/api/device-status/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    taskEl.textContent = data.task_name || 'Free focus';
    sessionEl.textContent = data.session_id ? `#${data.session_id}` : '—';
    blockedEl.textContent = data.blocked_attempts || 0;
    violationsEl.textContent = data.lock_violations || 0;

    if (data.active && data.lock_enabled) {
      statusBox.className = 'status-box locked';
      statusTitle.textContent = 'Locked — Super Power Saving Mode';
    } else if (data.active) {
      statusBox.className = 'status-box active';
      statusTitle.textContent = 'Focus session active';
    } else {
      statusBox.className = 'status-box idle';
      statusTitle.textContent = 'No active session';
    }
  } catch (e) {
    statusBox.className = 'status-box idle';
    statusTitle.textContent = 'Server unreachable';
  }
}

document.getElementById('refresh').addEventListener('click', refresh);
document.getElementById('openServer').addEventListener('click', async () => {
  const { serverUrl } = await getConfig();
  if (serverUrl) chrome.tabs.create({ url: serverUrl });
});
document.getElementById('options-link').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

refresh();