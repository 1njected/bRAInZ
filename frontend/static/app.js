'use strict';

/* =====================================================================
   State
   ===================================================================== */
let API  = localStorage.getItem('brainz_api') || window.location.origin;
let KEY  = localStorage.getItem('brainz_key') || '';
let currentView     = 'library';
let currentCategory = '';
let currentTag      = '';
let currentQuery    = '';
let currentItemId   = null;
let items           = [];
let allCategories   = [];
let allConfigCategories = [];  // all categories from taxonomy, regardless of item count
let searchTimer     = null;
let ingestTab       = 'url';

/* =====================================================================
   API helper
   ===================================================================== */
async function api(path, opts = {}) {
  const resp = await fetch(API + path, {
    ...opts,
    headers: { 'X-API-Key': KEY, 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(e.detail || resp.statusText);
  }
  if (resp.status === 204) return null;
  return resp.headers.get('content-type')?.includes('json') ? resp.json() : resp.text();
}

/* =====================================================================
   Auth
   ===================================================================== */
function submitAuth() {
  API = document.getElementById('apiUrlInput').value.trim().replace(/\/$/, '');
  KEY = document.getElementById('apiKeyInput').value.trim();
  localStorage.setItem('brainz_api', API);
  localStorage.setItem('brainz_key', KEY);
  init();
}

async function init() {
  try {
    const h = await api('/api/health');
    document.getElementById('authOverlay').classList.add('hidden');
    document.getElementById('statsBar').textContent = `${h.total_items} items · ${h.llm_provider}`;
    if (h.open_access) {
      document.getElementById('openAccessBanner').style.display = 'block';
      document.body.style.paddingTop = '34px';
    }
    await Promise.all([loadCategories(), loadTopTags(), loadItems(), loadConfigCategories(), loadQueryModels()]);
    updateFollowupBadge();
    updateDigestBadge();
    populateQueryCatFilter();
    populateSkillCat();
    handleHash();
  } catch (e) {
    document.getElementById('authError').textContent = `Connection failed: ${e.message}`;
  }
}

function handleHash() {
  const mItem = location.hash.match(/^#item=([a-f0-9]+)$/);
  if (mItem) { switchView('library'); loadDetail(mItem[1]); history.replaceState(null, '', location.pathname); return; }


  const mTool = location.hash.match(/^#tool=(.+)$/);
  if (mTool) {
    const fullName = decodeURIComponent(mTool[1]);
    switchView('tools');
    loadTools().then(() => {
      const match = toolRepos.find(r => r.full_name === fullName);
      if (match) showRepoDetail(match);
    });
    history.replaceState(null, '', location.pathname);
  }
}

window.addEventListener('hashchange', handleHash);

async function reindex() {
  const confirmed = confirm('Reindex will re-embed all items that are not yet embedded.\n\nThis can take a long time for large datasets. Continue?');
  if (!confirmed) return;
  const btn = document.getElementById('reindexBtn');
  btn.disabled = true;
  btn.textContent = '⟳ Reindexing…';
  try {
    const r = await api('/api/reindex', { method: 'POST' });
    btn.textContent = `✓ ${r.rebuilt} rebuilt`;
    await init();
  } catch (e) {
    btn.textContent = '✗ Failed';
  } finally {
    setTimeout(() => { btn.textContent = '⟳ Reindex'; btn.disabled = false; }, 3000);
  }
}

/* =====================================================================
   Nav — section toggle
   ===================================================================== */
function toggleSection(header) {
  header.closest('.nav-section').classList.toggle('collapsed');
}

/* =====================================================================
   Nav — view switching
   ===================================================================== */
function switchView(view) {
  currentView = view;
  // Clear search when explicitly navigating
  currentQuery = '';
  const si = document.getElementById('searchInput');
  if (si) si.value = '';
  document.querySelectorAll('.nav-view-item').forEach(el =>
    el.classList.toggle('active', el.dataset.view === view));

  const showList       = view === 'library';
  const showRss        = view === 'rss';
  const showTools      = view === 'tools';
  const showFollowup   = view === 'followup';
  const showMyWiki     = view === 'digest';
  const hideDetail     = showRss || showTools || showFollowup || showMyWiki;

  document.getElementById('navCatSection').style.display       = showList    ? '' : 'none';
  document.getElementById('navTagSection').style.display       = showList    ? '' : 'none';
  document.getElementById('navToolTopicSection').style.display = showTools   ? '' : 'none';
  document.getElementById('navWikiCatSection').style.display   = showMyWiki  ? '' : 'none';
  document.getElementById('navWikiTagSection').style.display   = showMyWiki  ? '' : 'none';

  // Standard panels (inside .content-area / #detailPanel)
  document.getElementById('listPanel').style.display     = showList  ? 'flex'  : 'none';
  document.getElementById('detailPanel').style.display   = hideDetail ? 'none'  : 'flex';
  document.getElementById('detailEmpty').style.display   = 'none';
  document.getElementById('detailContent').style.display = 'none';
  document.getElementById('querySkillsView').style.display = view === 'query' ? 'flex' : 'none';

  // Always hide search view when switching to an explicit view
  document.getElementById('searchViewWrapper').style.display = 'none';

  // Full-width views
  document.getElementById('rssViewWrapper').style.display            = showRss      ? 'flex' : 'none';
  document.getElementById('toolsViewWrapper').style.display          = showTools    ? 'flex' : 'none';
  document.getElementById('followupViewWrapper').style.display       = showFollowup ? 'flex' : 'none';
  document.getElementById('digestViewWrapper').style.display   = showMyWiki   ? 'flex' : 'none';

  if (view === 'library') {
    if (!currentItemId) document.getElementById('detailEmpty').style.display = 'flex';
    Promise.all([loadCategories(), loadTopTags(), loadItems()]);
  }
  if (view === 'query')         loadSkills();
  if (view === 'rss')           { loadFeeds(); startRssPoll(); }
  else                          { stopRssPoll(); }
  if (view === 'followup')      loadFollowup();
  if (view === 'digest') loadDigestPages();
  if (view === 'tools') { loadTools().then(loadToolTopics); startToolsStatusPoll(); }
  else { stopToolsStatusPoll(); currentTag = ''; }
}

function switchQsTab(tab) {
  document.getElementById('qsTabQuery').classList.toggle('active', tab === 'query');
  document.getElementById('qsTabSkills').classList.toggle('active', tab === 'skills');
  document.getElementById('qsTabPlanner').classList.toggle('active', tab === 'planner');
  document.getElementById('qsQueryPane').classList.toggle('active', tab === 'query');
  document.getElementById('qsSkillsPane').classList.toggle('active', tab === 'skills');
  document.getElementById('qsPlannerPane').classList.toggle('active', tab === 'planner');
  if (tab === 'skills') loadSkills();
  if (tab === 'planner') loadPlans();
}

/* =====================================================================
   Categories
   ===================================================================== */
async function loadConfigCategories() {
  allConfigCategories = await api('/api/config/categories');
}

async function loadCategories() {
  const data = await api('/api/categories');
  allCategories = data;
  const catList = document.getElementById('catList');
  catList.innerHTML = '';
  let total = 0;
  for (const c of data) {
    total += c.count;
    const div = document.createElement('div');
    div.className = 'nav-item';
    div.dataset.cat = c.name;
    div.innerHTML = `${esc(c.name)} <span class="nav-cnt">${c.count}</span>`;
    div.onclick = () => selectCategory(c.name);
    catList.appendChild(div);
  }
  document.getElementById('totalCnt').textContent = total;
}

function selectCategory(cat) {
  currentCategory = cat;
  currentTag = '';
  document.querySelectorAll('.nav-item[data-cat]').forEach(el =>
    el.classList.toggle('active', el.dataset.cat === cat));
  document.querySelectorAll('.nav-item[data-tag]').forEach(el =>
    el.classList.remove('active'));
  document.getElementById('listViewLabel').textContent = cat || 'All';
  if (currentView === 'tools') { renderToolRepoList(); return; }
  loadItems();
}

/* =====================================================================
   Top tags
   ===================================================================== */
async function loadTopTags() {
  const data = await api('/api/tags');
  const used = data.filter(t => t.count > 0).slice(0, 15);
  const tagList = document.getElementById('tagList');
  tagList.innerHTML = '';
  for (const t of used) {
    const div = document.createElement('div');
    div.className = 'nav-item';
    div.dataset.tag = t.name;
    div.innerHTML = `${esc(t.name)} <span class="nav-cnt">${t.count}</span>`;
    div.onclick = () => selectTag(t.name);
    tagList.appendChild(div);
  }
  if (!used.length) {
    tagList.innerHTML = '<div style="padding:6px 16px;font-size:12px;color:var(--muted)">No tags yet</div>';
  }
}

function selectTag(tag) {
  currentTag = tag;
  currentCategory = '';
  document.querySelectorAll('.nav-item[data-cat]').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-tag]').forEach(el =>
    el.classList.toggle('active', el.dataset.tag === tag));
  document.getElementById('listViewLabel').textContent = `#${tag}`;
  if (currentView === 'tools') { renderToolRepoList(); return; }
  loadItems();
}

function loadToolTopics() {
  const topicList = document.getElementById('toolTopicList');
  if (!topicList) return;
  // Count topic frequency across all loaded repos
  const counts = {};
  for (const r of toolRepos) {
    for (const t of (r.topics || [])) {
      counts[t] = (counts[t] || 0) + 1;
    }
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  topicList.innerHTML = '';
  // "All" entry
  const all = document.createElement('div');
  all.className = 'nav-item' + (currentTag === '' ? ' active' : '');
  all.dataset.tag = '';
  all.innerHTML = `All <span class="nav-cnt">${toolRepos.length}</span>`;
  all.onclick = () => selectTag('');
  topicList.appendChild(all);
  for (const [topic, count] of sorted) {
    const div = document.createElement('div');
    div.className = 'nav-item' + (currentTag === topic ? ' active' : '');
    div.dataset.tag = topic;
    div.innerHTML = `${esc(topic)} <span class="nav-cnt">${count}</span>`;
    div.onclick = () => selectTag(topic);
    topicList.appendChild(div);
  }
  if (!sorted.length) {
    topicList.innerHTML = '<div style="padding:6px 16px;font-size:12px;color:var(--dim)">No topics</div>';
  }
}

/* =====================================================================
   Items
   ===================================================================== */
async function loadItems() {
  document.getElementById('listLoading').style.display = 'block';
  document.getElementById('listEmpty').style.display = 'none';

  let path = '/api/library?limit=500';
  if (currentCategory) path += `&category=${encodeURIComponent(currentCategory)}`;
  if (currentTag)      path += `&tag=${encodeURIComponent(currentTag)}`;
  if (currentQuery)    path += `&q=${encodeURIComponent(currentQuery)}`;

  try {
    const data = await api(path);
    items = data.items;
    renderItemList(items);
    document.getElementById('listCount').textContent = `${items.length} item${items.length !== 1 ? 's' : ''}`;
  } catch (e) { console.error(e); }

  document.getElementById('listLoading').style.display = 'none';
  if (!items.length) document.getElementById('listEmpty').style.display = 'block';
}

function renderItemList(list) {
  const scroll = document.getElementById('itemScroll');
  scroll.querySelectorAll('.item-card').forEach(el => el.remove());
  for (const item of list) {
    const div = document.createElement('div');
    div.className = 'item-card' + (item.id === currentItemId ? ' active' : '');
    div.dataset.id = item.id;
    const date = (item.added || '').slice(0, 10);
    div.innerHTML = `
      <div class="item-title">${esc(item.title)}</div>
      <div class="item-meta">${esc(item.category)} · ${item.pub_date ? esc(item.pub_date) : date}</div>
      ${item.summary ? `<div class="item-summary">${esc(item.summary)}</div>` : ''}
      <div class="tags">${(item.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>`;
    div.onclick = () => loadDetail(item.id);
    scroll.appendChild(div);
  }
}

/* =====================================================================
   Search
   ===================================================================== */
function debounceSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    currentQuery = document.getElementById('searchInput').value.trim();
    if (currentQuery) {
      showSearchView();
      await runSearch();
    } else {
      hideSearchView();
      await loadItems();
    }
  }, 350);
}

function showSearchView() {
  // Deactivate nav items — search is not a nav view
  document.querySelectorAll('.nav-view-item').forEach(el => el.classList.remove('active'));
  document.getElementById('listPanel').style.display = 'none';
  document.getElementById('detailPanel').style.display = 'none';
  document.getElementById('querySkillsView').style.display = 'none';
  document.getElementById('rssViewWrapper').style.display = 'none';
  document.getElementById('toolsViewWrapper').style.display = 'none';
  document.getElementById('navCatSection').style.display = 'none';
  document.getElementById('navTagSection').style.display = 'none';
  document.getElementById('searchViewWrapper').style.display = 'flex';
}

function hideSearchView() {
  document.getElementById('searchViewWrapper').style.display = 'none';
  // Restore library view
  if (currentView === 'library' || currentView === 'search') {
    currentView = 'library';
    switchView('library');
  }
}

