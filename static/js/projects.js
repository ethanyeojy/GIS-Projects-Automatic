/* ===== Projects page: cards in the sidecar, per-card refresh, troubleshoot, global refresh, stats ===== */
const stDot = p => ({ verified: 'ok', incomplete: 'bad', conditional: 'warn' })[p.availability] || '';
const stTxt = p => ({ verified: 'Feasible', incomplete: 'Not feasible', conditional: 'Needs conditions', unverified: 'Not checked' })[p.availability] || '';
const COV = { ok: ['ok', 'Covers your period'], partial: ['warn', 'Covers part of your period'], gap: ['bad', 'Does not cover your period'], static: ['', 'Not date-based'], snapshot: ['warn', "Today's snapshot only"], unknown: ['', 'Coverage unknown'] };
const covChip = c => c ? `<span class="chip ${COV[c.status][0]}" title="${esc(c.note)}">${COV[c.status][1]}</span>` : '';

function dsLi(d) {
  const v = d.verification, st = v ? (v.status === 'verified' ? 'ok' : 'bad') : '';
  return `<li><i class="dot2 ${st}"></i><span>${esc(d.name)}${v && v.count != null ? ` <span class="mut small">· ${fmtN(v.count)} records${v.est_bytes != null ? ' · ≈' + fmtB(v.est_bytes) : ''}</span>` : ''}
   ${d.coverage ? `<br>${covChip(d.coverage)} <span class="small mut">${esc(d.coverage.note)}</span>` : ''}</span></li>`;
}
function verdict(p) {
  if (p.availability === 'unverified') return `<div class="banner info verdict">Not checked yet. Press <b>Refresh project</b> to test the live data services for this project.</div>`;
  if (p.availability === 'verified') return `<div class="banner verdict okb"><b>Feasible.</b> All ${p.dataset_details.length} datasets are reachable and passed checks (last checked ${esc((p.verified_at || '').replace('T', ' ').slice(0, 19))} UTC).</div>`;
  return `<div class="banner bad verdict"><b>Not feasible right now.</b><br>${p.reasons.map(esc).slice(0, 6).join('<br>') || 'A source could not be verified.'}</div>`;
}
function troubleBox(p) {
  const r = S.trouble[p.id];
  if (isBusy('trouble:' + p.id)) return '<div class="banner info verdict">Troubleshooting: re-checking every dataset and looking for alternatives… up to a minute. You can press the button again at any time.</div>';
  if (!r) return '';
  const bad = r.datasets.filter(d => d.status !== 'verified');
  return `<div class="tsbox"><b>🔧 Troubleshooting report</b> <span class="small mut">${esc(r.summary)}</span>
   ${r.internet ? '' : '<div class="banner bad small">No internet connection detected — check your network, VPN or firewall first.</div>'}
   ${bad.map(d => tsItem(d, p.id)).join('')}</div>`;
}
function tsItem(d, pid, taskJob) {
  return `<div class="tsd"><b>${esc(d.name)}</b> <span class="chip bad">${esc(d.status)}</span>
    <ul class="small">${d.explain.map(e => `<li>${esc(e)}</li>`).join('')}</ul>
    <details><summary class="small">Raw errors from the service</summary><ul class="small">${d.failed.map(f => `<li>${esc(f.name)} — ${esc(f.detail)}</li>`).join('')}</ul></details>
    ${d.alternatives.length ? `<div class="small"><b>Possible replacements (each tested live just now):</b></div><ul class="small">${d.alternatives.map(a => `<li>${esc(a.title)} <span class="chip ${a.status === 'verified' ? 'ok' : 'bad'}">${esc(a.status)}</span> ${a.count != null ? fmtN(a.count) + ' records' : ''}
      ${a.status === 'verified' ? `<button data-act="use" data-ds="${esc(d.dataset_id)}" data-url="${esc(a.service_url)}" data-pid="${esc(pid || '')}" data-job="${esc(taskJob || '')}">Use this</button>` : `<span class="mut">${esc((a.problems || []).join('; '))}</span>`}</li>`).join('')}</ul>` : '<div class="small mut">No working replacement was found automatically.</div>'}</div>`;
}
function coverOf(p) {
  const im = (p.case_study && p.case_study.images || [])[0]; if (!im) return '';
  return `<div class="pc-imgwrap"><img class="pc-img" src="${esc(im.thumb || im.url.replace('/1920px-', '/960px-'))}" alt="${esc(im.alt)}" loading="lazy"><span class="pc-cred">Photo: ${esc(im.credit)} · ${esc(im.licence)}</span></div>`;
}
const keepOpen = k => S.expanded.has(k) ? 'open' : '';
function cardHtml(p) {
  const busy = isBusy('card:' + p.id), tb = isBusy('trouble:' + p.id), reg = S.filters.region, col = (p.design && p.design.accent) || THEME_COL[p.theme] || 'var(--acc)', lay = (p.design && p.design.layout) || 'photo';
  const per = S.periodInfo ? `${S.periodInfo.start} → ${S.periodInfo.end}` : '';
  return `<article class="pc pc-l-${esc(lay)}" data-pid="${esc(p.id)}" style="--tc:${col}">${coverOf(p)}
   <div class="pc-top"><span class="pc-ico">${p.icon || '🗺️'}</span><h3>${esc(p.title)}</h3></div>
   <p class="pc-desc">${esc(p.summary)}</p>
   <div class="row">${p.region ? `<span class="chip ok">📍 ${esc(p.region)}</span>` : '<span class="chip">📍 All of NZ</span>'}<span class="chip">${esc(THEME_LBL[p.theme] || p.theme)}</span><span class="chip">${esc(p.difficulty)}</span><span class="chip">≈${p.workload_h[0]}–${p.workload_h[1]} h</span>
    <span class="chip ${stDot(p) === 'ok' ? 'ok' : stDot(p) === 'bad' ? 'bad' : stDot(p) === 'warn' ? 'warn' : ''}">${stTxt(p)}</span>${p.possible === false ? '<span class="chip bad">Not possible: file too big</span>' : ''}</div>
   <div class="pc-time"><b>Time period:</b> ${esc(per)} <span class="mut small">— ${esc(p.time_note || '')}</span></div>
   ${p.oversize && p.oversize.length ? `<div class="banner bad small"><b>Not possible with your file-size limit (${esc(String(p.limit_mb))} MB per file):</b><br>${p.oversize.map(o => esc(o.name) + ' ≈ ' + fmtB(o.est_bytes)).join('<br>')}<br>Choose a smaller study area (Settings / Filters) and press Refresh project, or raise the limit in Settings.</div>` : ''}
   ${p.time_issues && p.time_issues.length ? `<div class="banner small">⚠ <b>Part of your period isn't covered:</b><br>${p.time_issues.map(esc).join('<br>')}</div>` : ''}
   <details class="pc-ds" data-exp="${esc(p.id)}:ds" ${keepOpen(p.id + ':ds')}><summary>Datasets you'll work with (${p.dataset_details.length})</summary><ul class="dsl2">${p.dataset_details.map(dsLi).join('')}</ul></details>
   <details data-exp="${esc(p.id)}:kn" ${keepOpen(p.id + ':kn')}><summary>Good to know</summary><ul class="small">${p.limitations.map(l => `<li>${esc(l)}</li>`).join('')}</ul></details>
   ${p.availability === 'unverified' ? '' : verdict(p)}${troubleBox(p)}
   <div class="actions"><button class="primary" data-act="choose" data-pid="${esc(p.id)}">Choose this project</button>
    <button data-act="refresh" data-pid="${esc(p.id)}" class="${busy ? 'busy' : ''}">${busy ? '↻ Refreshing… (click to restart)' : '↻ Refresh project'}</button>
    <button data-act="trouble" data-pid="${esc(p.id)}" class="${tb ? 'busy' : ''}" title="Re-check every dataset, explain what failed, and look for working replacements">🔧 ${tb ? 'Troubleshooting… (click to restart)' : 'Troubleshoot'}</button></div>
   <div class="small mut">Choosing opens the Project tab to review each dataset and set filters before anything is downloaded${reg ? ' (study area: ' + esc(reg) + ')' : ''}.</div>
  </article>`;
}
/* renders ONLY one card: refreshing a project never touches the others */
function renderCard(id) {
  const p = projById(id), el = document.querySelector(`#sidecar .pc[data-pid="${CSS.escape(id)}"]`);
  if (!p || !el) return;
  const wrap = document.createElement('div'); wrap.innerHTML = cardHtml(p); el.replaceWith(wrap.firstElementChild);
}
function renderFeed() {
  const all = S.feed, list = all.filter(passes), sc = $('#sidecar');
  const show = S.open && S.tab === 'projects', prev = sc.querySelector('.sc-body'), top = prev ? prev.scrollTop : 0;
  sc.innerHTML = `<div class="sc-head"><div><h3>Choose a project</h3><div class="small mut">${list.length} of ${all.length} projects · scroll to browse</div></div><button id="sc_close" aria-label="Close" title="Close (Esc)">×</button></div>
   <div class="sc-body">${list.length ? list.map(cardHtml).join('') : (all.length ? `<div class="banner">Your filters hide all ${all.length} projects. <button id="sc_reset">Reset all filters</button></div>` : '<div class="banner info">Loading projects…</div>')}</div>`;
  sc.querySelector('.sc-body').scrollTop = top;
  sc.classList.toggle('open', show); document.body.classList.toggle('sc-open', show);
  $('#feed').innerHTML = `<div class="banner info browse">${all.length} project ideas · ${list.length} match your filters. <button class="primary" id="browse">${show ? 'Hide project list' : 'Browse projects'}</button></div>`;
  $('#browse').onclick = () => { S.open = !S.open; renderFeed(); };
  $('#sc_close').onclick = () => { S.open = false; renderFeed(); };
  const rs = $('#sc_reset'); if (rs) rs.onclick = () => resetFilters();
  const t = all.map(p => p.verified_at).filter(Boolean).sort();
  $('#lastver').textContent = t.length ? `Most recent verification: ${S.refresh.last_finished ? S.refresh.last_finished.replace('T', ' ').slice(0, 19) + ' UTC' : '(see project cards)'}` : '';
  renderSummary();
}
/* one delegated click handler for all card buttons (so per-card re-rendering never loses handlers) */
document.addEventListener('click', e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  const a = b.dataset.act, pid = b.dataset.pid;
  if (a === 'choose') return chooseProject(pid);
  if (a === 'refresh') return refreshCard(pid);
  if (a === 'trouble') return troubleshootProject(pid);
  if (a === 'use') return useAlt(b.dataset.ds, b.dataset.url, b.dataset.pid, b.dataset.job);
});
document.addEventListener('toggle', e => { const d = e.target; if (d.matches && d.matches('details[data-exp]')) { d.open ? S.expanded.add(d.dataset.exp) : S.expanded.delete(d.dataset.exp); } }, true);

