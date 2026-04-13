(() => {
  const $ = id => document.getElementById(id);

  function setStatus(msg, type) {
    const el = $('status');
    el.textContent = msg;
    el.className = `status ${type}`;
  }

  async function init() {
    const data = await new Promise(resolve =>
      chrome.storage.sync.get(['apiUrl', 'apiKey'], resolve)
    );
    if (data.apiUrl) $('apiUrl').value = data.apiUrl;
    if (data.apiKey) $('apiKey').value = data.apiKey;

    $('saveBtn').addEventListener('click', async () => {
      let apiUrl = $('apiUrl').value.trim().replace(/\/+$/, '');
      const apiKey = $('apiKey').value.trim();

      if (!apiUrl) {
        setStatus('API URL is required', 'err');
        return;
      }

      await new Promise(resolve =>
        chrome.storage.sync.set({ apiUrl, apiKey }, resolve)
      );
      setStatus('Saved!', 'ok');
      setTimeout(() => setStatus('', ''), 2000);
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