async function runSearch() {
  document.getElementById('searchResultsStatus').textContent = 'Searching…';
  document.getElementById('searchGroupLibrary').innerHTML = '';
  document.getElementById('searchGroupDigest').innerHTML = '';
  document.getElementById('searchGroupTools').innerHTML = '';
  try {
    const q = currentQuery.toLowerCase();
    const [libData, toolData, digestPages] = await Promise.all([
      api('/api/library/search', { method: 'POST', body: JSON.stringify({ query: currentQuery, top_k: 40 }) })
        .catch(() => ({ results: [] })),
      api(`/api/tools/search?q=${encodeURIComponent(currentQuery)}`).catch(() => ({ results: [] })),
      api('/api/digest/pages').catch(() => []),
    ]);

    const library = libData.results || [];

    renderSearchGroup('searchGroupLibrary', 'Library', library, r => () => {
      window.open(`${location.origin}${location.pathname}#item=${r.item_id}`, '_blank');
    });

    const digestResults = (digestPages || [])
      .filter(p => p.title.toLowerCase().includes(q) || (p.tags || []).some(t => t.toLowerCase().includes(q)) || p.category.toLowerCase().includes(q))
      .map(p => ({ title: p.title, url: null, category: p.category, content: (p.tags || []).join(', '), _page_id: p.page_id }));
    renderSearchGroup('searchGroupDigest', 'Digest', digestResults, r => () => {
      switchView('digest');
      loadDigestPage(r._page_id);
    });

    const toolResults = (toolData.results || []).map(r => ({
      title: r.full_name,
      url: r.url,
      category: r.language || '',
      content: r.description,
      item_id: null,
      _tool_repo: r,
    }));
    renderSearchGroup('searchGroupTools', 'Tools', toolResults, r => () => {
      window.open(`${location.origin}${location.pathname}#tool=${encodeURIComponent(r.title)}`, '_blank');
    });

    const total = library.length + digestResults.length + toolResults.length;
    document.getElementById('searchResultsStatus').textContent =
      `${total} result${total !== 1 ? 's' : ''} for "${currentQuery}" — Library: ${library.length}, Digest: ${digestResults.length}, Tools: ${toolResults.length}`;
  } catch (e) {
    document.getElementById('searchResultsStatus').textContent = 'Search failed: ' + e.message;
  }
}

function renderSearchGroup(containerId, heading, results, clickFn) {
  const el = document.getElementById(containerId);
  if (!results.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="search-group-heading">${esc(heading)} <span style="font-weight:400;opacity:.6;">(${results.length})</span></div>`;
  for (const r of results) {
    const card = document.createElement('div');
    card.className = 'search-result-card';
    const snippet = (r.content || '').replace(/[#*`>\-]/g, '').trim().slice(0, 180);
    const displayUrl = r.url && !r.url.startsWith('wiki://') ? r.url.replace(/^https?:\/\//, '').slice(0, 60) : '';
    card.innerHTML = `
      <div class="search-result-title">${esc(r.title)}</div>
      <div class="search-result-meta">${esc(r.category)}${displayUrl ? ` · <span style="color:var(--hi);">${esc(displayUrl)}</span>` : ''}</div>
      ${snippet ? `<div class="search-result-snippet">${esc(snippet)}</div>` : ''}`;
    card.onclick = clickFn(r);
    el.appendChild(card);
  }
}

/* =====================================================================
   Detail
   ===================================================================== */
async function loadDetail(id) {
  currentItemId = id;
  document.querySelectorAll('.item-card').forEach(el =>
    el.classList.toggle('active', el.dataset.id === id));

  const item = await api(`/api/items/${id}`);
  const date = (item.added || '').slice(0, 10);

  document.getElementById('detailEmpty').style.display = 'none';
  const dc = document.getElementById('detailContent');
  dc.style.display = 'block';

  const hasSnap  = !!item.has_snapshot;
  const hasPdf   = !!item.has_original && item.content_type === 'pdf';
  const hasImage = !!item.has_original && item.content_type === 'image';
  const hasUrl   = item.content_type === 'url' || item.content_type === 'pdf';
  const snapshotUrl = `${API}/api/items/${id}/snapshot?key=${encodeURIComponent(KEY)}`;
  const pdfUrl      = `${API}/api/items/${id}/original?key=${encodeURIComponent(KEY)}`;
  const imageUrl    = `${API}/api/items/${id}/original?key=${encodeURIComponent(KEY)}`;

  // Show viewer toggle for any URL/PDF item; snapshot tab only enabled if snapshot exists
  const hasViewer = hasSnap || hasPdf;
  const showSwitch = hasViewer || hasUrl;
  const viewerSrc  = hasPdf ? pdfUrl : snapshotUrl;

  const metaRows = [
    ['id',           item.id],
    ['category',     item.category],
    ['source',       item.source],
    ['content_type', item.content_type],
    ['pub_date',     item.pub_date || '—'],
    ['added',        item.added],
    ['updated',      item.updated],
    ['word_count',   item.word_count],
    ['embedded',     item.embedded ? 'yes' : 'no'],
    ['has_snapshot', item.has_snapshot ? 'yes' : 'no'],
    ['has_original', item.has_original ? 'yes' : 'no'],
    ['classified_by',item.classified_by || '—'],
    ['content_hash', item.content_hash],
    ['url',          item.url || '—'],
  ].map(([k,v]) => `<tr><td>${esc(String(k))}</td><td>${esc(String(v))}</td></tr>`).join('');

  dc.innerHTML = `
    <div class="detail-title">${esc(item.title)}</div>
    <div class="detail-meta">
      <span>${esc(item.category)}</span>
      <span>${date}</span>
      <span>${item.word_count} words</span>
      ${item.pub_date ? `<span>pub: ${esc(item.pub_date)}</span>` : ''}
      ${item.url ? `<a href="${esc(item.url)}" target="_blank">Source ↗</a>` : ''}
    </div>
    <div class="tags" style="margin-bottom:12px">
      ${(item.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}
    </div>
    <div class="detail-actions">
      <button class="btn" onclick="openEdit('${esc(id)}')">Edit</button>
      <button class="btn" onclick="reclassify('${esc(id)}', this)">Reclassify</button>
      <button class="btn" onclick="openMetaOverlay()">Metadata</button>
      <button class="btn ${(item.tags||[]).includes('followup') ? 'primary' : ''}" id="followupToggleBtn" onclick="toggleFollowup('${esc(id)}', this)" title="Toggle followup">${(item.tags||[]).includes('followup') ? '🔖 Followup' : '🔖'}</button>
      <button class="btn" id="addToDigestBtn" data-item-tags="${esc(JSON.stringify(item.tags||[]))}" onclick="addToDigest('${esc(id)}', this)" title="Add to Digest (AI-generated summary)">📝 Add to Digest (AI)</button>
      <button class="btn" id="addToDigestMdBtn" onclick="addToDigestMarkdown('${esc(id)}', this)" title="Add raw markdown to Digest">📝 Add to Digest (Markdown)</button>
      ${hasViewer ? `<span class="view-switch">
        <button id="viewBtnSnapshot" onclick="setView('snapshot')" class="active">Snapshot</button>
        <button id="viewBtnMarkdown" onclick="setView('markdown')">Markdown</button>
      </span>` : ''}
      <button class="btn danger" style="margin-left:auto" onclick="deleteItem('${esc(id)}')">Delete</button>
    </div>
    ${item.summary ? `<div class="detail-summary">${esc(item.summary)}</div>` : ''}
    ${hasImage ? `<div style="margin-bottom:12px"><img src="${imageUrl}" onclick="openLightbox(this.src)" style="max-width:100%;max-height:400px;border-radius:6px;border:1px solid var(--border);display:block;cursor:zoom-in;"></div>` : ''}
    ${hasViewer
      ? `<iframe id="snapshotFrame" src="${viewerSrc}" ${hasPdf ? '' : 'sandbox="allow-same-origin allow-popups allow-scripts"'}></iframe>`
      : ''}
    <div class="detail-body" id="detailTextBody" style="${hasViewer ? 'display:none' : ''}"></div>`;

  window._currentMetaRows = metaRows;
  window._showingSnapshot = hasViewer;

  // Render markdown content
  const mdEl = document.getElementById('detailTextBody');
  if (mdEl) {
    const assetBase = `${API}/api/items/${item.id}/assets/`;
    const md = (item.content || '').replace(/\]\(assets\//g, `](${assetBase}`);
    mdEl.innerHTML = typeof marked !== 'undefined'
      ? DOMPurify.sanitize(marked.parse(md, { breaks: false, gfm: true }))
      : `<pre style="white-space:pre-wrap">${esc(md)}</pre>`;
  }
}

function openMetaOverlay() {
  document.getElementById('metaTableBody').innerHTML = window._currentMetaRows || '';
  document.getElementById('metaOverlay').classList.add('open');
}

function closeMetaOverlay() {
  document.getElementById('metaOverlay').classList.remove('open');
}

function openLightbox(src) {
  const lb = document.getElementById('lightbox');
  document.getElementById('lightboxImg').src = src;
  lb.style.display = 'flex';
}

function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
}

function setView(view) {
  const frame = document.getElementById('snapshotFrame');
  const text  = document.getElementById('detailTextBody');
  const btnSnap = document.getElementById('viewBtnSnapshot');
  const btnMd   = document.getElementById('viewBtnMarkdown');
  if (!text) return;
  const isSnapshot = view === 'snapshot';
  if (frame) frame.style.display = isSnapshot ? '' : 'none';
  text.style.display = isSnapshot ? 'none' : '';
  if (btnSnap) btnSnap.classList.toggle('active', isSnapshot);
  if (btnMd)   btnMd.classList.toggle('active', !isSnapshot);
  window._showingSnapshot = isSnapshot;
}

/* =====================================================================
   Query view
   ===================================================================== */
function populateQueryCatFilter() {
  const sel = document.getElementById('queryCatFilter');
  sel.innerHTML = '<option value="">All categories</option>';
  for (const c of allCategories) {
    const o = document.createElement('option');
    o.value = c.name; o.textContent = c.name;
    sel.appendChild(o);
  }
}

async function loadQueryModels() {
  try {
    const data = await api('/api/config/models');
    const sel = document.getElementById('queryModelSelect');
    const prev = sel.value;
    sel.innerHTML = '';
    for (const m of data.models) {
      const o = document.createElement('option');
      o.value = m; o.textContent = m;
      if (m === (prev || data.default)) o.selected = true;
      sel.appendChild(o);
    }
  } catch (e) { /* non-fatal */ }
}

async function runQuery() {
  const q     = document.getElementById('queryInput').value.trim();
  if (!q) return;
  const cat   = document.getElementById('queryCatFilter').value;
  const model = document.getElementById('queryModelSelect').value;
  document.getElementById('queryAnswer').textContent = 'Thinking…';
  document.getElementById('queryAnswer').style.color = 'var(--dim)';
  document.getElementById('querySources').innerHTML = '';
  document.getElementById('queryTools').innerHTML = '';
  try {
    const data = await api('/api/query', {
      method: 'POST',
      body: JSON.stringify({ question: q, category: cat || undefined, top_k: 8, model: model || undefined }),
    });
    document.getElementById('queryAnswer').style.color = '';
    let answerHtml = '';
    if (data.thinking) {
      answerHtml += `<details class="query-thinking"><summary>Reasoning</summary><div class="query-thinking-body">${esc(data.thinking)}</div></details>`;
    }
    answerHtml += DOMPurify.sanitize(marked.parse(data.answer, { gfm: true }));
    document.getElementById('queryAnswer').innerHTML = answerHtml;
    if (data.sources && data.sources.length) {
      document.getElementById('querySources').innerHTML =
        '<div class="query-section-label">Sources</div>' +
        data.sources.map(s =>
          s.url
            ? `<a class="source-chip" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.url)}">${esc(s.title)}</a>`
            : `<a class="source-chip" href="#item=${esc(s.item_id)}" title="Open in library">${esc(s.title)}</a>`
        ).join('');
    } else {
      document.getElementById('querySources').innerHTML = '';
    }
    if (data.tools && data.tools.length) {
      const toolsDiv = document.getElementById('queryTools');
      toolsDiv.innerHTML = '<div class="query-section-label">Tools</div>';
      for (const t of data.tools) {
        const chip = document.createElement('a');
        chip.className = 'source-chip';
        chip.href = `${location.origin}${location.pathname}#tool=${encodeURIComponent(t.title)}`;
        chip.target = '_blank';
        chip.title = t.url;
        chip.textContent = t.title;
        toolsDiv.appendChild(chip);
      }
    } else {
      document.getElementById('queryTools').innerHTML = '';
    }
  } catch (e) {
    document.getElementById('queryAnswer').style.color = 'var(--dim)';
    document.getElementById('queryAnswer').textContent = 'Error: ' + e.message;
  }
}

/* =====================================================================
   Skills view
   ===================================================================== */
function populateSkillCat() {
  for (const sel of ['skillCat']) {
    const el = document.getElementById(sel);
    el.innerHTML = '<option value="">All categories</option>';
    for (const c of allCategories) {
      const o = document.createElement('option');
      o.value = c.name; o.textContent = c.name;
      el.appendChild(o);
    }
  }
}

async function generateSkill() {
  const topic = document.getElementById('skillTopic').value.trim();
  if (!topic) return;
  const desc  = document.getElementById('skillDesc').value.trim();
  const cat   = document.getElementById('skillCat').value;
  const out   = document.getElementById('skillOutput');
  out.style.display = 'block';
  out.textContent = 'Generating…';
  try {
    const data = await api('/api/skills/generate', {
      method: 'POST',
      body: JSON.stringify({
        topic,
        description: desc || undefined,
        categories: cat ? [cat] : undefined,
      }),
    });
    out.textContent = data.content;
    loadSkills();
  } catch (e) {
    out.textContent = 'Error: ' + e.message;
  }
}

async function loadSkills() {
  const data = await api('/api/skills');
  const list = document.getElementById('skillList');
  list.innerHTML = '';
  if (!data.length) {
    list.innerHTML = '<div style="font-size:13px;color:var(--muted)">No skills generated yet.</div>';
    return;
  }
  for (const s of data) {
    const div = document.createElement('div');
    div.className = 'skill-chip';
    div.innerHTML = `
      <span class="skill-name">${esc(s.topic)}</span>
      <span class="skill-date">${s.generated.slice(0,10)}</span>`;
    div.onclick = async () => {
      const content = await api(`/api/skills/${encodeURIComponent(s.topic)}`);
      document.getElementById('skillOutput').style.display = 'block';
      document.getElementById('skillOutput').textContent = content;
    };
    list.appendChild(div);
  }
}

/* =====================================================================
   Planner
   ===================================================================== */