function refreshCard(id) {
  return run('card:' + id, async () => {
    renderCard(id);  // shows the busy look; the button stays clickable
    try {
      const r = await api('/api/check', { project_id: id, ...periodBody(), region: (projById(id) || {}).region || S.filters.region || undefined }, { timeout: 150000 });
      const i = S.feed.findIndex(p => p.id === id); if (i >= 0) S.feed[i] = r.project;
      toast('Refreshed “' + r.project.title + '” — other projects were left as they were.');
    } finally { delete S.busy['card:' + id]; renderCard(id); updateStats(); }
  });
}
function troubleshootProject(id) {
  return run('trouble:' + id, async () => {
    renderCard(id);
    try {
      const r = await api('/api/troubleshoot', { project_id: id }, { timeout: 240000 });
      S.trouble[id] = r; const i = S.feed.findIndex(p => p.id === id); if (i >= 0) S.feed[i] = r.project;
    } finally { delete S.busy['trouble:' + id]; renderCard(id); updateStats(); }
  });
}
async function useAlt(ds, url, pid, jobId) {
  await run('use:' + ds, async () => {
    if (jobId) { await api(`/api/jobs/${jobId}/task/${ds}/use`, { service_url: url }); toast('Switched source and restarted that dataset.'); await refreshStatus(); return; }
    await api('/api/troubleshoot/apply', { dataset_id: ds, service_url: url });
    delete S.trouble[pid]; toast('Switched to the replacement source.'); await refreshCard(pid);
  });
}
async function chooseProject(id) {
  S.chosen = { id, region: (projById(id) || {}).region || S.filters.region, period: { ...S.period } }; S.plan = null; S.sel = {}; S.extras = []; S.disc = null; S.open = false;
  showTab('project');
  loadPlan();
}

