'use strict';

// Context menus
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'save-page',
    title: 'Save to bRAInZ',
    contexts: ['page'],
  });
  chrome.contextMenus.create({
    id: 'save-link',
    title: 'Save Link to bRAInZ',
    contexts: ['link'],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.menuItemId === 'save-link' ? info.linkUrl : tab.url;
  saveUrl(url);
});

// Keyboard shortcut
chrome.commands.onCommand.addListener((command) => {
  if (command === 'save-to-brainz') {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (tab?.url) saveUrl(tab.url);
    });
  }
});

async function saveUrl(url) {
  const { apiUrl = 'http://localhost:8000', apiKey = '' } = await chrome.storage.local.get(['apiUrl', 'apiKey']);

  try {
    const resp = await fetch(`${apiUrl}/api/ingest/url`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify({ url }),
    });
    const data = await resp.json();
    const msg = data.duplicate
      ? `Already saved: ${data.title}`
      : `Saved to bRAInZ: ${data.title}`;

    chrome.notifications?.create({
      type: 'basic',
      iconUrl: 'icons/icon48.png',
      title: 'bRAInZ',
      message: msg,
    });
  } catch (err) {
    chrome.notifications?.create({
      type: 'basic',
      iconUrl: 'icons/icon48.png',
      title: 'bRAInZ — Error',
      message: err.message,
    });
  }
}
