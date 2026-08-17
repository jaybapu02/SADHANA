// Sadhana Focus Guard - background service worker.
// Polls the Django server, applies website blocking rules (declarativeNetRequest),
// detects tab switching / minimize / window close / leave attempts, and reports
// every violation back to the server so parents are notified.

const DEFAULT_POLL_MS = 5000;
const FOCUS_PATH = '/focus/';

let config = { serverUrl: '', token: '', enabled: true };
let state = {
  active: false,
  lockEnabled: false,
  sessionId: null,
  focusTabId: null,
  focusWindowId: null,
  whitelistPatterns: [],
  blacklistPatterns: [],
  approvedPatterns: [],
  blockedAttempts: 0,
  lockViolations: 0,
};
let pendingEvents = []; // events detected while the server was unreachable

// ─── Config ────────────────────────────────────────────────────────────────

async function loadConfig() {
  const stored = await chrome.storage.sync.get(['serverUrl', 'token', 'enabled']);
  config.serverUrl = (stored.serverUrl || '').replace(/\/+$/, '');
  config.token = stored.token || '';
  config.enabled = stored.enabled !== false;
}

async function saveConfig(next) {
  config = { ...config, ...next };
  await chrome.storage.sync.set({
    serverUrl: config.serverUrl,
    token: config.token,
    enabled: config.enabled,
  });
}

// ─── Server communication ──────────────────────────────────────────────────