async function generatePlan(btn) {
  const description = (document.getElementById('plannerInput')?.value || '').trim();
  if (!description) { alert('Please describe the engagement.'); return; }

  const status = document.getElementById('plannerStatus');
  const output = document.getElementById('plannerOutput');

  btn.disabled = true;
  btn.textContent = 'Generating…';
  status.style.display = '';
  status.innerHTML = '<span class="spinner"></span> Pass 1: Analysing engagement parameters…';
  output.style.display = 'none';
  output.innerHTML = '';

  // Simulate pass status updates during the single long request
  const passes = [
    'Pass 1: Analysing engagement parameters…',
    'Pass 2: Searching knowledge base (recon, exploitation, tools, lateral movement)…',
    'Pass 3: Drafting plan…',
    'Pass 4: Enriching tools and command reference…',
  ];
  let passIdx = 0;
  const passTimer = setInterval(() => {
    passIdx = Math.min(passIdx + 1, passes.length - 1);
    status.innerHTML = `<span class="spinner"></span> ${passes[passIdx]}`;
  }, 18000); // advance every ~18s

  try {
    const data = await api('/api/planner/generate', {
      method: 'POST',
      body: JSON.stringify({ description }),
    });
    clearInterval(passTimer);
    const sourceCount = (data.content.match(/^## Library References/m)) ? '—' : '';
    status.innerHTML = `✓ Plan generated${sourceCount ? '' : ''} — saved as <em>${esc(data.slug)}</em>`;
    output.style.display = 'block';
    output.innerHTML = typeof marked !== 'undefined'
      ? DOMPurify.sanitize(marked.parse(data.content, { breaks: false, gfm: true }))
      : `<pre style="white-space:pre-wrap">${esc(data.content)}</pre>`;
    loadPlans();
  } catch (e) {
    clearInterval(passTimer);
    status.innerHTML = `<span style="color:var(--hi)">Error: ${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate Plan';
  }
}

async function loadPlans() {
  const data = await api('/api/planner').catch(() => []);
  const list = document.getElementById('plannerList');
  list.innerHTML = '';
  if (!data.length) {
    list.innerHTML = '<div style="font-size:13px;color:var(--muted)">No plans generated yet.</div>';
    return;
  }
  for (const p of data) {
    const div = document.createElement('div');
    div.className = 'skill-chip';
    div.innerHTML = `
      <span class="skill-name">${esc(p.title)}</span>
      <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
        <span class="skill-date">${p.generated.slice(0,10)}</span>
        <button class="rss-icon-btn" title="Delete" onclick="event.stopPropagation();deletePlan('${esc(p.slug)}',this)">✕</button>
      </div>`;
    div.onclick = async () => {
      const plan = await api(`/api/planner/${encodeURIComponent(p.slug)}`);
      const output = document.getElementById('plannerOutput');
      const status = document.getElementById('plannerStatus');
      status.style.display = '';
      status.innerHTML = `Showing: <em>${esc(plan.title)}</em>`;
      output.style.display = 'block';
      output.innerHTML = typeof marked !== 'undefined'
        ? DOMPurify.sanitize(marked.parse(plan.content, { breaks: false, gfm: true }))
        : `<pre style="white-space:pre-wrap">${esc(plan.content)}</pre>`;
      output.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    list.appendChild(div);
  }
}

async function deletePlan(slug, btn) {
  btn.disabled = true;
  try {
    await api(`/api/planner/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    loadPlans();
  } catch (e) {
    btn.disabled = false;
  }
}

/* =====================================================================
   Ingest modal
   ===================================================================== */
function openIngest() {
  // Populate category selects from live categories
  for (const id of ['ingestUrlCat','ingestTextCat','ingestPdfCat','ingestImageCat']) {
    const sel = document.getElementById(id);
    sel.innerHTML = '<option value="">Auto-classify</option>';
    for (const c of allCategories) {
      const o = document.createElement('option'); o.value = c.name; o.textContent = c.name;
      sel.appendChild(o);
    }
  }
  document.getElementById('ingestStatus').textContent = '';
  document.getElementById('ingestModal').classList.remove('hidden');
}

function closeIngest() {
  document.getElementById('ingestModal').classList.add('hidden');
  const saveBtn = document.querySelector('#ingestModal .btn.primary');
  const cancelBtn = document.querySelector('#ingestModal .btn:not(.primary)');
  if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save'; }
  if (cancelBtn) cancelBtn.disabled = false;
  const st = document.getElementById('ingestStatus');
  st.textContent = '';
  st.className = '';
}

function switchIngestTab(tab) {
  ingestTab = tab;
  document.querySelectorAll('.modal-tab').forEach((el, i) => {
    el.classList.toggle('active', ['url','text','pdf','image'][i] === tab);
  });
  document.querySelectorAll('.modal-pane').forEach(el => el.classList.remove('active'));
  document.getElementById(`pane-${tab}`).classList.add('active');
}

function onIngestImageChange(input) {
  const wrap = document.getElementById('ingestImagePreviewWrap');
  const img  = document.getElementById('ingestImagePreview');
  if (input.files && input.files[0]) {
    img.src = URL.createObjectURL(input.files[0]);
    wrap.style.display = 'block';
  } else {
    wrap.style.display = 'none';
    img.src = '';
  }
}

async function submitIngest() {
  const status  = document.getElementById('ingestStatus');
  const saveBtn = document.querySelector('#ingestModal .btn.primary');
  const cancelBtn = document.querySelector('#ingestModal .btn:not(.primary)');

  const setStatus = (msg, cls = '') => { status.textContent = msg; status.className = cls; };
  const setBusy = (busy) => {
    saveBtn.disabled = busy;
    cancelBtn.disabled = busy;
    saveBtn.textContent = busy ? '⟳ Saving…' : 'Save';
  };

  setBusy(true);
  setStatus('Fetching and processing…');

  try {
    let result;
    if (ingestTab === 'url') {
      const url  = document.getElementById('ingestUrl').value.trim();
      const cat  = document.getElementById('ingestUrlCat').value;
      const tags = parseTags(document.getElementById('ingestUrlTags').value);
      setStatus('Fetching page…');
      result = await api('/api/ingest/url', {
        method: 'POST',
        body: JSON.stringify({ url, category: cat||undefined, tags: tags.length?tags:undefined }),
      });
    } else if (ingestTab === 'text') {
      const title = document.getElementById('ingestTextTitle').value.trim();
      const body  = document.getElementById('ingestTextBody').value.trim();
      const cat   = document.getElementById('ingestTextCat').value;
      const tags  = parseTags(document.getElementById('ingestTextTags').value);
      setStatus('Classifying and embedding…');
      result = await api('/api/ingest/text', {
        method: 'POST',
        body: JSON.stringify({ title, body, category: cat||undefined, tags: tags.length?tags:undefined }),
      });
    } else if (ingestTab === 'pdf') {
      const fileInput = document.getElementById('ingestPdfFile');
      const cat       = document.getElementById('ingestPdfCat').value;
      const tags      = parseTags(document.getElementById('ingestPdfTags').value);
      if (!fileInput.files.length) { setStatus('Select a file', 'err'); setBusy(false); return; }
      const form = new FormData();
      form.append('file', fileInput.files[0]);
      if (cat) form.append('category', cat);
      if (tags.length) form.append('tags', tags.join(','));
      setStatus('Uploading and processing PDF…');
      result = await fetch(API + '/api/ingest/pdf', {
        method: 'POST', headers: { 'X-API-Key': KEY }, body: form,
      }).then(r => r.json());
      if (result.detail) throw new Error(result.detail);
    } else {
      const fileInput = document.getElementById('ingestImageFile');
      const cat       = document.getElementById('ingestImageCat').value;
      const tags      = parseTags(document.getElementById('ingestImageTags').value);
      if (!fileInput.files.length) { setStatus('Select an image', 'err'); setBusy(false); return; }
      const form = new FormData();
      form.append('file', fileInput.files[0]);
      if (cat) form.append('category', cat);
      if (tags.length) form.append('tags', tags.join(','));
      setStatus('Analyzing image…');
      result = await fetch(API + '/api/ingest/image', {
        method: 'POST', headers: { 'X-API-Key': KEY }, body: form,
      }).then(r => r.json());
      if (result.detail) throw new Error(result.detail);
    }

    setStatus('Updating library…');
    // Reset category/tag filter so the new item is visible regardless of where it was classified
    if (!result.duplicate) {
      currentCategory = '';
      currentTag = '';
      document.querySelectorAll('.cat-item').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tag-chip').forEach(el => el.classList.remove('active'));
      document.getElementById('listViewLabel').textContent = 'All';
    }
    await Promise.all([loadCategories(), loadTopTags(), loadItems()]);
    if (!result.duplicate && result.item_id) loadDetail(result.item_id);

    const msg = result.duplicate ? `Already in library: ${result.title}` : `✓ Added: ${result.title}`;
    setStatus(msg, result.duplicate ? '' : 'ok');
    setTimeout(closeIngest, 2000);
  } catch (e) {
    setStatus(`Error: ${e.message}`, 'err');
    setBusy(false);
    status.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function parseTags(raw) {
  return raw.split(',').map(t => t.trim()).filter(Boolean);
}

let _errorPopupTimer = null;
function showErrorPopup(msg) {
  const el = document.getElementById('errorPopup');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('visible');
  clearTimeout(_errorPopupTimer);
  _errorPopupTimer = setTimeout(() => el.classList.remove('visible'), 8000);
}

/* =====================================================================
   Edit modal
   ===================================================================== */
let currentEditTags = [];

function renderTagPills() {
  const editor = document.getElementById('tagEditor');
  const input  = document.getElementById('tagInput');
  // Remove existing pills
  editor.querySelectorAll('.tag-pill').forEach(p => p.remove());
  // Insert pills before the input
  currentEditTags.forEach(tag => {
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.innerHTML = `${esc(tag)}<span class="remove" onclick="removeTag('${esc(tag)}')">&times;</span>`;
    editor.insertBefore(pill, input);
  });
}

function addTag(raw) {
  const tag = raw.trim().toLowerCase();
  if (!tag || currentEditTags.includes(tag)) return;
  currentEditTags.push(tag);
  renderTagPills();
  renderCategoryTagPills();
  document.getElementById('tagInput').value = '';
}

function removeTag(tag) {
  currentEditTags = currentEditTags.filter(t => t !== tag);
  renderTagPills();
  renderCategoryTagPills();
}

function onTagKeydown(e) {
  const input = e.target;
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    if (input.value.trim()) addTag(input.value);
  } else if (e.key === 'Backspace' && input.value === '' && currentEditTags.length) {
    currentEditTags.pop();
    renderTagPills();
  }
}

function onTagInput(input) {
  if (input.value.includes(',')) {
    input.value.split(',').forEach(t => { if (t.trim()) addTag(t); });
    input.value = '';
  }
}

function onTagChange(input) {
  if (input.value.trim()) addTag(input.value);
}

function _resetSuggester() {
  document.getElementById('suggestResults').style.display = 'none';
  document.getElementById('suggestResults').innerHTML = '';
  document.getElementById('suggestSpinner').style.display = 'none';
  document.getElementById('suggestBtn').style.display = '';
  document.getElementById('suggestBtn').disabled = false;
  document.getElementById('tagSuggester').removeAttribute('open');
  document.getElementById('categoryTagPills').style.display = 'none';
  document.getElementById('categoryTagPills').innerHTML = '';
}

function openEdit(id) {
  const item = items.find(i => i.id === id);
  if (!item) return;
  document.getElementById('editTitle').value = item.title || '';
  currentEditTags = [...(item.tags || [])];
  renderTagPills();
  _resetSuggester();

  // Populate from all configured categories (not just ones with items)
  const sel = document.getElementById('editCategory');
  sel.innerHTML = '';
  const cats = allConfigCategories.length ? allConfigCategories : allCategories.map(c => c.name);
  for (const c of cats) {
    const name = typeof c === 'string' ? c : c.name;
    const o = document.createElement('option');
    o.value = name; o.textContent = name;
    if (name === item.category) o.selected = true;
    sel.appendChild(o);
  }

  // Load tag suggestions for current category
  loadTagsForCategory(item.category);
  sel.onchange = () => { loadTagsForCategory(sel.value); _resetSuggester(); };

  document.getElementById('editModal').dataset.id = id;
  document.getElementById('editModal').classList.remove('hidden');
}

let _tagSuggestions = [];

async function loadTagsForCategory(category) {
  if (!category) return;
  try {
    _tagSuggestions = await api(`/api/config/tags/${encodeURIComponent(category)}`);
    const dl = document.getElementById('editTagSuggestions');
    dl.innerHTML = _tagSuggestions.map(t => `<option value="${esc(t)}">`).join('');
    renderCategoryTagPills();
  } catch (e) { _tagSuggestions = []; }
}

function renderCategoryTagPills() {
  const container = document.getElementById('categoryTagPills');
  if (!_tagSuggestions.length) { container.style.display = 'none'; return; }
  container.style.display = 'flex';
  container.innerHTML = '';
  for (const tag of _tagSuggestions) {
    const pill = document.createElement('span');
    pill.className = 'cat-tag-pill' + (currentEditTags.includes(tag) ? ' added' : '');
    pill.textContent = tag;
    pill.title = currentEditTags.includes(tag) ? 'Already added' : 'Click to add';
    pill.onclick = () => {
      if (pill.classList.contains('added')) return;
      addTag(tag);
      pill.classList.add('added');
      pill.title = 'Already added';
    };
    container.appendChild(pill);
  }
}


function closeEdit() {
  document.getElementById('editModal').classList.add('hidden');
}

async function saveEdit() {
  const id = document.getElementById('editModal').dataset.id;
  const cat = document.getElementById('editCategory').value;
  // Flush any partially typed tag/keyword in the inputs
  const partialInput = document.getElementById('tagInput').value.trim();
  if (partialInput) addTag(partialInput);
  // Add any new tags (not in taxonomy) to the category
  const newTags = currentEditTags.filter(t => !_tagSuggestions.includes(t));
  for (const tag of newTags) {
    try {
      await api(`/api/config/tags/${encodeURIComponent(cat)}`, {
        method: 'POST', body: JSON.stringify({ tag }),
      });
    } catch (e) { /* non-fatal */ }
  }
  if (newTags.length) await loadTagsForCategory(cat);
  await api(`/api/items/${id}`, { method: 'PATCH', body: JSON.stringify({
    title:    document.getElementById('editTitle').value.trim(),
    category: cat,
    tags:     currentEditTags,
  })});
  closeEdit();
  await Promise.all([loadCategories(), loadTopTags(), loadItems()]);
  loadDetail(id);
}


async function suggestTags() {
  const id = document.getElementById('editModal').dataset.id;
  const cat = document.getElementById('editCategory').value;
  if (!cat || !id) return;
  const btn = document.getElementById('suggestBtn');
  const spinner = document.getElementById('suggestSpinner');
  const results = document.getElementById('suggestResults');

  btn.disabled = true;
  btn.style.display = 'none';
  spinner.style.display = 'inline-flex';
  results.style.display = 'none';
  results.innerHTML = '';

  try {
    const data = await api(`/api/items/${encodeURIComponent(id)}/suggest-tags`, {
      method: 'POST', body: JSON.stringify({ category: cat, existing_tags: currentEditTags }),
    });
    const suggested = data.suggested || [];
    if (!suggested.length) {
      results.innerHTML = '<span style="font-size:12px;color:var(--dim)">No suggestions returned.</span>';
      results.style.display = 'flex';
      return;
    }
    results.style.display = 'flex';
    for (const tag of suggested) {
      const pill = document.createElement('span');
      pill.className = 'suggest-pill';
      pill.title = 'Click to add';
      pill.textContent = tag;
      pill.onclick = () => {
        if (pill.classList.contains('added')) return;
        addTag(tag);
        pill.classList.add('added');
        pill.title = 'Added';
      };
      results.appendChild(pill);
    }
  } catch (e) {
    results.innerHTML = '<span style="font-size:12px;color:var(--hi)">Error fetching suggestions.</span>';
    results.style.display = 'flex';
  } finally {
    btn.disabled = false;
    btn.style.display = '';
    spinner.style.display = 'none';
  }
}

/* =====================================================================
   Delete / Reclassify
   ===================================================================== */
/* =====================================================================
   Followup / Reading list
   ===================================================================== */
async function toggleFollowup(id, btn) {
  const isFollowup = btn.classList.contains('primary');
  const method = isFollowup ? 'DELETE' : 'POST';
  try {
    const updated = await api(`/api/items/${id}/followup`, { method });
    const nowFollowup = (updated.tags || []).includes('followup');
    btn.textContent = nowFollowup ? '🔖 Followup' : '🔖';
    btn.classList.toggle('primary', nowFollowup);
    updateFollowupBadge();
  } catch (e) { console.error(e); }
}

async function toggleToolFollowup(btn) {
  if (!currentToolRepo) return;
  const isFollowup = !!currentToolRepo._followup;
  if (isFollowup) {
    // Remove: need the ingested item_id
    if (currentToolRepo._followup_item_id) {
      await api(`/api/items/${currentToolRepo._followup_item_id}/followup`, { method: 'DELETE' });
    }
    currentToolRepo._followup = false;
    currentToolRepo._followup_item_id = null;
  } else {
    // Ingest if not already, then tag
    let item_id = currentToolRepo._ingested_item_id;
    if (!item_id) {
      // Ingest it first
      try {
        const r = await api(`/api/tools/${encodeURIComponent(currentToolId)}/ingest`, {
          method: 'POST', body: JSON.stringify({ node_ids: [currentToolRepo.node_id] })
        });
        item_id = r.item_ids?.[0];
        if (item_id) {
          currentToolRepo.seen = true;
          currentToolRepo._ingested_item_id = item_id;
          const ingestBtn = document.getElementById('toolDetailIngestBtn');
          if (ingestBtn) { ingestBtn.textContent = '✓ Ingested'; ingestBtn.disabled = true; }
        }
      } catch (e) { console.error('Ingest for followup failed:', e); return; }
    }
    if (item_id) {
      await api(`/api/items/${item_id}/followup`, { method: 'POST' });
      currentToolRepo._followup = true;
      currentToolRepo._followup_item_id = item_id;
    }
  }
  btn.textContent = currentToolRepo._followup ? '🔖 Followup' : '🔖';
  btn.classList.toggle('primary', !!currentToolRepo._followup);
  updateFollowupBadge();
}

async function loadFollowup() {
  const list = document.getElementById('followupList');
  const empty = document.getElementById('followupEmpty');
  const count = document.getElementById('followupCount');
  list.innerHTML = '<div style="padding:12px;font-size:12px;color:var(--dim);">Loading…</div>';
  empty.style.display = 'none';

  const data = await api('/api/followup?limit=500');
  const items = data.items || [];
  count.textContent = `${items.length} item${items.length !== 1 ? 's' : ''}`;
  list.innerHTML = '';

  if (!items.length) { empty.style.display = 'block'; return; }

  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'item-card';
    row.dataset.id = item.id;
    const date = (item.added || '').slice(0, 10);
    row.innerHTML = `
      <div class="item-title">${esc(item.title)}</div>
      <div class="item-meta">${esc(item.category)} · ${item.pub_date ? esc(item.pub_date) : date}</div>
      ${item.summary ? `<div class="item-summary">${esc(item.summary)}</div>` : ''}`;
    row.onclick = () => loadFollowupDetail(item.id);
    list.appendChild(row);
  }
  updateFollowupBadge(items.length);
}

async function loadFollowupDetail(id) {
  document.querySelectorAll('#followupList .item-card').forEach(el =>
    el.classList.toggle('active', el.dataset.id === id));
  const panel = document.getElementById('followupDetailPanel');
  panel.innerHTML = '<div style="padding:20px;font-size:12px;color:var(--dim);">Loading…</div>';
  let item;
  try {
    item = await api(`/api/items/${id}`);
  } catch (e) {
    panel.innerHTML = `<div style="padding:20px;font-size:12px;color:var(--hi);">Failed to load item: ${esc(String(e))}</div>`;
    return;
  }
  const isFollowup = (item.tags || []).includes('followup');
  const date = item.added ? item.added.slice(0,10) : '';
  const visibleTags = (item.tags || []).filter(t => t !== 'followup');
  panel.innerHTML = `
    <div class="detail-title">${esc(item.title)}</div>
    <div class="detail-meta">
      <span>${esc(item.category)}</span>
      <span>${date}</span>
      <span>${item.word_count || 0} words</span>
      ${item.url ? `<a href="${esc(item.url)}" target="_blank">Source ↗</a>` : ''}
    </div>
    <div class="tags" style="margin-bottom:12px">
      ${visibleTags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}
    </div>
    <div class="detail-actions">
      <button class="btn ${isFollowup ? 'primary' : ''}" id="followupDetailToggleBtn"
        onclick="toggleFollowupFromDetail('${esc(id)}', this)">
        ${isFollowup ? '🔖 Remove from Followup' : '🔖 Add to Followup'}
      </button>
      <button class="btn" onclick="switchView('library');loadDetail('${esc(id)}')">Open in Library</button>
    </div>
    ${item.summary ? `<div class="detail-summary">${esc(item.summary)}</div>` : ''}
    <div class="detail-body" id="followupDetailBody"></div>`;

  const mdEl = document.getElementById('followupDetailBody');
  if (mdEl) {
    const assetBase = `${API}/api/items/${item.id}/assets/`;
    const md = (item.content || '').replace(/\]\(assets\//g, `](${assetBase}`);
    mdEl.innerHTML = typeof marked !== 'undefined'
      ? DOMPurify.sanitize(marked.parse(md, { breaks: false, gfm: true }))
      : `<pre style="white-space:pre-wrap">${esc(md)}</pre>`;
  }
}

async function toggleFollowupFromDetail(id, btn) {
  const isFollowup = btn.classList.contains('primary');
  const method = isFollowup ? 'DELETE' : 'POST';
  const updated = await api(`/api/items/${id}/followup`, { method });
  const nowFollowup = (updated.tags || []).includes('followup');
  btn.textContent = nowFollowup ? '🔖 Remove from Followup' : '🔖 Add to Followup';
  btn.classList.toggle('primary', nowFollowup);
  if (!nowFollowup) loadFollowup(); // refresh list when removed
  updateFollowupBadge();
}

async function updateFollowupBadge(count) {
  if (count === undefined) {
    try {
      const data = await api('/api/followup?limit=1');
      count = data.total;
    } catch { return; }
  }
  const badge = document.getElementById('followupBadge');
  if (!badge) return;
  if (count > 0) { badge.textContent = count; badge.style.display = ''; }
  else { badge.style.display = 'none'; }
}

/* =====================================================================
   Digest
   ===================================================================== */
let _myWikiPages = [];
let _currentWikiPageId = null;
let _digestFilterCat = '';
let _digestFilterTag = '';

function selectDigestCategory(cat) {
  _digestFilterCat = cat;
  _digestFilterTag = '';
  document.querySelectorAll('#digestCatList .nav-item, #digestNavAll').forEach(el =>
    el.classList.toggle('active', (el.dataset.cat || '') === cat));
  document.querySelectorAll('#digestTagList .nav-item').forEach(el => el.classList.remove('active'));
  renderDigestPageList();
}

function selectDigestTag(tag) {
  _digestFilterTag = tag;
  _digestFilterCat = '';
  document.querySelectorAll('#digestCatList .nav-item, #digestNavAll').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('#digestTagList .nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.tag === tag));
  renderDigestPageList();
}

async function loadDigestPages() {
  _myWikiPages = await api('/api/digest/pages');

  // Build category nav
  const catCounts = {};
  const tagCounts = {};
  for (const p of _myWikiPages) {
    catCounts[p.category] = (catCounts[p.category] || 0) + 1;
    for (const t of (p.tags || [])) tagCounts[t] = (tagCounts[t] || 0) + 1;
  }
  const catList = document.getElementById('digestCatList');
  catList.innerHTML = '';
  for (const [cat, count] of Object.entries(catCounts).sort()) {
    const div = document.createElement('div');
    div.className = 'nav-item' + (_digestFilterCat === cat ? ' active' : '');
    div.dataset.cat = cat;
    div.innerHTML = esc(cat);
    div.onclick = () => selectDigestCategory(cat);
    catList.appendChild(div);
  }
  // If active cat no longer exists, reset
  if (_digestFilterCat && !catCounts[_digestFilterCat]) _digestFilterCat = '';

  // Build tag nav
  const tagList = document.getElementById('digestTagList');
  tagList.innerHTML = '';
  const sortedTags = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).slice(0, 20);
  if (sortedTags.length) {
    for (const [tag, count] of sortedTags) {
      const div = document.createElement('div');
      div.className = 'nav-item' + (_digestFilterTag === tag ? ' active' : '');
      div.dataset.tag = tag;
      div.innerHTML = esc(tag);
      div.onclick = () => selectDigestTag(tag);
      tagList.appendChild(div);
    }
  } else {
    tagList.innerHTML = '<div style="padding:6px 16px;font-size:12px;color:var(--muted)">No tags yet</div>';
  }

  renderDigestPageList();
  updateDigestBadge(_myWikiPages.length);
}

function renderDigestPageList() {
  const list = document.getElementById('digestPageList');
  const empty = document.getElementById('digestPageEmpty');
  list.innerHTML = '';

  let filtered = _myWikiPages;
  if (_digestFilterCat) filtered = filtered.filter(p => p.category === _digestFilterCat);
  if (_digestFilterTag) filtered = filtered.filter(p => (p.tags || []).includes(_digestFilterTag));

  if (!filtered.length) {
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  for (const p of filtered) {
    const row = document.createElement('div');
    row.className = 'item-card' + (_currentWikiPageId === p.page_id ? ' active' : '');
    row.dataset.pageId = p.page_id;
    const tagsHtml = (p.tags || []).length
      ? `<div class="tags">${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>`
      : '';
    row.innerHTML = `<div class="item-title">${esc(p.title)}</div>
      <div class="item-meta">${esc(p.category)} · ${esc(p.updated.slice(0,10))}</div>
      ${tagsHtml}`;
    row.onclick = () => loadDigestPage(p.page_id);
    list.appendChild(row);
  }
}

async function loadDigestPage(pageId) {
  _resetWikiDetailPanel();
  _currentWikiPageId = pageId;
  // Re-render list to update active state
  renderDigestPageList();
  const panel = document.getElementById('digestPageDetail');
  panel.innerHTML = '<div style="padding:20px;font-size:12px;color:var(--dim);">Loading…</div>';
  const page = await api(`/api/digest/pages/${encodeURIComponent(pageId)}`);
  renderDigestPage(page);
}

function _resetWikiDetailPanel() {
  const panel = document.getElementById('digestPageDetail');
  panel.style.overflowY = 'auto';
  panel.style.display = '';
  panel.style.flexDirection = '';
}

function renderDigestPage(page) {
  _resetWikiDetailPanel();
  const panel = document.getElementById('digestPageDetail');
  const sourceLink = page.source_item_id
    ? `<a href="#" onclick="switchView('library');loadDetail('${esc(page.source_item_id)}');return false;" style="font-size:12px;color:var(--hi);">Open source ↗</a>`
    : (page.source_url ? `<a href="${esc(page.source_url)}" target="_blank" rel="noopener" style="font-size:12px;color:var(--hi);">Source ↗</a>` : '');

  panel.innerHTML = `
    <div style="padding:20px 24px;width:100%;box-sizing:border-box;">
      <div class="detail-title">${esc(page.title)}</div>
      <div class="detail-meta">
        <span>${esc(page.category)}</span>
        <span>updated ${esc(page.updated.slice(0,10))}</span>
        <span>${page.word_count} words</span>
        ${sourceLink}
      </div>
      <div class="tags" style="margin-bottom:12px;">${(page.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
      <div class="detail-actions">
        <button class="btn" onclick="openWikiEdit('${esc(page.page_id)}')">Edit</button>
        <button class="btn danger" style="margin-left:auto" onclick="deleteDigestPage('${esc(page.page_id)}')">Delete</button>
      </div>
      <div class="detail-body" id="digestPageBody"></div>
    </div>`;
  const body = document.getElementById('digestPageBody');
  if (body) {
    body.innerHTML = typeof marked !== 'undefined'
      ? DOMPurify.sanitize(marked.parse(page.content, { breaks: false, gfm: true }))
      : `<pre style="white-space:pre-wrap">${esc(page.content)}</pre>`;
  }
}

/* ----- Wiki edit modal ----- */

let wikiCurrentTags = [];
let _wikiEditPageId = null;
let _wikiTagSuggestions = [];

function wikiModalRenderTagPills() {
  const editor = document.getElementById('wikiModalTagEditor');
  if (!editor) return;
  const input = document.getElementById('wikiModalTagInput');
  editor.querySelectorAll('.tag-pill').forEach(p => p.remove());
  wikiCurrentTags.forEach(tag => {
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.innerHTML = `${esc(tag)}<span class="remove" onclick="wikiModalRemoveTag('${esc(tag)}')">&times;</span>`;
    editor.insertBefore(pill, input);
  });
}

function wikiModalAddTag(raw) {
  const tag = raw.trim().toLowerCase();
  if (!tag || wikiCurrentTags.includes(tag)) return;
  wikiCurrentTags.push(tag);
  wikiModalRenderTagPills();
  wikiModalRenderCatTagPills();
  const input = document.getElementById('wikiModalTagInput');
  if (input) input.value = '';
}

function wikiModalRemoveTag(tag) {
  wikiCurrentTags = wikiCurrentTags.filter(t => t !== tag);
  wikiModalRenderTagPills();
  wikiModalRenderCatTagPills();
}

function wikiModalOnTagKeydown(e) {
  const input = e.target;
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    if (input.value.trim()) wikiModalAddTag(input.value);
  } else if (e.key === 'Backspace' && input.value === '' && wikiCurrentTags.length) {
    wikiCurrentTags.pop();
    wikiModalRenderTagPills();
  }
}

function wikiModalOnTagInput(input) {
  if (input.value.includes(',')) {
    input.value.split(',').forEach(t => { if (t.trim()) wikiModalAddTag(t); });
    input.value = '';
  }
}

function wikiModalOnTagChange(input) {
  if (input.value.trim()) wikiModalAddTag(input.value);
}

async function wikiModalLoadTagsForCategory(category) {
  if (!category) return;
  try {
    _wikiTagSuggestions = await api(`/api/config/tags/${encodeURIComponent(category)}`);
    const dl = document.getElementById('wikiModalTagSuggestions');
    if (dl) dl.innerHTML = _wikiTagSuggestions.map(t => `<option value="${esc(t)}">`).join('');
    wikiModalRenderCatTagPills();
  } catch (e) { _wikiTagSuggestions = []; }
}

function wikiModalRenderCatTagPills() {
  const container = document.getElementById('wikiModalCatTagPills');
  if (!container) return;
  if (!_wikiTagSuggestions.length) { container.style.display = 'none'; return; }
  container.style.display = 'flex';
  container.innerHTML = '';
  for (const tag of _wikiTagSuggestions) {
    const pill = document.createElement('span');
    pill.className = 'cat-tag-pill' + (wikiCurrentTags.includes(tag) ? ' added' : '');
    pill.textContent = tag;
    pill.title = wikiCurrentTags.includes(tag) ? 'Already added' : 'Click to add';
    pill.onclick = () => {
      if (pill.classList.contains('added')) return;
      wikiModalAddTag(tag);
      pill.classList.add('added');
      pill.title = 'Already added';
    };
    container.appendChild(pill);
  }
}

function _resetWikiSuggester() {
  const results = document.getElementById('wikiSuggestResults');
  const spinner = document.getElementById('wikiSuggestSpinner');
  const btn = document.getElementById('wikiSuggestBtn');
  if (results) { results.style.display = 'none'; results.innerHTML = ''; }
  if (spinner) spinner.style.display = 'none';
  if (btn) { btn.style.display = ''; btn.disabled = false; }
  const det = document.getElementById('wikiTagSuggester');
  if (det) det.removeAttribute('open');
}

async function wikiSuggestTags() {
  const pageId = _wikiEditPageId;
  const cat = document.getElementById('wikiModalCategory').value;
  const btn = document.getElementById('wikiSuggestBtn');
  const spinner = document.getElementById('wikiSuggestSpinner');
  const results = document.getElementById('wikiSuggestResults');
  if (!pageId || !cat) return;

  // We need a source_item_id to call the suggest endpoint
  let sourceItemId = null;
  try {
    const pg = await api(`/api/digest/pages/${encodeURIComponent(pageId)}`);
    sourceItemId = pg.source_item_id;
  } catch (_) {}

  btn.disabled = true; btn.style.display = 'none';
  spinner.style.display = 'inline-flex';
  results.style.display = 'none'; results.innerHTML = '';

  try {
    let suggested = [];
    if (sourceItemId) {
      const data = await api(`/api/items/${encodeURIComponent(sourceItemId)}/suggest-tags`, {
        method: 'POST', body: JSON.stringify({ category: cat, existing_tags: wikiCurrentTags }),
      });
      suggested = data.suggested || [];
    } else {
      // Fall back to generic tag list for category
      suggested = _wikiTagSuggestions.filter(t => !wikiCurrentTags.includes(t));
    }
    if (!suggested.length) {
      results.innerHTML = '<span style="font-size:12px;color:var(--dim)">No suggestions returned.</span>';
    } else {
      for (const tag of suggested) {
        const pill = document.createElement('span');
        pill.className = 'suggest-pill';
        pill.title = 'Click to add';
        pill.textContent = tag;
        pill.onclick = () => {
          if (pill.classList.contains('added')) return;
          wikiModalAddTag(tag);
          pill.classList.add('added');
          pill.title = 'Added';
        };
        results.appendChild(pill);
      }
    }
    results.style.display = 'flex';
  } catch (e) {
    results.innerHTML = '<span style="font-size:12px;color:var(--hi)">Error fetching suggestions.</span>';
    results.style.display = 'flex';
  } finally {
    btn.disabled = false; btn.style.display = '';
    spinner.style.display = 'none';
  }
}

async function openWikiEdit(pageId) {
  const page = await api(`/api/digest/pages/${encodeURIComponent(pageId)}`);
  _wikiEditPageId = pageId;
  wikiCurrentTags = [...(page.tags || [])];
  _wikiTagSuggestions = [];
  _resetWikiSuggester();

  document.getElementById('wikiModalTitle').value = page.title || '';
  document.getElementById('wikiModalContent').value = page.content || '';

  // Populate category dropdown from config categories
  const sel = document.getElementById('wikiModalCategory');
  sel.innerHTML = '';
  const cats = allConfigCategories.length ? allConfigCategories : allCategories.map(c => c.name);
  for (const c of cats) {
    const name = typeof c === 'string' ? c : c.name;
    const o = document.createElement('option');
    o.value = name; o.textContent = name;
    if (name === page.category) o.selected = true;
    sel.appendChild(o);
  }
  // If category not in list, add it as first option
  if (![...sel.options].some(o => o.value === page.category)) {
    const o = document.createElement('option');
    o.value = page.category; o.textContent = page.category;
    sel.insertBefore(o, sel.firstChild);
    sel.value = page.category;
  }

  sel.onchange = () => { wikiModalLoadTagsForCategory(sel.value); _resetWikiSuggester(); };
  await wikiModalLoadTagsForCategory(page.category);
  wikiModalRenderTagPills();

  document.getElementById('wikiEditModal').classList.remove('hidden');
}

function closeWikiEdit() {
  document.getElementById('wikiEditModal').classList.add('hidden');
  _wikiEditPageId = null;
}

async function saveWikiEdit() {
  const pageId = _wikiEditPageId;
  if (!pageId) return;
  const title = document.getElementById('wikiModalTitle').value.trim();
  const content = document.getElementById('wikiModalContent').value;
  const category = document.getElementById('wikiModalCategory').value;
  // Flush any partially typed tag
  const tagInput = document.getElementById('wikiModalTagInput');
  if (tagInput && tagInput.value.trim()) wikiModalAddTag(tagInput.value);
  // Register new tags in taxonomy
  const newTags = wikiCurrentTags.filter(t => !_wikiTagSuggestions.includes(t));
  for (const tag of newTags) {
    try {
      await api(`/api/config/tags/${encodeURIComponent(category)}`, {
        method: 'POST', body: JSON.stringify({ tag }),
      });
    } catch (e) { /* non-fatal */ }
  }
  const updated = await api(`/api/digest/pages/${encodeURIComponent(pageId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title, content, tags: wikiCurrentTags, category }),
  });
  closeWikiEdit();
  _currentWikiPageId = updated.page_id;
  renderDigestPage(updated);
  await loadDigestPages();
}

async function deleteDigestPage(pageId) {
  if (!confirm('Delete this digest page? This cannot be undone.')) return;
  await api(`/api/digest/pages/${encodeURIComponent(pageId)}`, { method: 'DELETE' });
  _currentWikiPageId = null;
  document.getElementById('digestPageDetail').innerHTML =
    '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);font-size:13px;">Select a page</div>';
  await loadDigestPages();
}

async function addToDigest(itemId, btn) {
  const orig = btn ? btn.innerHTML : '';
  let tags = [];
  try { tags = JSON.parse(btn?.dataset?.itemTags || '[]'); } catch (_) {}
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Generating…'; }
  try {
    const page = await api('/api/digest/generate', {
      method: 'POST',
      body: JSON.stringify({ item_id: itemId, tags }),
    });
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '📝 View in Wiki';
      btn.onclick = () => { switchView('digest'); loadDigestPage(page.page_id); };
      btn.classList.add('primary');
    }
    updateDigestBadge();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.innerHTML = orig; }
    alert(`Failed to generate digest page: ${e.message}`);
  }
}

async function addToDigestMarkdown(itemId, btn) {
  const orig = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Saving…'; }
  try {
    const page = await api('/api/digest/save-markdown', {
      method: 'POST',
      body: JSON.stringify({ item_id: itemId }),
    });
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '📝 View in Digest';
      btn.onclick = () => { switchView('digest'); loadDigestPage(page.page_id); };
      btn.classList.add('primary');
    }
    await loadDigestPages();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.innerHTML = orig; }
    alert(`Failed to save digest page: ${e.message}`);
  }
}

function updateDigestBadge() {}

async function digestUploadFiles(files) {
  if (!files || !files.length) return;
  const input = document.getElementById('digestUploadInput');
  let done = 0, failed = 0;
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      await fetch(`${API}/api/digest/upload`, {
        method: 'POST',
        headers: KEY ? { 'X-API-Key': KEY } : {},
        body: fd,
      }).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
      done++;
    } catch { failed++; }
  }
  input.value = '';
  await loadDigestPages();
  if (failed) alert(`Uploaded ${done}, failed ${failed}.`);
}

/* =====================================================================
   Wiki Import from Git
   ===================================================================== */
let _digestImportPages = [];  // flat page list from fetch-repo
let _digestImportUrl = '';    // URL used for the current fetch

function openDigestImport() {
  digestImportReset();
  document.getElementById('digestImportModal').classList.remove('hidden');
}

function closeDigestImport() {
  document.getElementById('digestImportModal').classList.add('hidden');
}

function digestImportReset() {
  document.getElementById('digestImportStep1').style.display = '';
  document.getElementById('digestImportStep2').style.display = 'none';
  document.getElementById('digestImportFetchStatus').textContent = '';
  document.getElementById('digestImportUrl').value = '';
  document.getElementById('digestImportFetchBtn').disabled = false;
}

async function digestImportFetch() {
  const url = document.getElementById('digestImportUrl').value.trim();
  if (!url) return;
  const statusEl = document.getElementById('digestImportFetchStatus');
  const btn = document.getElementById('digestImportFetchBtn');
  statusEl.textContent = 'Cloning repo…';
  statusEl.style.color = 'var(--dim)';
  btn.disabled = true;
  try {
    _digestImportUrl = url;
    const data = await api('/api/digest/fetch-repo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    _digestImportPages = data.pages || [];
    document.getElementById('digestImportRepoTitle').textContent = data.title || url;
    _digestImportRenderFiles(data.toc || [], _digestImportPages);
    document.getElementById('digestImportStep1').style.display = 'none';
    document.getElementById('digestImportStep2').style.display = 'flex';
    _digestImportUpdateSelCount();
  } catch (e) {
    statusEl.textContent = 'Error: ' + esc(e.message || String(e));
    statusEl.style.color = 'var(--hi)';
    btn.disabled = false;
  }
}

function _digestImportRenderFiles(toc, pages) {
  const list = document.getElementById('digestImportFileList');
  list.innerHTML = '';
  if (toc && toc.length) {
    _digestImportRenderTocNodes(toc, list, 0);
  } else {
    for (const p of pages) _digestImportRenderRow(p, list, 0);
  }
}

function _digestImportRenderTocNodes(nodes, container, depth) {
  for (const node of nodes) {
    if (!node.rel_path && (!node.children || !node.children.length)) continue;
    if (!node.rel_path) {
      const sec = document.createElement('div');
      sec.style.cssText = `padding:5px 10px 3px ${10 + depth * 14}px;font-size:11px;font-weight:600;color:var(--dim);text-transform:uppercase;letter-spacing:.04em;`;
      sec.textContent = node.title;
      container.appendChild(sec);
      if (node.children && node.children.length) {
        _digestImportRenderTocNodes(node.children, container, depth + 1);
      }
      continue;
    }
    _digestImportRenderRow(node, container, depth);
    if (node.children && node.children.length) {
      _digestImportRenderTocNodes(node.children, container, depth + 1);
    }
  }
}

function _digestImportRenderRow(page, container, depth) {
  const row = document.createElement('label');
  row.style.cssText = `display:flex;align-items:center;gap:8px;padding:4px 10px 4px ${10 + depth * 14}px;cursor:pointer;font-size:12px;border-bottom:1px solid var(--border);`;
  row.innerHTML = `<input type="checkbox" class="digest-import-cb" data-path="${esc(page.rel_path)}" data-title="${esc(page.title)}" checked style="flex-shrink:0;"> <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(page.rel_path)}">${esc(page.title || page.rel_path)}</span>`;
  row.querySelector('input').addEventListener('change', _digestImportUpdateSelCount);
  container.appendChild(row);
}

function _digestImportUpdateSelCount() {
  const checked = document.querySelectorAll('.digest-import-cb:checked').length;
  document.getElementById('digestImportSelCount').textContent = `${checked} selected`;
}

function digestImportSelectAll(state) {
  document.querySelectorAll('.digest-import-cb').forEach(cb => cb.checked = state);
  _digestImportUpdateSelCount();
}

async function digestImportRun() {
  const checked = Array.from(document.querySelectorAll('.digest-import-cb:checked'));
  if (!checked.length) { alert('No pages selected.'); return; }

  const pages = checked.map(cb => ({ rel_path: cb.dataset.path, title: cb.dataset.title }));

  const btn = document.getElementById('digestImportRunBtn');
  const status = document.getElementById('digestImportRunStatus');
  btn.disabled = true;
  status.textContent = `Importing ${pages.length} pages with AI analysis…`;
  status.style.color = 'var(--dim)';

  try {
    const result = await api('/api/digest/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: _digestImportUrl, pages }),
    });
    status.textContent = `Done: ${result.imported} imported, ${result.skipped} skipped, ${result.failed} failed.`;
    status.style.color = result.failed > 0 ? 'var(--hi)' : 'var(--ok, #4caf50)';
    await loadDigestPages();
    if (result.imported > 0) setTimeout(closeDigestImport, 1500);
  } catch (e) {
    status.textContent = 'Error: ' + esc(e.message || String(e));
    status.style.color = 'var(--hi)';
    btn.disabled = false;
  }
}

async function deleteItem(id) {
  if (!confirm('Delete this item? This cannot be undone.')) return;
  await api(`/api/items/${id}`, { method: 'DELETE' });
  currentItemId = null;
  document.getElementById('detailContent').style.display = 'none';
  document.getElementById('detailEmpty').style.display = 'flex';
  await Promise.all([loadCategories(), loadTopTags(), loadItems()]);
}

async function reclassify(id, btn) {
  if (!confirm('Re-run AI classification on this item?')) return;
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Classifying…'; }
  await new Promise(r => setTimeout(r, 0)); // flush repaint before blocking fetch
  try {
    await api(`/api/items/${id}/reclassify`, { method: 'POST' });
    await Promise.all([loadCategories(), loadItems()]);
    loadDetail(id);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Reclassify'; }
  }
}

/* =====================================================================
   RSS / Feeds
   ===================================================================== */
let rssFeeds = [];
let rssShowAll = false;
let currentFeedId = null;
let currentFeedEntries = [];
let _rssPollTimer = null;
const RSS_POLL_INTERVAL = 60_000; // 1 minute

function startRssPoll() {
  stopRssPoll();
  _rssPollTimer = setInterval(async () => {
    const fresh = await api('/api/feeds').catch(() => null);
    if (!fresh) return;
    // Update unread counts without clobbering the feed list UI state
    let changed = false;
    for (const f of fresh) {
      const existing = rssFeeds.find(r => r.id === f.id);
      if (existing && existing.unread_count !== f.unread_count) {
        existing.unread_count = f.unread_count;
        changed = true;
      }
    }
    if (changed) { renderFeedList(); updateRssNavBadge(); }
  }, RSS_POLL_INTERVAL);
}

function stopRssPoll() {
  if (_rssPollTimer) { clearInterval(_rssPollTimer); _rssPollTimer = null; }
}

function updateRssNavBadge() {
  const total = rssFeeds.reduce((sum, f) => sum + (f.unread_count || 0), 0);
  const badge = document.getElementById('rssNavBadge');
  if (!badge) return;
  if (total > 0) {
    badge.textContent = total > 999 ? '999+' : total;
    badge.style.display = '';
  } else {
    badge.style.display = 'none';
  }
}

async function loadFeeds() {
  rssFeeds = await api('/api/feeds').catch(() => []);
  renderFeedList();
  updateRssNavBadge();
}

function toggleFeedFilter() {
  rssShowAll = !rssShowAll;
  const btn = document.getElementById('rssFilterBtn');
  btn.textContent = rssShowAll ? 'Unread only' : 'Show all';
  btn.style.color = rssShowAll ? 'var(--text)' : 'var(--dim)';
  renderFeedList();
}

function renderFeedList() {
  const list = document.getElementById('rssFeedList');
  const empty = document.getElementById('rssFeedEmpty');
  list.querySelectorAll('.rss-feed-row').forEach(el => el.remove());

  const query = (document.getElementById('rssFeedSearch')?.value || '').toLowerCase();
  let visible = rssShowAll ? rssFeeds : rssFeeds.filter(f => f.unread_count > 0);
  if (query) visible = visible.filter(f => f.title.toLowerCase().includes(query) || f.url.toLowerCase().includes(query));
  visible = [...visible].sort((a, b) => a.title.localeCompare(b.title));

  empty.style.display = visible.length ? 'none' : 'flex';
  empty.style.flexDirection = 'column';
  empty.textContent = rssFeeds.length ? (query ? 'No matching feeds' : 'No unread feeds') : 'No feeds added yet';

  for (const feed of visible) {
    const row = document.createElement('div');
    row.className = 'rss-feed-row' + (feed.id === currentFeedId ? ' active' : '');
    row.dataset.feedId = feed.id;
    const badge = (feed.unread_count > 0)
      ? `<span class="rss-unread-badge">${feed.unread_count}</span>`
      : '';
    row.innerHTML = `
      <span class="rss-feed-title" title="${esc(feed.url)}">${esc(feed.title)}</span>
      <div class="rss-feed-actions">
        ${badge}
        <button class="rss-icon-btn" title="Mark all read" onclick="event.stopPropagation();markAllReadFeed('${esc(feed.id)}',this)">✓</button>
        <button class="rss-icon-btn" title="Refresh" onclick="event.stopPropagation();previewFeed('${esc(feed.id)}')">↻</button>
        <button class="rss-icon-btn" title="Delete"  onclick="event.stopPropagation();deleteFeed('${esc(feed.id)}')">✕</button>
      </div>`;
    row.onclick = () => previewFeed(feed.id);
    list.appendChild(row);
  }
  updateRssNavBadge();
}

async function previewFeed(feedId) {
  currentFeedId = feedId;
  document.querySelectorAll('.rss-feed-row').forEach(el =>
    el.classList.toggle('active', el.dataset.feedId === feedId));

  // Hide settings, show entries area
  document.getElementById('rssSettingsPanel').style.display = 'none';
  document.getElementById('rssSelectPrompt').style.display = 'none';
  document.getElementById('rssEntriesContent').style.display = 'flex';

  const entriesTitle = document.getElementById('rssEntriesFeedTitle');
  const entriesCount = document.getElementById('rssEntriesCount');
  const entryList    = document.getElementById('rssEntryList');
  const feed = rssFeeds.find(f => f.id === feedId);
  entriesTitle.textContent = feed ? feed.title : feedId;
  document.getElementById('rssRenameFeedBtn').style.display = '';
  entriesCount.textContent = 'Loading…';
  entryList.innerHTML = '<div class="rss-empty">Fetching entries…</div>';

  try {
    const data = await api(`/api/feeds/${encodeURIComponent(feedId)}/preview`);
    currentFeedEntries = data.entries;
    const unread = data.unread_count ?? data.entries.filter(e => !e.seen).length;
    entriesCount.textContent = `${unread} unread / ${data.entries.length} total`;
    // Update unread badge on the feed row
    const feed = rssFeeds.find(f => f.id === feedId);
    if (feed) { feed.unread_count = unread; renderFeedList(); }
    entryList.innerHTML = '';
    if (!data.entries.length) {
      entryList.innerHTML = '<div class="rss-empty">No entries found in this feed</div>';
      return;
    }
    for (const entry of data.entries) {
      const card = document.createElement('div');
      card.className = 'rss-entry-card' + (entry.seen ? ' seen' : '');
      card.dataset.url = entry.url;

      const hasContent = entry.content && entry.content.trim().length > 100;

      const titleEl = document.createElement('div');
      titleEl.className = 'rss-entry-title' + (hasContent ? ' expandable' : '');
      titleEl.textContent = (hasContent ? '▶ ' : '') + decodeHtml(entry.title);

      const metaEl = document.createElement('div');
      metaEl.className = 'rss-entry-meta';
      metaEl.textContent = entry.published;

      const summaryEl = document.createElement('div');
      summaryEl.className = 'rss-entry-summary';
      if (entry.summary) {
        const decoded = decodeHtml(entry.summary);
        summaryEl.textContent = decoded.slice(0, 200) + (decoded.length > 200 ? '…' : '');
      }

      let contentEl = null;
      if (hasContent) {
        contentEl = document.createElement('div');
        contentEl.className = 'rss-entry-body';
        contentEl.innerHTML = DOMPurify.sanitize(entry.content, { ADD_ATTR: ['target'] });
        contentEl.querySelectorAll('a').forEach(a => { a.target = '_blank'; a.rel = 'noopener'; });

        titleEl.style.cursor = 'pointer';
        titleEl.addEventListener('click', () => {
          const expanded = contentEl.style.display === 'block';
          contentEl.style.display = expanded ? 'none' : 'block';
          titleEl.textContent = (expanded ? '▶ ' : '▼ ') + decodeHtml(entry.title);
        });
      }

      const actionsEl = document.createElement('div');
      actionsEl.className = 'rss-entry-actions';
      actionsEl.innerHTML = `
        ${entry.url ? `<a class="btn" href="${esc(entry.url)}" target="_blank" rel="noopener" style="font-size:11px;padding:4px 8px;text-decoration:none;">Open ↗</a>` : ''}
        ${entry.comments_url ? `<a class="btn" href="${esc(entry.comments_url)}" target="_blank" rel="noopener" style="font-size:11px;padding:4px 8px;text-decoration:none;">Comments ↗</a>` : ''}
        ${entry.url ? `<button class="btn" onclick="ingestEntry('${esc(feedId)}','${esc(entry.url)}',this)" style="font-size:11px;padding:4px 8px;">Add to Library</button>` : ''}
        ${entry.url ? `<button class="btn" onclick="ingestEntryFollowup('${esc(feedId)}','${esc(entry.url)}',this)" style="font-size:11px;padding:4px 8px;">Add to Library + Followup</button>` : ''}
        ${entry.url && !entry.seen ? `<button class="btn" onclick="markEntryRead('${esc(feedId)}','${esc(entry.url)}',this)" style="font-size:11px;padding:4px 8px;">Mark read</button>` : ''}
      `;
      card.appendChild(titleEl);
      card.appendChild(metaEl);
      if (entry.summary) card.appendChild(summaryEl);
      if (contentEl) card.appendChild(contentEl);
      card.appendChild(actionsEl);
      entryList.appendChild(card);
    }
  } catch (e) {
    entriesCount.textContent = '';
    entryList.innerHTML = `<div class="rss-empty" style="color:var(--hi)">Error: ${esc(e.message)}</div>`;
  }
}

function startRenameFeed() {
  if (!currentFeedId) return;
  const feed = rssFeeds.find(f => f.id === currentFeedId);
  if (!feed) return;

  const titleEl = document.getElementById('rssEntriesFeedTitle');
  const renameBtn = document.getElementById('rssRenameFeedBtn');
  const currentTitle = feed.title;

  // Replace title span with inline input
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentTitle;
  input.style.cssText = 'flex:1;min-width:0;background:var(--bg3);border:1px solid var(--hi);color:var(--text);border-radius:4px;font-size:13px;font-weight:600;padding:2px 6px;outline:none;';
  titleEl.replaceWith(input);
  renameBtn.style.display = 'none';
  input.focus();
  input.select();

  async function commit() {
    const newTitle = input.value.trim();
    // Restore title element regardless
    const span = document.createElement('span');
    span.className = 'rss-entries-title';
    span.id = 'rssEntriesFeedTitle';
    span.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    if (!newTitle || newTitle === currentTitle) {
      span.textContent = currentTitle;
      input.replaceWith(span);
      renameBtn.style.display = '';
      return;
    }
    try {
      await api(`/api/feeds/${encodeURIComponent(currentFeedId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: newTitle }),
      });
      feed.title = newTitle;
      span.textContent = newTitle;
      renderFeedList();
    } catch (_) {
      span.textContent = currentTitle;
    }
    input.replaceWith(span);
    renameBtn.style.display = '';
  }

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = currentTitle; input.blur(); }
  });
}

async function ingestEntry(feedId, url, btn) {
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  try {
    const r = await api(`/api/feeds/${encodeURIComponent(feedId)}/ingest`, {
      method: 'POST', body: JSON.stringify({ entry_urls: [url] }),
    });
    if (btn) { btn.textContent = r.skipped ? 'Already in library' : '✓ Added'; }
  } catch (e) {
    if (btn) { btn.textContent = 'Error'; btn.disabled = false; btn.style.color = 'var(--hi)'; }
    showErrorPopup(e.message);
  }
}

async function ingestEntryFollowup(feedId, url, btn) {
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  try {
    const r = await api(`/api/feeds/${encodeURIComponent(feedId)}/ingest`, {
      method: 'POST', body: JSON.stringify({ entry_urls: [url] }),
    });
    if (r.item_ids && r.item_ids.length) {
      await api(`/api/items/${r.item_ids[0]}/followup`, { method: 'POST' });
      updateFollowupBadge();
    }
    if (btn) { btn.textContent = r.skipped ? 'Already in library' : '✓ Added + Followup'; }
  } catch (e) {
    if (btn) { btn.textContent = 'Error'; btn.disabled = false; btn.style.color = 'var(--hi)'; }
    showErrorPopup(e.message);
  }
}

async function ingestAllEntries() {
  const btn = document.getElementById('rssIngestAllBtn');
  btn.disabled = true; btn.textContent = 'Adding…';
  try {
    const r = await api(`/api/feeds/${encodeURIComponent(currentFeedId)}/ingest`, { method: 'POST', body: JSON.stringify({}) });
    btn.textContent = `✓ ${r.imported} imported`;
  } catch (e) {
    btn.textContent = 'Error';
  } finally {
    setTimeout(() => { btn.textContent = 'Add All to Library'; btn.disabled = false; }, 3000);
  }
}

function _updateUnreadCount(feedId) {
  const cards = document.querySelectorAll('#rssEntryList .rss-entry-card');
  const unread = [...cards].filter(c => !c.classList.contains('seen')).length;
  document.getElementById('rssEntriesCount').textContent =
    `${unread} unread / ${cards.length} total`;
  const feed = rssFeeds.find(f => f.id === feedId);
  if (feed) { feed.unread_count = unread; renderFeedList(); }
}

async function markEntryRead(feedId, url, btn) {
  btn.disabled = true;
  try {
    await api(`/api/feeds/${encodeURIComponent(feedId)}/mark-read`, {
      method: 'POST', body: JSON.stringify({ urls: [url] }),
    });
    const card = btn.closest('.rss-entry-card');
    card.classList.add('seen');
    btn.remove();
    _updateUnreadCount(feedId);
  } catch (e) {
    btn.disabled = false;
  }
}

async function markAllRead() {
  if (!currentFeedId) return;
  const btn = document.getElementById('rssMarkAllReadBtn');
  btn.disabled = true; btn.textContent = '…';
  try {
    await api(`/api/feeds/${encodeURIComponent(currentFeedId)}/mark-read`, { method: 'POST', body: JSON.stringify({}) });
    document.querySelectorAll('#rssEntryList .rss-entry-card').forEach(c => {
      c.classList.add('seen');
      c.querySelector('button[onclick^="markEntryRead"]')?.remove();
    });
    _updateUnreadCount(currentFeedId);
  } finally {
    btn.disabled = false; btn.textContent = 'Mark all read';
  }
}

async function markAllFeedsRead(btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Marking…';
  try {
    await Promise.all(rssFeeds.map(f =>
      api(`/api/feeds/${encodeURIComponent(f.id)}/mark-read`, { method: 'POST', body: JSON.stringify({}) })
    ));
    rssFeeds.forEach(f => { f.unread_count = 0; });
    if (currentFeedId) {
      document.querySelectorAll('#rssEntryList .rss-entry-card').forEach(c => {
        c.classList.add('seen');
        c.querySelector('button[onclick^="markEntryRead"]')?.remove();
      });
      _updateUnreadCount(currentFeedId);
    } else {
      renderFeedList();
    }
  } finally {
    btn.textContent = orig; btn.disabled = false;  // textContent clears the spinner innerHTML
  }
}

async function markAllReadFeed(feedId, btn) {
  btn.disabled = true;
  try {
    await api(`/api/feeds/${encodeURIComponent(feedId)}/mark-read`, { method: 'POST', body: JSON.stringify({}) });
    const feed = rssFeeds.find(f => f.id === feedId);
    if (feed) { feed.unread_count = 0; renderFeedList(); }
    if (feedId === currentFeedId) {
      document.querySelectorAll('#rssEntryList .rss-entry-card').forEach(c => {
        c.classList.add('seen');
        c.querySelector('button[onclick^="markEntryRead"]')?.remove();
      });
      _updateUnreadCount(feedId);
    }
  } finally {
    btn.disabled = false;
  }
}

async function deleteFeed(feedId) {
  if (!confirm('Remove this feed?')) return;
  await api(`/api/feeds/${encodeURIComponent(feedId)}`, { method: 'DELETE' });
  if (currentFeedId === feedId) {
    currentFeedId = null;
    document.getElementById('rssEntriesContent').style.display = 'none';
    document.getElementById('rssSettingsPanel').style.display = 'none';
    document.getElementById('rssSelectPrompt').style.display = 'flex';
  }
  await loadFeeds();
  renderSettingsTable();
}

async function refreshAllFeeds(btn) {
  const orig = btn.textContent;
  btn.textContent = '↻ Refreshing…';
  btn.style.pointerEvents = 'none';
  try {
    const r = await api('/api/feeds/refresh', { method: 'POST' });
    btn.textContent = `✓ ${r.refreshed} updated`;
    await loadFeeds();
  } catch (e) {
    btn.textContent = '✗ Failed';
  } finally {
    setTimeout(() => { btn.textContent = orig; btn.style.pointerEvents = ''; }, 3000);
  }
}

function showRssSettings() {
  currentFeedId = null;
  document.querySelectorAll('.rss-feed-row').forEach(el => el.classList.remove('active'));
  document.getElementById('rssSelectPrompt').style.display = 'none';
  document.getElementById('rssEntriesContent').style.display = 'none';
  document.getElementById('rssSettingsPanel').style.display = 'flex';
  renderSettingsTable();
  loadRefreshInterval();
}

async function loadRefreshInterval() {
  try {
    const data = await api('/api/feeds/config');
    document.getElementById('rssIntervalInput').value = data.refresh_interval_minutes;
  } catch (e) { /* non-fatal */ }
}

async function saveRefreshInterval() {
  const val = parseInt(document.getElementById('rssIntervalInput').value, 10);
  const status = document.getElementById('rssIntervalStatus');
  if (!val || val < 1) { status.textContent = 'Invalid'; return; }
  try {
    await api('/api/feeds/config', { method: 'PATCH', body: JSON.stringify({ refresh_interval_minutes: val }) });
    status.textContent = 'Saved';
    setTimeout(() => { status.textContent = ''; }, 2000);
  } catch (e) {
    status.textContent = 'Error';
    status.style.color = 'var(--hi)';
  }
}

function renderSettingsTable() {
  const tbody = document.getElementById('rssSettingsTable');
  tbody.innerHTML = '';
  for (const feed of rssFeeds) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${esc(feed.title)}</td>
      <td class="url-cell" title="${esc(feed.url)}">${esc(feed.url)}</td>
      <td><input type="checkbox" ${feed.enabled ? 'checked' : ''} onchange="toggleFeedEnabled('${esc(feed.id)}',this.checked)"></td>
      <td><button class="rss-icon-btn" onclick="deleteFeed('${esc(feed.id)}')">✕</button></td>`;
    tbody.appendChild(tr);
  }
}

async function toggleFeedEnabled(feedId, enabled) {
  await api(`/api/feeds/${encodeURIComponent(feedId)}`, {
    method: 'PATCH', body: JSON.stringify({ enabled }),
  }).catch(() => {});
  const feed = rssFeeds.find(f => f.id === feedId);
  if (feed) feed.enabled = enabled;
}

function toggleAddFeedForm() {
  const form = document.getElementById('rssAddFormInline');
  const visible = form.style.display !== 'none';
  form.style.display = visible ? 'none' : 'block';
  if (!visible) {
    document.getElementById('rssAddUrl').value = '';
    document.getElementById('rssAddStatus').textContent = '';
    document.getElementById('rssAddUrl').focus();
  }
}

async function submitAddFeed() {
  const url    = document.getElementById('rssAddUrl').value.trim();
  const status = document.getElementById('rssAddStatus');

  if (!url) { status.textContent = 'URL is required'; return; }
  status.textContent = 'Fetching feed…';

  try {
    await api('/api/feeds', { method: 'POST', body: JSON.stringify({ url }) });
    status.textContent = 'Feed added!';
    document.getElementById('rssAddUrl').value = '';
    await loadFeeds();
    if (document.getElementById('rssSettingsPanel').style.display !== 'none') renderSettingsTable();
    setTimeout(() => {
      document.getElementById('rssAddFormInline').style.display = 'none';
      status.textContent = '';
    }, 1000);
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  }
}

function importOPML() {
  document.getElementById('opmlFileInput').click();
}

async function handleOPMLFile(input) {
  const file = input.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const r = await fetch(API + '/api/feeds/opml', {
      method: 'POST', headers: { 'X-API-Key': KEY }, body: form,
    }).then(res => res.json());
    alert(`Imported ${r.added} feeds (${r.skipped} skipped)`);
    await loadFeeds();
    if (document.getElementById('rssSettingsPanel').style.display !== 'none') renderSettingsTable();
  } catch (e) {
    alert('OPML import failed: ' + e.message);
  } finally {
    input.value = '';
  }
}

async function exportOPML() {
  const a = document.createElement('a');
  a.href = API + '/api/feeds/opml';
  a.download = 'brainz-feeds.opml';
  // Include key via header isn't possible for direct href downloads; use fetch+blob
  try {
    const resp = await fetch(API + '/api/feeds/opml', { headers: { 'X-API-Key': KEY } });
    const blob = await resp.blob();
    a.href = URL.createObjectURL(blob);
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) {
    alert('Export failed: ' + e.message);
  }
}

/* =====================================================================
   Util
   ===================================================================== */
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function decodeHtml(s) {
  const txt = document.createElement('textarea');
  txt.innerHTML = String(s || '');
  return txt.value;
}

/* =====================================================================
   Tools (GitHub Stars)
   ===================================================================== */
let toolRepos = [];          // flat list of all repos across all accounts
let currentToolRepo = null;  // currently selected repo object
let currentToolId = null;    // tool account id for the selected repo
let toolPage = 0;
const TOOL_PAGE_SIZE = 50;
let _toolsStatusPollTimer = null;
let _toolsWasRefreshing = false;

function startToolsStatusPoll() {
  if (_toolsStatusPollTimer) return;
  _toolsStatusPollTimer = setInterval(_pollToolsStatus, 3000);
}

function stopToolsStatusPoll() {
  clearInterval(_toolsStatusPollTimer);
  _toolsStatusPollTimer = null;
  _toolsWasRefreshing = false;
}

async function _pollToolsStatus() {
  try {
    const data = await api('/api/tools/status');
    const entries = Object.values(data.refreshing || {});
    if (entries.length > 0) {
      _toolsWasRefreshing = true;
      _setToolStatus(`<span class="spinner"></span> Refreshing: ${entries.map(esc).join(', ')}…`);
    } else if (_toolsWasRefreshing) {
      // Just finished — reload list and show updated count
      _toolsWasRefreshing = false;
      await loadTools(); loadToolTopics();
    }
  } catch (_) {}
}

async function loadTools() {
  _setToolStatus('<span class="spinner"></span> Loading…');
  const accounts = await api('/api/tools').catch(() => []);
  toolRepos = [];
  toolPage = 0;
  const enabled = accounts.filter(a => a.enabled);
  const results = await Promise.all(enabled.map(acct =>
    api(`/api/tools/${encodeURIComponent(acct.id)}/preview`)
      .then(data => { for (const r of data.repos) r._tool_id = acct.id; return data.repos; })
      .catch(() => [])
  ));
  toolRepos = results.flat();
  renderToolRepoList();
  if (toolRepos.length) {
    const unseenCount = toolRepos.filter(r => !r.seen).length;
    if (unseenCount > 0) {
      _setToolStatus(`${toolRepos.length} repos — <strong>${unseenCount} not yet ingested</strong>. Use <em>Ingest All Starred</em> in Settings to make them available for Query.`);
    } else {
      _setToolStatus(`${toolRepos.length} repos — all ingested`);
    }
  } else {
    _setToolStatus(null);
  }
}

function renderToolRepoList() {
  const q = (document.getElementById('toolSearch')?.value || '').toLowerCase();
  const list = document.getElementById('toolRepoListPanel');
  list.innerHTML = '';
  const filtered = toolRepos.filter(r => {
    if (currentTag && !r.topics.some(t => t.toLowerCase() === currentTag.toLowerCase())) return false;
    if (q && !(
      r.full_name.toLowerCase().includes(q) ||
      (r.description || '').toLowerCase().includes(q) ||
      (r.language || '').toLowerCase().includes(q) ||
      r.topics.some(t => t.toLowerCase().includes(q))
    )) return false;
    return true;
  });
  if (!filtered.length) {
    list.innerHTML = `<div style="padding:16px 12px;font-size:12px;color:var(--dim);">${toolRepos.length ? 'No results.' : 'No starred repos. Add a username in Settings.'}</div>`;
    document.getElementById('toolPagination').style.display = 'none';
    return;
  }
  const totalPages = Math.ceil(filtered.length / TOOL_PAGE_SIZE);
  if (toolPage >= totalPages) toolPage = totalPages - 1;
  const page = filtered.slice(toolPage * TOOL_PAGE_SIZE, (toolPage + 1) * TOOL_PAGE_SIZE);
  for (const repo of page) {
    const row = document.createElement('div');
    const isActive = currentToolRepo && currentToolRepo.node_id === repo.node_id;
    row.className = 'rss-feed-row' + (isActive ? ' active' : '');
    const lang = repo.language ? `<span style="font-size:10px;color:var(--dim);margin-left:4px;">${esc(repo.language)}</span>` : '';
    row.innerHTML = `
      <span class="rss-feed-title" style="font-size:12px;">${esc(repo.full_name)}${lang}</span>
      <span style="font-size:10px;color:var(--dim);flex-shrink:0;">★${repo.stars.toLocaleString()}</span>`;
    row.onclick = () => showRepoDetail(repo);
    list.appendChild(row);
  }
  // Pagination controls
  const pag = document.getElementById('toolPagination');
  if (totalPages > 1) {
    pag.style.display = 'flex';
    document.getElementById('toolPageInfo').textContent =
      `${toolPage * TOOL_PAGE_SIZE + 1}–${Math.min((toolPage + 1) * TOOL_PAGE_SIZE, filtered.length)} of ${filtered.length}`;
    document.getElementById('toolPagePrev').disabled = toolPage === 0;
    document.getElementById('toolPageNext').disabled = toolPage >= totalPages - 1;
  } else {
    pag.style.display = 'none';
  }
}

function toolChangePage(dir) {
  toolPage += dir;
  renderToolRepoList();
  document.getElementById('toolRepoListPanel').scrollTop = 0;
}

async function showRepoDetail(repo) {
  currentToolRepo = repo;
  currentToolId = repo._tool_id;
  renderToolRepoList();

  document.getElementById('toolSelectPrompt').style.display = 'none';
  document.getElementById('toolSettingsPane').style.display = 'none';
  const pane = document.getElementById('toolDetailPane');
  pane.style.display = 'flex';
  pane.style.flexDirection = 'column';

  document.getElementById('toolDetailTitle').textContent = repo.full_name;
  const btn = document.getElementById('toolDetailIngestBtn');
  btn.textContent = repo.seen ? '✓ Ingested' : 'Ingest';
  btn.disabled = repo.seen;
  const fbtn = document.getElementById('toolFollowupBtn');
  fbtn.textContent = repo._followup ? '🔖 Followup' : '🔖';
  fbtn.classList.toggle('primary', !!repo._followup);

  const content = document.getElementById('toolDetailContent');
  const lang = repo.language ? `<span style="padding:2px 8px;background:var(--bg3);border-radius:4px;font-size:11px;color:var(--dim);">${esc(repo.language)}</span>` : '';
  const stars = `<span style="font-size:12px;color:var(--dim);">★ ${repo.stars.toLocaleString()}</span>`;
  const topics = repo.topics.length
    ? `<div style="display:flex;flex-wrap:wrap;gap:4px;">${repo.topics.map(t => `<span style="font-size:11px;padding:2px 8px;background:var(--tag-bg);border-radius:4px;color:var(--dim);">${esc(t)}</span>`).join('')}</div>`
    : '';
  const desc = repo.description ? `<p style="font-size:13px;color:var(--text);line-height:1.6;margin:0;">${esc(repo.description)}</p>` : '';
  const link = `<a href="${esc(repo.html_url)}" target="_blank" style="font-size:12px;color:var(--hi);">View on GitHub ↗</a>`;

  content.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">${lang}${stars}</div>
    ${desc}${topics}${link}
    <div id="toolReadmeContent" style="margin-top:8px;color:var(--dim);font-size:12px;">Loading README…</div>`;

  // Fetch and render README
  if (repo.readme_path && currentToolId) {
    try {
      const md = await api(`/api/tools/${encodeURIComponent(currentToolId)}/readme?full_name=${encodeURIComponent(repo.full_name)}`);
      const readmeEl = document.getElementById('toolReadmeContent');
      if (readmeEl) {
        readmeEl.className = 'detail-body';
        readmeEl.style.cssText = 'margin-top:12px;height:auto;min-height:unset;max-height:none;overflow-y:visible;';
        readmeEl.innerHTML = DOMPurify.sanitize(marked.parse(md, { breaks: false, gfm: true }));
      }
    } catch (_) {
      const readmeEl = document.getElementById('toolReadmeContent');
      if (readmeEl) readmeEl.textContent = 'README not available.';
    }
  } else {
    const readmeEl = document.getElementById('toolReadmeContent');
    if (readmeEl) readmeEl.textContent = 'No README downloaded yet — refresh to fetch.';
  }
}

async function ingestCurrentRepo(btn) {
  if (!currentToolRepo || !currentToolId) return;
  btn.disabled = true; btn.textContent = '…';
  try {
    const r = await api(`/api/tools/${encodeURIComponent(currentToolId)}/ingest`, {
      method: 'POST', body: JSON.stringify({ node_ids: [currentToolRepo.node_id] })
    });
    btn.textContent = r.skipped ? '✓ Already in library' : '✓ Ingested';
    currentToolRepo.seen = true;
  } catch (e) {
    btn.textContent = 'Error'; btn.disabled = false;
    setTimeout(() => { btn.textContent = 'Ingest'; }, 2000);
  }
}

async function ingestAllToolRepos(btn) {
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = 'Ingesting…';
  let total = { imported: 0, skipped: 0, failed: 0 };
  const accounts = await api('/api/tools').catch(() => []);
  for (const acct of accounts) {
    if (!acct.enabled) continue;
    try {
      const r = await api(`/api/tools/${encodeURIComponent(acct.id)}/ingest`, { method: 'POST', body: JSON.stringify({}) });
      total.imported += r.imported; total.skipped += r.skipped; total.failed += r.failed;
    } catch (_) {}
  }
  btn.textContent = `✓ ${total.imported} ingested`;
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 4000);
}

function _setToolStatus(msg, isError) {
  const bar = document.getElementById('toolStatusBar');
  if (!bar) return;
  if (!msg) { bar.style.display = 'none'; return; }
  bar.style.display = '';
  bar.style.color = isError ? 'var(--hi)' : 'var(--dim)';
  bar.innerHTML = msg;
}

async function refreshToolsNow(btn) {
  if (btn) { btn.style.opacity = '0.5'; btn.style.pointerEvents = 'none'; btn.textContent = '↻ Refreshing…'; }
  _setToolStatus('<span class="spinner"></span> Fetching starred repos…');
  try {
    await api('/api/tools/refresh', { method: 'POST' });
    _setToolStatus('<span class="spinner"></span> Loading…');
    await loadTools();
    _setToolStatus(`${toolRepos.length} repos loaded`);
    setTimeout(() => _setToolStatus(null), 3000);
  } catch (e) {
    _setToolStatus(`Error: ${e.message}`, true);
  } finally {
    if (btn) { btn.style.opacity = ''; btn.style.pointerEvents = ''; btn.textContent = '↻ Refresh'; }
  }
}

async function showToolsSettings() {
  currentToolRepo = null;
  renderToolRepoList();
  document.getElementById('toolSelectPrompt').style.display = 'none';
  document.getElementById('toolDetailPane').style.display = 'none';
  const pane = document.getElementById('toolSettingsPane');
  pane.style.display = 'flex';
  pane.style.flexDirection = 'column';

  try {
    const cfg = await api('/api/tools/config');
    document.getElementById('toolRefreshInterval').value = cfg.refresh_interval_minutes;
    document.getElementById('toolTokenStatus').textContent = cfg.github_token_set
      ? '✓ Token active (5000 req/hr)' : '✗ No token set — limited to 60 req/hr';
    // Populate username field from existing accounts
    const accounts = await api('/api/tools').catch(() => []);
    document.getElementById('toolUsernameInput').value = accounts.map(a => a.username).join(', ');
  } catch (_) {}
}

async function saveToolsSettings() {
  const raw = document.getElementById('toolUsernameInput').value;
  const interval = parseInt(document.getElementById('toolRefreshInterval').value);

  // Save config (interval only — token is set via .env)
  const body = {};
  if (!isNaN(interval) && interval >= 1) body.refresh_interval_minutes = interval;
  if (Object.keys(body).length) {
    await api('/api/tools/config', { method: 'PATCH', body: JSON.stringify(body) });
  }

  // Sync usernames: add new, remove deleted
  if (raw.trim()) {
    const desired = raw.split(',').map(u => u.trim().toLowerCase()).filter(Boolean);
    const existing = await api('/api/tools').catch(() => []);
    const existingNames = existing.map(a => a.username.toLowerCase());
    // Add new
    for (const u of desired) {
      if (!existingNames.includes(u)) {
        await api('/api/tools', { method: 'POST', body: JSON.stringify({ username: u }) }).catch(() => {});
      }
    }
    // Remove deleted
    for (const acct of existing) {
      if (!desired.includes(acct.username.toLowerCase())) {
        await api(`/api/tools/${encodeURIComponent(acct.id)}`, { method: 'DELETE' }).catch(() => {});
      }
    }
  }

  await loadTools();
}

/* =====================================================================
   Boot
   ===================================================================== */
// Theme
function setTheme(name) {
  document.documentElement.setAttribute('data-theme', name);
  localStorage.setItem('brainz_theme', name);
  document.getElementById('themePicker').value = name;
}
(function () {
  const saved = localStorage.getItem('brainz_theme') || 'default';
  setTheme(saved);
})();

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeLightbox();
});

// Set initial view state
switchView('library');
// Load feeds in background so RSS nav badge shows immediately
loadFeeds();

if (KEY) {
  init();
} else {
  document.getElementById('apiUrlInput').value = API;
  document.getElementById('authOverlay').classList.remove('hidden');
}

/* =====================================================================
   Resizable columns
   ===================================================================== */
(function () {
  const STORAGE_KEY_NAV  = 'brainz_nav_w';
  const STORAGE_KEY_LIST = 'brainz_list_w';
  const MIN_NAV  = 140;
  const MAX_NAV  = 400;
  const MIN_LIST = 200;
  const MAX_LIST = 700;

  function applyWidths(navW, listW) {
    document.documentElement.style.setProperty('--nav-w',  navW  + 'px');
    document.documentElement.style.setProperty('--list-w', listW + 'px');
  }

  // Restore saved widths
  const savedNav  = parseInt(localStorage.getItem(STORAGE_KEY_NAV),  10);
  const savedList = parseInt(localStorage.getItem(STORAGE_KEY_LIST), 10);
  if (savedNav  >= MIN_NAV  && savedNav  <= MAX_NAV)  document.documentElement.style.setProperty('--nav-w',  savedNav  + 'px');
  if (savedList >= MIN_LIST && savedList <= MAX_LIST) document.documentElement.style.setProperty('--list-w', savedList + 'px');

  function makeResizable(handleId, getEl, getSize, setSize, min, max, storageKey) {
    const handle = document.getElementById(handleId);
    if (!handle) return;
    let startX, startSize;

    handle.addEventListener('mousedown', e => {
      e.preventDefault();
      startX    = e.clientX;
      startSize = getSize();
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      function onMove(e) {
        const delta = e.clientX - startX;
        const newSize = Math.min(max, Math.max(min, startSize + delta));
        setSize(newSize);
        localStorage.setItem(storageKey, newSize);
      }
      function onUp() {
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup',   onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  }

  makeResizable(
    'resizeNav',
    () => document.querySelector('nav'),
    () => document.querySelector('nav').getBoundingClientRect().width,
    w  => document.documentElement.style.setProperty('--nav-w', w + 'px'),
    MIN_NAV, MAX_NAV, STORAGE_KEY_NAV
  );

  makeResizable(
    'resizeList',
    () => document.getElementById('listPanel'),
    () => document.getElementById('listPanel').getBoundingClientRect().width,
    w  => document.documentElement.style.setProperty('--list-w', w + 'px'),
    MIN_LIST, MAX_LIST, STORAGE_KEY_LIST
  );
})();

/* =====================================================================
   Mobile — responsive push-navigation
   ===================================================================== */
const IS_MOBILE = window.matchMedia('(max-width:768px)').matches;

if (IS_MOBILE) {
  // Give the anonymous list-column divs stable IDs so the CSS can target them
  const fu = document.querySelector('#followupViewWrapper > div > div:first-child');
  if (fu) fu.id = 'followupListCol';
  const dg = document.querySelector('#digestViewWrapper > div > div:first-child');
  if (dg) dg.id = 'digestListCol';
}

function mobileToggleNav() {
  document.getElementById('nav').classList.contains('open') ? mobileCloseNav() : mobileOpenNav();
}

function mobileOpenNav() {
  document.getElementById('nav').classList.add('open');
  document.getElementById('mobileNavBackdrop').classList.add('open');
}

function mobileCloseNav() {
  document.getElementById('nav').classList.remove('open');
  document.getElementById('mobileNavBackdrop').classList.remove('open');
}

function mobileGoBack() {
  const b = document.body;
  if (b.classList.contains('detail-open'))          { b.classList.remove('detail-open'); return; }
  if (b.classList.contains('rss-detail-open'))      { b.classList.remove('rss-detail-open'); return; }
  if (b.classList.contains('followup-detail-open')) { b.classList.remove('followup-detail-open'); return; }
  if (b.classList.contains('digest-detail-open'))   { b.classList.remove('digest-detail-open'); return; }
}

if (IS_MOBILE) {
  // switchView: clear all push-state and close nav when switching top-level views
  const _switchView = switchView;
  window.switchView = function(view) {
    _switchView(view);
    document.body.classList.remove('detail-open', 'rss-detail-open', 'followup-detail-open', 'digest-detail-open');
    mobileCloseNav();
  };

  // renderItemList: each card tap pushes into detail
  const _renderItemList = renderItemList;
  window.renderItemList = function(list) {
    _renderItemList(list);
    document.querySelectorAll('#itemScroll .item-card').forEach(card => {
      const orig = card.onclick;
      card.onclick = e => { orig && orig(e); document.body.classList.add('detail-open'); };
    });
  };

  // loadFollowup: row taps push into followup detail
  const _loadFollowup = loadFollowup;
  window.loadFollowup = async function() {
    await _loadFollowup();
    document.querySelectorAll('#followupList .item-card').forEach(row => {
      const orig = row.onclick;
      row.onclick = e => { orig && orig(e); document.body.classList.add('followup-detail-open'); };
    });
  };

  // previewFeed: push into RSS entries panel
  const _previewFeed = previewFeed;
  window.previewFeed = async function(feedId) {
    await _previewFeed(feedId);
    document.body.classList.add('rss-detail-open');
    mobileCloseNav();
  };

  // showRepoDetail: push into tools detail panel
  const _showRepoDetail = showRepoDetail;
  window.showRepoDetail = async function(repo) {
    await _showRepoDetail(repo);
    document.body.classList.add('rss-detail-open');
    mobileCloseNav();
  };

  // loadDigestPage: push into digest page detail
  const _loadDigestPage = loadDigestPage;
  window.loadDigestPage = async function(pageId) {
    await _loadDigestPage(pageId);
    document.body.classList.add('digest-detail-open');
    mobileCloseNav();
  };

  // Swipe gestures
  (() => {
    let x0 = 0, y0 = 0, tid = null;
    document.addEventListener('touchstart', e => {
      const t = e.changedTouches[0];
      x0 = t.clientX; y0 = t.clientY; tid = t.identifier;
    }, { passive: true });
    document.addEventListener('touchend', e => {
      const t = [...e.changedTouches].find(t => t.identifier === tid);
      if (!t) return;
      const dx = t.clientX - x0, dy = t.clientY - y0;
      if (Math.abs(dy) > Math.abs(dx) * 1.5 || Math.abs(dx) < 50) return;
      const nav = document.getElementById('nav');
      if (dx > 0) {
        if (x0 < 32 && !nav.classList.contains('open')) { mobileOpenNav(); return; }
        mobileGoBack();
      } else {
        if (nav.classList.contains('open')) mobileCloseNav();
      }
    }, { passive: true });
  })();
}
