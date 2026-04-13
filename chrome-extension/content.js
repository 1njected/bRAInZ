/**
 * bRAInZ page capture content script.
 * Called via chrome.scripting.executeScript — must be a self-contained function.
 *
 * Strategy: serialize the live DOM, then inline external stylesheets and images
 * as data URIs so the result is self-contained (like SingleFile).
 * Runs inside the page's origin context so fetch() carries the page's cookies.
 */
async function capturePageAsHTML() {
  // ── helpers ────────────────────────────────────────────────────────────────

  function toDataURI(bytes, mimeType) {
    const b64 = btoa(String.fromCharCode(...new Uint8Array(bytes)));
    return `data:${mimeType};base64,${b64}`;
  }

  async function fetchBytes(url) {
    try {
      const r = await fetch(url, { credentials: 'include' });
      if (!r.ok) return null;
      const buf = await r.arrayBuffer();
      const ct  = r.headers.get('content-type') || 'application/octet-stream';
      const mime = ct.split(';')[0].trim();
      return { bytes: buf, mime };
    } catch {
      return null;
    }
  }

  // Inline a single CSS text: replace url(…) references with data URIs.
  async function inlineCSSUrls(cssText, baseUrl) {
    const urlPattern = /url\(\s*(['"]?)([^)'"]+)\1\s*\)/gi;
    const matches = [];
    let m;
    while ((m = urlPattern.exec(cssText)) !== null) {
      matches.push({ full: m[0], quote: m[1], raw: m[2], index: m.index });
    }
    const results = await Promise.all(matches.map(async ({ raw }) => {
      if (raw.startsWith('data:') || raw.startsWith('#')) return null;
      const abs = new URL(raw, baseUrl).href;
      return fetchBytes(abs);
    }));
    let out = cssText;
    // Replace from end to front to keep indices valid
    for (let i = matches.length - 1; i >= 0; i--) {
      const res = results[i];
      if (!res) continue;
      const { full, quote, index } = matches[i];
      const dataUri = toDataURI(res.bytes, res.mime);
      out = out.slice(0, index) + `url(${quote}${dataUri}${quote})` + out.slice(index + full.length);
    }
    return out;
  }

  // ── 1. Clone the document ──────────────────────────────────────────────────

  const docClone = document.documentElement.cloneNode(true);

  // Remove scripts to keep snapshot static and safe
  docClone.querySelectorAll('script').forEach(el => el.remove());
  // Remove noscript — not needed in a static snapshot
  docClone.querySelectorAll('noscript').forEach(el => el.remove());

  const baseUrl = document.baseURI || location.href;

  // ── 2. Inline external stylesheets ────────────────────────────────────────

  const linkEls = Array.from(docClone.querySelectorAll('link[rel="stylesheet"][href]'));
  await Promise.all(linkEls.map(async link => {
    const href = link.getAttribute('href');
    if (!href || href.startsWith('data:')) return;
    try {
      const abs = new URL(href, baseUrl).href;
      const res = await fetchBytes(abs);
      if (!res) return;
      const decoder = new TextDecoder('utf-8');
      let cssText = decoder.decode(res.bytes);
      cssText = await inlineCSSUrls(cssText, abs);
      const style = document.createElement('style');
      style.textContent = cssText;
      link.parentNode.replaceChild(style, link);
    } catch { /* leave as-is */ }
  }));

  // Inline url() references in existing <style> blocks
  const styleEls = Array.from(docClone.querySelectorAll('style'));
  await Promise.all(styleEls.map(async style => {
    style.textContent = await inlineCSSUrls(style.textContent, baseUrl);
  }));

  // ── 3. Inline images ──────────────────────────────────────────────────────

  const imgEls = Array.from(docClone.querySelectorAll('img[src]'));
  await Promise.all(imgEls.map(async img => {
    const src = img.getAttribute('src');
    if (!src || src.startsWith('data:')) return;
    try {
      const abs = new URL(src, baseUrl).href;
      const res = await fetchBytes(abs);
      if (!res) return;
      img.setAttribute('src', toDataURI(res.bytes, res.mime));
    } catch { /* leave as-is */ }
  }));

  // Inline srcset images (take first entry only to keep size reasonable)
  const srcsetEls = Array.from(docClone.querySelectorAll('img[srcset], source[srcset]'));
  await Promise.all(srcsetEls.map(async el => {
    const first = el.getAttribute('srcset').split(',')[0].trim().split(/\s+/)[0];
    if (!first || first.startsWith('data:')) return;
    try {
      const abs = new URL(first, baseUrl).href;
      const res = await fetchBytes(abs);
      if (!res) return;
      el.setAttribute('src', toDataURI(res.bytes, res.mime));
      el.removeAttribute('srcset');
    } catch { /* leave as-is */ }
  }));

  // ── 4. Fix relative hrefs and src attributes ───────────────────────────────

  // Make all remaining src/href attributes absolute so links still work
  for (const el of docClone.querySelectorAll('[href]')) {
    const v = el.getAttribute('href');
    if (v && !v.startsWith('#') && !v.startsWith('data:') && !v.startsWith('javascript:')) {
      try { el.setAttribute('href', new URL(v, baseUrl).href); } catch { /* ignore */ }
    }
  }
  for (const el of docClone.querySelectorAll('[src]')) {
    const v = el.getAttribute('src');
    if (v && !v.startsWith('data:') && !v.startsWith('javascript:')) {
      try { el.setAttribute('src', new URL(v, baseUrl).href); } catch { /* ignore */ }
    }
  }

  // ── 5. Ensure <base> points to origin so any missed relative URLs still resolve

  let base = docClone.querySelector('base');
  if (!base) {
    base = document.createElement('base');
    const head = docClone.querySelector('head') || docClone;
    head.insertBefore(base, head.firstChild);
  }
  base.setAttribute('href', baseUrl);

  // ── 6. Serialize ──────────────────────────────────────────────────────────

  const serializer = new XMLSerializer();
  const html = '<!DOCTYPE html>\n' + serializer.serializeToString(docClone);
  return html;
}
