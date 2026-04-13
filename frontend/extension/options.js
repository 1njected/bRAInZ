'use strict';

const apiUrlEl = document.getElementById('apiUrl');
const apiKeyEl = document.getElementById('apiKey');
const defaultCatEl = document.getElementById('defaultCategory');
const saveBtn = document.getElementById('saveBtn');
const testBtn = document.getElementById('testBtn');
const statusEl = document.getElementById('status');

function setStatus(msg, cls = '') {
  statusEl.textContent = msg;
  statusEl.className = cls;
}

function populateCategories(cats, selected = '') {
  defaultCatEl.innerHTML = '<option value="">Auto-classify</option>';
  for (const cat of cats) {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    if (cat === selected) opt.selected = true;
    defaultCatEl.appendChild(opt);
  }
}

// Load saved settings, then try to fetch categories from API
chrome.storage.local.get(['apiUrl', 'apiKey', 'defaultCategory'], async data => {
  if (data.apiUrl) apiUrlEl.value = data.apiUrl;
  if (data.apiKey) apiKeyEl.value = data.apiKey;

  const url = (data.apiUrl || 'http://localhost:8000').replace(/\/$/, '');
  const key = data.apiKey || '';

  try {
    const resp = await fetch(`${url}/api/config/categories`, { headers: { 'X-API-Key': key } });
    if (resp.ok) {
      const cats = await resp.json();
      populateCategories(cats, data.defaultCategory || '');
      return;
    }
  } catch (_) {}

  // Fallback: minimal list
  populateCategories(['appsec','reversing','netsec','ad-hacking','cloud-security','forensics','malware','crypto','osint','misc'], data.defaultCategory || '');
});

saveBtn.addEventListener('click', () => {
  chrome.storage.local.set({
    apiUrl: apiUrlEl.value.trim().replace(/\/$/, ''),
    apiKey: apiKeyEl.value.trim(),
    defaultCategory: defaultCatEl.value,
  }, () => setStatus('Settings saved', 'ok'));
});

testBtn.addEventListener('click', async () => {
  const url = apiUrlEl.value.trim().replace(/\/$/, '');
  const key = apiKeyEl.value.trim();
  setStatus('Testing…', '');
  try {
    const resp = await fetch(`${url}/api/health`, {
      headers: { 'X-API-Key': key },
    });
    const data = await resp.json();
    if (resp.ok) {
      setStatus(`Connected — ${data.total_items} items in knowledge base`, 'ok');
    } else {
      setStatus(`Error: ${data.detail || resp.statusText}`, 'err');
    }
  } catch (err) {
    setStatus(`Connection failed: ${err.message}`, 'err');
  }
});
