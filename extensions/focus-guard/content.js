// Sadhana Focus Guard - content script.
// Runs on every page. When the Sadhana focus page is open it detects
// tab-switch (visibility change), leave attempts (navigation / close / Esc / F11)
// and reports them to the service worker so parents get notified.

(function () {
  let isFocusPage = false;

  function checkFocusPage() {
    try {
      const path = window.location.pathname;
      isFocusPage = path.startsWith('/focus/') && !path.startsWith('/focus/parent');
    } catch (e) {
      isFocusPage = false;
    }
    return isFocusPage;
  }

  function notify(msg) {
    try {
      chrome.runtime.sendMessage(msg);
    } catch (e) { /* extension context may be gone */ }
  }

  if (!checkFocusPage()) return;

  notify({ type: 'FOCUS_PAGE_READY' });

  // Listen for allowed-app launch signals from the focus page JS.
  // When a child opens an Allowed App through Sadhana, the page sets a guard
  // flag that the service worker checks before reporting violations.
  window.addEventListener('message', e => {
    if (e.source !== window) return;
    if (e.data && e.data.type === 'SADHANA_ALLOWED_APP_LAUNCHED') {
      notify({ type: 'ALLOWED_APP_GUARD', duration: e.data.duration || 15000 });
    }
  });

  // Tab switch detection (user leaves this tab).
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      notify({ type: 'TAB_HIDDEN', detail: 'Focus page hidden (tab switched)' });
    }
  });

  // Leave attempts: closing the tab / navigating away.
  window.addEventListener('beforeunload', e => {
    notify({ type: 'LEAVE_ATTEMPT', detail: 'Child tried to close or navigate away from the focus window' });
    // Show a warning dialog to deter leaving.
    e.preventDefault();
    e.returnValue = '';
  });

  // Keyboard shortcuts that try to escape the lock (best effort).
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' || e.key === 'F11') {
      notify({ type: 'LEAVE_ATTEMPT', detail: `Child pressed ${e.key}` });
    }
    // Alt+Tab cannot be intercepted by a page; the service worker handles it.
  });

  // Re-assert focus periodically.
  setInterval(() => {
    if (document.hasFocus() === false) {
      notify({ type: 'TAB_HIDDEN', detail: 'Focus window lost focus' });
    }
  }, 5000);
})();