/* ---------- global refresh + stats ---------- */
async function loadFeed() { const j = await api('/api/feed?' + periodQuery()); S.feed = j.projects; S.refresh = j.refresh; renderFeed(); renderRefresh(); updateStats(); }
function renderRefresh() {
  const r = S.refresh, run_ = r.state === 'running';
  $('#refresh').classList.toggle('busy', run_); updateStats(); $('#refresh_cancel').style.display = run_ ? '' : 'none'; $('#refresh_bar').style.display = run_ ? '' : 'none';
  $('#refresh_msg').textContent = run_ ? `Checking sources: ${r.done} of ${r.total} done — ${r.message}` : (r.message || '');
  $('#refresh_log').textContent = (r.log || []).join('\n');
}
$('#refresh').onclick = () => run('refresh-all', async () => {
  resetFilters(); S.open = true; S.trouble = {};
  $('#refresh_msg').textContent = 'Starting checks…';
  await api('/api/refresh', periodBody()); pollRefresh();
});
$('#refresh_cancel').onclick = () => run('refresh-cancel', () => api('/api/refresh/cancel', {}));
function pollRefresh() {
  clearInterval(S.refTimer);
  S.refTimer = setInterval(async () => {
    try { const j = await api('/api/state'); S.refresh = j.refresh; renderRefresh(); if (j.refresh.state !== 'running') { clearInterval(S.refTimer); await loadFeed(); } }
    catch (e) { clearInterval(S.refTimer); toast('Lost contact with the server — is the terminal still running server.py?', 'bad'); }
  }, 1200);
}
function renderSrcs() {
  const r = S.refresh || {}, log = r.log || [], items = [], by = {};
  log.forEach(l => {
    const t = l.replace(/^\d\d:\d\d:\d\d\s/, ''); let m;
    if (m = t.match(/^Verifying: (.*)$/)) { by[m[1]] = { n: m[1], st: 'run', d: '' }; items.push(by[m[1]]); }
    else if (m = t.match(/^\s+→ (.*?) — (\w+)\s*(.*)$/)) { let x = by[m[1]]; if (!x) { x = by[m[1]] = { n: m[1] }; items.push(x); } x.st = m[2] === 'verified' ? 'ok' : 'bad'; x.d = m[2] + (m[3] ? ' ' + m[3] : ''); }
    else if (/^Refresh failed/.test(t)) items.push({ n: 'Refresh stopped', st: 'bad', d: t });
  });
  if (!items.length) {  // no refresh in this session: list what each project card last found
    const seen = new Set();
    S.feed.forEach(p => p.dataset_details.forEach(d => { if (d.verification && !seen.has(d.id)) { seen.add(d.id); items.push({ n: d.name, st: d.verification.status === 'verified' ? 'ok' : 'bad', d: d.verification.status }); } }));
  }
  $('#srccount').textContent = items.length;
  $('#srcs').innerHTML = items.map(x => `<div class="src ${x.st}"><i></i><div>${esc(x.n)}<small>${x.st === 'run' ? 'checking now…' : esc(x.d)}</small></div></div>`).join('');
}
function countUp(el, to) { const a = +el.dataset.v || 0; if (a === to) { el.textContent = to; return; } el.dataset.v = to; const t0 = performance.now(); (function f(t) { const p = Math.min(1, (t - t0) / 600); el.textContent = Math.round(a + (to - a) * p); if (p < 1) requestAnimationFrame(f); })(t0); }
function updateStats() {
  renderSrcs(); const all = S.feed || [], v = all.filter(p => p.availability === 'verified').length, srcs = new Set(), ok = new Set();
  all.forEach(p => p.dataset_details.forEach(d => { if (d.verification) { srcs.add(d.id || d.name); if (d.verification.status === 'verified') ok.add(d.id || d.name); } }));
  const last = S.refresh && S.refresh.last_finished ? S.refresh.last_finished.replace('T', ' ').slice(11, 16) + ' UTC' : 'never';
  $('#stats').innerHTML = `<div class="stat"><b data-k="v">0</b><span>projects ready to start</span></div><div class="stat"><b data-k="s">0</b><span>data sources checked</span></div><div class="stat"><b data-k="o">0</b><span>sources verified</span></div><div class="stat"><b style="font-size:20px">${last}</b><span>last full refresh</span></div>`;
  countUp($('[data-k=v]'), v); countUp($('[data-k=s]'), srcs.size); countUp($('[data-k=o]'), ok.size);
}
