// Options page for Sadhana Focus Guard.
const serverUrlInput = document.getElementById('serverUrl');
const tokenInput = document.getElementById('token');
const statusEl = document.getElementById('status');

function showStatus(text, type) {
  statusEl.className = `status ${type}`;
  statusEl.textContent = text;
}

async function load() {
  const stored = await chrome.storage.sync.get(['serverUrl', 'token']);
  serverUrlInput.value = stored.serverUrl || '';
  tokenInput.value = stored.token || '';
}

document.getElementById('save').addEventListener('click', async () => {
  const serverUrl = serverUrlInput.value.trim().replace(/\/+$/, '');
  const token = tokenInput.value.trim();
  await chrome.storage.sync.set({ serverUrl, token });
  showStatus('Saved. The extension will start enforcing Super Power Saving Mode.', 'ok');
});

document.getElementById('test').addEventListener('click', async () => {
  const serverUrl = serverUrlInput.value.trim().replace(/\/+$/, '');
  const token = tokenInput.value.trim();
  if (!serverUrl || !token) {
    showStatus('Enter both the server URL and device token first.', 'err');
    return;
  }
  try {
    const res = await fetch(`${serverUrl}/focus/api/device-status/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    if (!res.ok) {
      showStatus(`Connection failed (${res.status}). Check the URL and token.`, 'err');
      return;
    }
    const lock = data.lock_enabled ? 'Super Power Saving Mode is ACTIVE' : 'No active lock';
    showStatus(`Connected! Session active: ${data.active ? 'yes' : 'no'}. ${lock}.`, 'ok');
    await chrome.storage.sync.set({ serverUrl, token });
  } catch (e) {
    showStatus('Could not reach the server. Make sure it is running and the URL is correct.', 'err');
  }
});

load();