async function api(path, options = {}) {
  if (!config.serverUrl) throw new Error('Server URL not configured.');
  const res = await fetch(`${config.serverUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${config.token}`,
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const err = new Error(`API ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function reportEvent(eventType, detail, metadata = {}) {
  if (!state.active || !state.lockEnabled) return;
  try {
    await api('/focus/api/report-lock-event/', {
      method: 'POST',
      body: JSON.stringify({ event_type: eventType, detail, metadata }),
    });
  } catch (e) {
    // Buffer the event and retry on the next heartbeat.
    pendingEvents.push({ event_type: eventType, detail, metadata });
  }
}

async function flushPending() {
  if (!pendingEvents.length) return;
  const events = [...pendingEvents];
  try {
    await api('/focus/api/device-heartbeat/', {
      method: 'POST',
      body: JSON.stringify({ events }),
    });
    pendingEvents = [];
  } catch (e) {
    /* will retry */
  }
}

// ─── Poll server state ─────────────────────────────────────────────────────

async function pollStatus() {
  if (!config.enabled || !config.token) {
    setBadge('off');
    return;
  }
  try {
    const data = await api('/focus/api/device-status/');
    applyStatus(data);
  } catch (e) {
    setBadge('!');
    if (e.status === 401) setBadge('no');
  }
}

function applyStatus(data) {
  const wasActive = state.active;
  const wasLocked = state.lockEnabled;
  state.active = data.active;
  state.lockEnabled = data.lock_enabled;
  state.sessionId = data.session_id;
  state.blockedAttempts = data.blocked_attempts || 0;
  state.lockViolations = data.lock_violations || 0;

  state.whitelistPatterns = (data.whitelist || [])
    .filter(w => w.category === 'WEBSITE' && w.url_pattern)
    .map(w => w.url_pattern);
  state.blacklistPatterns = (data.blacklist || [])
    .filter(b => b.category === 'WEBSITE' && b.url_pattern)
    .map(b => b.url_pattern);
  const now = Date.now();
  state.approvedPatterns = (data.approved || [])
    .filter(a => a.category === 'WEBSITE' && a.url_pattern && a.granted_until)
    .filter(a => new Date(a.granted_until).getTime() > now)
    .map(a => a.url_pattern);

  applyBlockingRules();

  if (state.active && state.lockEnabled) {
    setBadge('lock');
    enforceWindow();
    flushPending();
  } else if (state.active && !state.lockEnabled) {
    setBadge('on');
  } else if (wasActive && !state.active) {
    setBadge('off');
  }

  if (!wasLocked && state.lockEnabled) onLockActivated();
}

function onLockActivated() {
  // Lock turned on: send everyone back to the focus tab.
  bringFocusWindowToFront();
}

// ─── declarativeNetRequest rules ──────────────────────────────────────────

async function applyBlockingRules() {
  const rules = [];
  const blockIds = new Set();
  const allowIds = new Set();
  let idCounter = 1;

  // Allow whitelisted sites (higher priority overrides block).
  for (const pattern of state.whitelistPatterns) {
    rules.push({
      id: idCounter++,
      priority: 3,
      action: { type: 'allow' },
      condition: { urlFilter: pattern, resourceTypes: ['main_frame', 'sub_frame'] },
    });
    allowIds.add(idCounter - 1);
  }
  // Allow parent-approved restricted sites.
  for (const pattern of state.approvedPatterns) {
    rules.push({
      id: idCounter++,
      priority: 3,
      action: { type: 'allow' },
      condition: { urlFilter: pattern, resourceTypes: ['main_frame', 'sub_frame'] },
    });
    allowIds.add(idCounter - 1);
  }
  // Block restricted sites.
  for (const pattern of state.blacklistPatterns) {
    rules.push({
      id: idCounter++,
      priority: 2,
      action: { type: 'block' },
      condition: { urlFilter: pattern, resourceTypes: ['main_frame', 'sub_frame'] },
    });
    blockIds.add(idCounter - 1);
  }

  try {
    const existing = await chrome.declarativeNetRequest.getDynamicRules();
    await chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: existing.map(r => r.id),
      addRules: rules,
    });
  } catch (e) {
    console.error('Failed to update DNR rules', e);
  }
}

// ─── Badge ─────────────────────────────────────────────────────────────────

function setBadge(label) {
  const text = label === 'lock' ? '🔒' : label === 'on' ? '⏱' : label === 'off' ? '' : label === 'no' ? 'X' : '!';
  try {
    chrome.action.setBadgeText({ text });
    chrome.action.setBadgeBackgroundColor({ color: label === 'lock' ? '#d63384' : '#6c757d' });
  } catch (e) { /* ok */ }
}

// ─── Tab / window monitoring ───────────────────────────────────────────────

function isFocusTab(url) {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.pathname.startsWith(FOCUS_PATH) && !u.pathname.startsWith('/focus/parent');
  } catch (e) {
    return false;
  }
}

function isBlacklisted(url) {
  try {
    const u = new URL(url);
    const host = u.hostname;
    return state.blacklistPatterns.some(p => host.includes(p.replace(/^https?:\/\//, '')));
  } catch (e) {
    return false;
  }
}

function isApprovedOrWhitelisted(url) {
  try {
    const u = new URL(url);
    const host = u.hostname;
    return [...state.whitelistPatterns, ...state.approvedPatterns].some(p =>
      host.includes(p.replace(/^https?:\/\//, ''))
    );
  } catch (e) {
    return false;
  }
}

function trackFocusTab(tabId, url) {
  if (isFocusTab(url)) {
    state.focusTabId = tabId;
    chrome.tabs.get(tabId, tab => {
      if (tab && tab.windowId) state.focusWindowId = tab.windowId;
    });
  }
}

function bringFocusWindowToFront() {
  if (!state.focusWindowId || !state.active || !state.lockEnabled) return;
  try {
    chrome.windows.get(state.focusWindowId, w => {
      if (chrome.runtime.lastError || !w) return;
      if (w.state === 'minimized') chrome.windows.update(w.id, { state: 'normal' });
      chrome.windows.update(w.id, { focused: true });
    });
  } catch (e) { /* ok */ }
}

// Web navigation: track the focus tab.
chrome.webNavigation.onCommitted.addListener(details => {
  trackFocusTab(details.tabId, details.url);
});

// Tab became active (user switched tabs).
chrome.tabs.onActivated.addListener(async info => {
  if (!state.active || !state.lockEnabled) return;
  const tab = await chrome.tabs.get(info.tabId).catch(() => null);
  if (!tab) return;
  if (isFocusTab(tab.url)) {
    state.focusTabId = tab.tabId;
    state.focusWindowId = tab.windowId;
    bringFocusWindowToFront();
    return;
  }
  if (isBlacklisted(tab.url) && !isApprovedOrWhitelisted(tab.url)) {
    reportEvent('WEBSITE_BLOCKED', `Attempted to open restricted site ${tab.url}`);
    try { chrome.tabs.remove(tab.id); } catch (e) { /* ok */ }
    return;
  }
  // Switched away from the focus window to an unrelated tab.
  reportEvent('TAB_SWITCH', `Child switched to ${tab.url || 'another tab'}`);
  bringFocusWindowToFront();
});

// New tab / navigation to a restricted site.
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!state.active || !state.lockEnabled) return;
  if (changeInfo.url) {
    if (isFocusTab(changeInfo.url)) {
      state.focusTabId = tabId;
      return;
    }
    if (isBlacklisted(changeInfo.url) && !isApprovedOrWhitelisted(changeInfo.url)) {
      reportEvent('WEBSITE_BLOCKED', `Attempted to open restricted site ${changeInfo.url}`);
    }
  }
});

// Window closed.
chrome.windows.onRemoved.addListener(windowId => {
  if (state.active && state.lockEnabled && state.focusWindowId === windowId) {
    reportEvent('WINDOW_CLOSE', 'The focus window was closed');
    state.focusWindowId = null;
    state.focusTabId = null;
  }
});

// Window lost focus (minimize / alt-tab to desktop).
chrome.windows.onFocusChanged.addListener(windowId => {
  if (!state.active || !state.lockEnabled) return;
  if (windowId === chrome.windows.WINDOW_ID_NONE && state.focusWindowId) {
    reportEvent('MINIMIZE', 'The focus window lost focus');
    bringFocusWindowToFront();
  }
});

// Messages from the content script on the focus page.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === 'FOCUS_PAGE_READY') {
    state.focusTabId = sender.tab ? sender.tab.id : null;
    state.focusWindowId = sender.tab ? sender.tab.windowId : null;
    sendResponse({ ok: true });
    return;
  }
  if (msg && msg.type === 'LEAVE_ATTEMPT') {
    reportEvent('LEAVE_ATTEMPT', msg.detail || 'Child tried to leave the focus window');
    bringFocusWindowToFront();
    sendResponse({ ok: true });
    return;
  }
  if (msg && msg.type === 'TAB_HIDDEN') {
    reportEvent('TAB_SWITCH', msg.detail || 'Child switched away from the focus window');
    bringFocusWindowToFront();
    sendResponse({ ok: true });
  }
});

// Periodic enforcement: keep the focus window in front while locked.
setInterval(() => {
  if (state.active && state.lockEnabled) bringFocusWindowToFront();
}, 2000);

// ─── Startup ───────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async () => {
  await loadConfig();
  if (!config.serverUrl) {
    chrome.runtime.openOptionsPage();
  }
  pollStatus();
});

chrome.alarms.create('focus-guard-poll', { periodInMinutes: 0.25 });
chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name === 'focus-guard-poll') {
    pollStatus();
  }
});

loadConfig().then(() => {
  pollStatus();
  setInterval(pollStatus, DEFAULT_POLL_MS);
});
