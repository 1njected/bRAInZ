'use strict';

let currentUrl = '';
let apiUrl = 'http://localhost:8000';
let apiKey = '';

const urlDisplay = document.getElementById('urlDisplay');
const titleInput = document.getElementById('titleInput');
const categorySelect = document.getElementById('categorySelect');
const tagsInput = document.getElementById('tagsInput');
const saveBtn = document.getElementById('saveBtn');
const saveCloseBtn = document.getElementById('saveCloseBtn');
const statusEl = document.getElementById('status');
const dashLink = document.getElementById('dashLink');

function setStatus(msg, type = '') {
  statusEl.textContent = msg;
  statusEl.className = type ? `status-${type}` : '';
}

async function loadSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(['apiUrl', 'apiKey', 'defaultCategory'], data => {
      if (data.apiUrl) apiUrl = data.apiUrl;
      if (data.apiKey) apiKey = data.apiKey;
      dashLink.href = apiUrl;
      resolve(data);
    });
  });
}

async function loadCategories() {
  try {
    const resp = await fetch(`${apiUrl}/api/config/categories`, {
      headers: { 'X-API-Key': apiKey },
    });
    if (!resp.ok) return;
    const cats = await resp.json();
    for (const cat of cats) {
      const opt = document.createElement('option');
      opt.value = cat;
      opt.textContent = cat;
      categorySelect.appendChild(opt);
    }
  } catch (_) {}
}

async function loadTags() {
  try {
    const resp = await fetch(`${apiUrl}/api/tags`, {
      headers: { 'X-API-Key': apiKey },
    });
    if (!resp.ok) return;
    const tags = await resp.json();
    // Simple datalist for autocomplete
    const dl = document.createElement('datalist');
    dl.id = 'tagSuggestions';
    for (const t of tags.slice(0, 50)) {
      const opt = document.createElement('option');
      opt.value = t.name;
      dl.appendChild(opt);
    }
    document.body.appendChild(dl);
    tagsInput.setAttribute('list', 'tagSuggestions');
  } catch (_) {}
}

async function save(closeAfter = false) {
  if (!currentUrl) return;
  saveBtn.disabled = true;
  saveCloseBtn.disabled = true;
  setStatus('Saving…', 'loading');

  const body = { url: currentUrl };
  const cat = categorySelect.value;
  const tags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean);
  if (cat) body.category = cat;
  if (tags.length) body.tags = tags;

  try {
    const resp = await fetch(`${apiUrl}/api/ingest/url`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    if (data.duplicate) {
      setStatus('Already in knowledge base', 'ok');
    } else {
      setStatus(`Saved: ${data.title}`, 'ok');
    }
    if (closeAfter) setTimeout(() => window.close(), 800);
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'err');
  } finally {
    saveBtn.disabled = false;
    saveCloseBtn.disabled = false;
  }
}

// Init
(async () => {
  await loadSettings();

  // Get current tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tab?.url || '';
  urlDisplay.textContent = currentUrl || 'No URL';
  titleInput.value = tab?.title || '';

  await Promise.all([loadCategories(), loadTags()]);
})();

saveBtn.addEventListener('click', () => save(false));
saveCloseBtn.addEventListener('click', () => save(true));
