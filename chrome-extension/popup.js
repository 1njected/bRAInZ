(() => {
  const $ = id => document.getElementById(id);

  async function getStorage(keys) {
    return new Promise(resolve => chrome.storage.sync.get(keys, resolve));
  }

  async function getCurrentTab() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  }

  async function loadCategories(apiUrl, apiKey) {
    try {
      const headers = apiKey ? { 'X-API-Key': apiKey } : {};
      const resp = await fetch(`${apiUrl}/api/config/categories`, { headers });
      if (!resp.ok) return [];
      return await resp.json();
    } catch {
      return [];
    }
  }

  function setStatus(msg, type) {
    const el = $('status');
    el.textContent = msg;
    el.className = `status ${type}`;
  }

  function setAllDisabled(disabled) {
    $('ingestBtn').disabled = disabled;
    $('ingestFollowupBtn').disabled = disabled;
    $('snapshotBtn').disabled = disabled;
  }

  async function init() {
    const { apiUrl, apiKey } = await getStorage(['apiUrl', 'apiKey']);

    $('settingsBtn').addEventListener('click', () => chrome.runtime.openOptionsPage());
    $('openSettings')?.addEventListener('click', () => chrome.runtime.openOptionsPage());

    if (!apiUrl) {
      $('notConfigured').style.display = '';
      $('mainBody').style.display = 'none';
      return;
    }

    $('notConfigured').style.display = 'none';
    $('mainBody').style.display = '';

    const tab = await getCurrentTab();
    $('urlDisplay').textContent = tab.url || '(no URL)';

    // Load categories
    const categories = await loadCategories(apiUrl, apiKey);
    const select = $('categorySelect');
    for (const cat of categories) {
      const opt = document.createElement('option');
      opt.value = cat;
      opt.textContent = cat;
      select.appendChild(opt);
    }

    function getCommonParams(followup) {
      const category = select.value || null;
      const rawTags = $('tagsInput').value.trim();
      const tags = rawTags ? rawTags.split(',').map(t => t.trim()).filter(Boolean) : [];
      if (followup && !tags.includes('followup')) tags.push('followup');
      return { category, tags };
    }

    // ── Standard URL ingest ──────────────────────────────────────────────────

    async function doIngest(followup) {
      setAllDisabled(true);
      setStatus('Saving…', 'info');

      const { category, tags } = getCommonParams(followup);
      const body = { url: tab.url };
      if (category) body.category = category;
      if (tags.length) body.tags = tags;

      try {
        const headers = { 'Content-Type': 'application/json' };
        if (apiKey) headers['X-API-Key'] = apiKey;

        const resp = await fetch(`${apiUrl}/api/ingest/url`, {
          method: 'POST', headers, body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));

        if (resp.ok || resp.status === 202) {
          setStatus(followup ? '🔖 Saved + added to Followup' : '✓ Saved', 'ok');
        } else {
          setStatus(data.detail || data.error || `Error ${resp.status}`, 'err');
          setAllDisabled(false);
        }
      } catch {
        setStatus('Network error', 'err');
        setAllDisabled(false);
      }
    }

    // ── Snapshot ingest ──────────────────────────────────────────────────────

    async function doSnapshot() {
      setAllDisabled(true);
      setStatus('Capturing page…', 'info');

      let html;
      try {
        // Inject content.js into the page and run capturePageAsHTML()
        const [{ result }] = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['content.js'],
        });
        // content.js defines capturePageAsHTML; call it in the page context
        const [{ result: captured }] = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => capturePageAsHTML(),
        });
        html = captured;
      } catch (e) {
        setStatus('Capture failed: ' + (e.message || e), 'err');
        setAllDisabled(false);
        return;
      }

      if (!html) {
        setStatus('No content captured', 'err');
        setAllDisabled(false);
        return;
      }

      setStatus('Sending to bRAInZ…', 'info');

      const { category, tags } = getCommonParams(false);
      const body = {
        url: tab.url,
        title: tab.title || '',
        html,
      };
      if (category) body.category = category;
      if (tags.length) body.tags = tags;

      try {
        const headers = { 'Content-Type': 'application/json' };
        if (apiKey) headers['X-API-Key'] = apiKey;

        const resp = await fetch(`${apiUrl}/api/ingest/snapshot`, {
          method: 'POST', headers, body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));

        if (resp.ok || resp.status === 202) {
          setStatus('✓ Saved with snapshot', 'ok');
        } else {
          setStatus(data.detail || data.error || `Error ${resp.status}`, 'err');
          setAllDisabled(false);
        }
      } catch {
        setStatus('Network error', 'err');
        setAllDisabled(false);
      }
    }

    $('ingestBtn').addEventListener('click', () => doIngest(false));
    $('ingestFollowupBtn').addEventListener('click', () => doIngest(true));
    $('snapshotBtn').addEventListener('click', doSnapshot);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
