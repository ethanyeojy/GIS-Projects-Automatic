/* ===== workflow: Project (plan) tab, missing-dataset finder, Progress, Quality, Files & maps ===== */

/* ================= PROJECT TAB (review before download) ================= */
const chosenBody = () => ({ project_id: S.chosen.id, region: S.chosen.region || undefined, ...periodBody() });
async function loadPlan() {
  S.planLoading = true; S.planError = ''; renderProject();
  try {
    S.chosen.period = { ...S.period };
    S.plan = await api('/api/plan', chosenBody(), { timeout: 300000 });
    S.plan.datasets.forEach(d => { if (!S.sel[d.id]) S.sel[d.id] = { include: true, filters: { use_period: true }, formats: d.default_formats.slice() }; });
  } catch (e) { S.planError = e.message; }
  finally { S.planLoading = false; renderProject(); }
}
const planItems = () => (S.plan ? S.plan.datasets : []);
function cleanFilters(f) {
  const o = {};
  Object.entries(f || {}).forEach(([k, v]) => { if (v === '' || v == null || (Array.isArray(v) && !v.length)) return; o[k] = v; });
  if (o.attr && (!o.attr.field || !(o.attr.values || []).length)) delete o.attr;
  if (o.max_records) o.max_records = Math.floor(+o.max_records);
  return o;
}
function ctrlHtml(d, c) {
  const f = S.sel[d.id].filters, id = `${d.id}__${c.key}`;
  if (c.type === 'number') return `<label>${esc(c.label)}<input type="number" data-ds="${d.id}" data-f="${c.key}" step="${c.step || 1}" value="${f[c.key] ?? ''}" placeholder="${c.default ?? 'no limit'}"></label>`;
  if (c.type === 'select') return `<label>${esc(c.label)}<select data-ds="${d.id}" data-f="${c.key}">${c.options.map(o => `<option value="${esc(o)}" ${(f[c.key] || '') === o ? 'selected' : ''}>${o ? esc(o.replace(/_/g, ' ').toLowerCase()) : '(any)'}</option>`).join('')}</select></label>`;
  if (c.type === 'multi') { const cur = f[c.key] || c.default; return `<div class="small"><b>${esc(c.label)}</b></div><div class="pills">${c.options.map(o => `<label class="pill"><input type="checkbox" data-ds="${d.id}" data-fm="${c.key}" value="${esc(o)}" ${cur.includes(o) ? 'checked' : ''}> ${esc(o.replace(/_/g, ' '))}</label>`).join('')}</div>`; }
  if (c.type === 'attr') {
    const a = f.attr || {}; const vals = (S.vals && S.vals[d.id]) || [];
    return `<div class="small"><b>${esc(c.label)}</b></div><div class="row"><select data-ds="${d.id}" data-attr-field><option value="">(choose a field)</option>${c.fields.map(x => `<option ${a.field === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select>
      <button data-act2="loadvals" data-ds="${d.id}">Load categories</button></div>
      ${vals.length ? `<div class="vals">${vals.slice(0, 200).map(v => `<label class="pill"><input type="checkbox" data-ds="${d.id}" data-attr-val value="${esc(v)}" ${(a.values || []).includes(String(v)) ? 'checked' : ''}> ${esc(v)}</label>`).join('')}</div>` : '<div class="small mut">Pick a field and load its categories to tick the ones you want.</div>'}`;
  }
  return '';
}
function dsPlanHtml(d) {
  const sel = S.sel[d.id] || (S.sel[d.id] = { include: true, filters: { use_period: true }, formats: d.default_formats.slice() });
  const okS = d.status === 'verified';
  const lim = S.settings.max_file_mb;
  const est = d.est_bytes != null && lim && d.est_bytes > lim * 1048576;
  return `<div class="dsp ${sel.include ? '' : 'off'}" data-dsp="${esc(d.id)}">
   <div class="dsp-top"><label class="chk"><input type="checkbox" data-inc="${esc(d.id)}" ${sel.include ? 'checked' : ''}> <b>${esc(d.name)}</b></label>${covChip(d.coverage)}${okS ? '' : `<span class="chip bad">${esc(d.status)}</span>`}${d.extra ? '<span class="chip">added by you</span>' : ''}</div>
   <div class="small mut">${esc(d.publisher)}${d.landing_url ? ` · <a href="${esc(d.landing_url)}" target="_blank" rel="noopener">source</a>` : ''}</div>
   <div class="dsp-nums">After your area, time period and filters: <b>${fmtN(d.count)} records</b> · <b>≈ ${fmtB(d.est_bytes)}</b> <span class="mut small">${d.est_note ? '(' + esc(d.est_note) + ')' : ''}</span></div>
   ${d.coverage && ['gap', 'partial'].includes(d.coverage.status) ? `<div class="banner small">⚠ ${esc(d.coverage.note)} You'll be asked what to do when the download starts — nothing is substituted.</div>` : (d.coverage ? `<div class="small mut">${esc(d.coverage.note)}</div>` : '')}
   ${est ? `<div class="banner small">⚠ Estimated over your ${lim} MB per-file limit — you'll be asked how to handle it (filter, keep the first N, split where supported, skip, or allow).</div>` : ''}
   ${d.failed.length ? `<div class="banner bad small">${d.failed.map(f => esc(f.name + ' — ' + f.detail)).join('<br>')}</div>` : ''}
   <details class="dsp-f" data-exp="plan:${esc(d.id)}" ${keepOpen('plan:' + d.id)}><summary>Filters, limits &amp; export formats</summary>
    <div class="fgrid">
     <div><div class="small"><b>Area</b></div><div class="small mut">${S.chosen.region ? esc(S.chosen.region) : 'All of New Zealand'} <span class="mut">(change in Settings / Filters)</span></div></div>
     <div><div class="small"><b>Dates</b></div>${d.caps.period ? `<label class="chk small"><input type="checkbox" data-ds="${esc(d.id)}" data-usep ${sel.filters.use_period !== false ? 'checked' : ''}> Use my time period (${esc(S.periodInfo ? S.periodInfo.start + ' → ' + S.periodInfo.end : '')})</label>` : '<div class="small mut">Not filtered by date for this source.</div>'}</div>
     ${d.schema.map(c => `<div class="fc">${ctrlHtml(d, c)}</div>`).join('')}
     <div class="fc"><label>Maximum number of records<input type="number" min="1" data-ds="${esc(d.id)}" data-f="max_records" value="${sel.filters.max_records ?? ''}" placeholder="no limit"></label><div class="small mut">If more match, you choose how to reduce — nothing is cut silently.</div></div>
     <div class="fc"><div class="small"><b>Export formats</b></div><div class="pills">${d.formats.map(fm => `<label class="pill"><input type="checkbox" data-ds="${esc(d.id)}" data-fmt="${fm}" ${sel.formats.includes(fm) ? 'checked' : ''}> ${fm === 'geojson' ? 'GeoJSON (ArcGIS Pro)' : fm === 'csv' ? 'CSV (Excel)' : 'Excel .xlsx'}</label>`).join('')}</div></div>
    </div>
    <div class="actions"><button data-act2="estimate" data-ds="${esc(d.id)}" class="${isBusy('est:' + d.id) ? 'busy' : ''}">${isBusy('est:' + d.id) ? '↻ Updating…' : '↻ Update count & size'}</button></div>
   </details></div>`;
}
function renderProject() {
  const el = $('#project');
  if (!S.chosen) { el.innerHTML = '<div class="banner info">Choose a project on the Projects tab first.</div>'; return; }
  const p = projById(S.chosen.id); if (!p) return;
  const pi = S.periodInfo;
  const head = `<div class="projhead" style="--tc:${THEME_COL[p.theme] || 'var(--acc)'}">
    <div class="ph-kicker">${esc(p.icon || '')} ${esc(THEME_LBL[p.theme] || p.theme)} · ${esc(p.difficulty)} · ≈${p.workload_h[0]}–${p.workload_h[1]} h</div>
    <h1>${esc(p.title)}</h1>
    <div class="bigq"><span class="bq-label">Main research question</span>${esc(p.question)}</div>
    <p class="purpose"><b>What this investigates and why it matters.</b> ${esc(p.purpose)}</p>
    <div class="row"><span class="chip">Study area: ${esc(S.chosen.region || 'All of New Zealand')}</span><span class="chip">Time period: ${esc(pi ? pi.label + ' · ' + pi.start + ' → ' + pi.end : '…')}</span><span class="chip">Max file size: ${esc(String(S.settings.max_file_mb))} MB per file</span></div>
   </div>`;
  let body;
  if (S.planLoading) body = `<div class="banner info"><b>Checking every dataset live</b> against your study area, time period and filters (this can take up to a minute)…<div class="bar ind" style="margin-top:8px"><i></i></div></div>`;
  else if (S.planError) body = `<div class="banner bad"><b>Couldn't prepare the dataset list.</b> ${esc(S.planError)}<div class="actions"><button class="primary" data-act2="replan">Try again</button><button data-act="trouble" data-pid="${esc(p.id)}">🔧 Troubleshoot</button></div></div>`;
  else if (S.plan) body = `<h2 class="sect">Datasets (${planItems().length}${S.extras.length ? ' + ' + S.extras.length + ' added' : ''})</h2>
    <p class="small mut">Untick anything you don't want. Open <b>Filters</b> on a dataset to narrow it before it is downloaded; the count and size update from the live source.</p>
    <div id="dsplist">${planItems().map(dsPlanHtml).join('')}</div>
    <h2 class="sect">Find missing datasets</h2>${discPanelHtml()}`;
  else body = '';
  el.innerHTML = head + body + planFooter();
}
/* rough outlook: what the finished project could look like, shown as soon as a project is chosen (no data downloaded yet) */
const outlookKey = () => S.chosen ? [S.chosen.id, S.chosen.region || '', S.period.preset, S.period.start, S.period.end].join('|') : '';
function outlookBox() {
  const ready = S.outlook && S.outlook.key === outlookKey() && S.outlook.data;
  return `<details class="outlookwrap" open><summary><b>Rough outlook of the finished project</b> <span class="small mut">— a layout preview with illustrations; nothing is downloaded yet</span></summary>
   <div id="outlook" class="smap">${ready ? smPreview(S.outlook.data) : '<div class="banner info">Preparing the outlook…</div>'}</div></details>`;
}
async function loadOutlook() {
  const key = outlookKey(); if (!key) return;
  S.outlook = { key, data: null };
  try {
    const q = new URLSearchParams({ project_id: S.chosen.id, preset: S.period.preset, ...(S.period.start ? { start: S.period.start } : {}), ...(S.period.end ? { end: S.period.end } : {}), ...(S.chosen.region ? { region: S.chosen.region } : {}) });
    const d = await api('/api/outlook?' + q.toString(), undefined, { timeout: 60000 });
    if (outlookKey() !== key) return;
    S.outlook = { key, data: d };
    const box = $('#outlook'); if (box) box.innerHTML = smPreview(d);
  } catch (e) { const box = $('#outlook'); if (box) box.innerHTML = `<div class="banner bad small">Couldn't build the outlook: ${esc(e.message)}</div>`; }
}
function planFooter() {
  if (!S.plan || S.planLoading) return '';
  const inc = planItems().filter(d => (S.sel[d.id] || {}).include);
  const tot = inc.reduce((a, d) => a + (d.est_bytes || 0), 0), unk = inc.some(d => d.est_bytes == null);
  const lim = S.settings.max_file_mb, over = inc.filter(d => d.est_bytes != null && lim && d.est_bytes > lim * 1048576);
  const gaps = inc.filter(d => d.coverage && ['gap', 'partial'].includes(d.coverage.status));
  return `<div class="planfoot"><div><b>${inc.length}</b> of ${planItems().length} datasets selected · estimated total ≈ ${fmtB(tot)}${unk ? ' + some unknown' : ''}
    <div class="small mut">${over.length ? `${over.length} file(s) estimated over the ${lim} MB per-file limit (each file is checked on its own). ` : 'Every file is within your per-file limit. '}${gaps.length ? `${gaps.length} dataset(s) don't fully cover your period — you'll be asked. ` : ''}Nothing is downloaded until you press Start.</div></div>
    <div class="row"><button data-act2="replan" class="${S.planLoading ? 'busy' : ''}">↻ Re-check datasets for this period</button><button class="primary big" data-act2="start">Start download →</button></div></div>`;
}
async function estimateOne(ds) {
  await run('est:' + ds, async () => {
    const sel = S.sel[ds]; rerenderDs(ds);
    try {
      const r = await api('/api/plan/estimate', { dataset_id: ds, region: S.chosen.region || undefined, ...periodBody(), filters: cleanFilters(sel.filters) }, { timeout: 120000 });
      const i = S.plan.datasets.findIndex(x => x.id === ds); if (i >= 0) S.plan.datasets[i] = { ...S.plan.datasets[i], ...r, extra: S.plan.datasets[i].extra };
    } finally { delete S.busy['est:' + ds]; rerenderDs(ds); refreshFooter(); }
  });
}
function rerenderDs(ds) {
  const d = planItems().find(x => x.id === ds), el = document.querySelector(`.dsp[data-dsp="${CSS.escape(ds)}"]`); if (!d || !el) return;
  const w = document.createElement('div'); w.innerHTML = dsPlanHtml(d); el.replaceWith(w.firstElementChild);
}
function refreshFooter() { const f = $('#project .planfoot'); if (f) { const w = document.createElement('div'); w.innerHTML = planFooter(); f.replaceWith(w.firstElementChild); } }
async function startDownload() {
  await run('start', async () => {
    const plan = { datasets: {}, extras: S.extras.slice() };
    planItems().forEach(d => { const s = S.sel[d.id]; plan.datasets[d.id] = { include: !!s.include, filters: cleanFilters(s.filters), formats: s.formats.length ? s.formats : d.default_formats }; });
    if (!Object.values(plan.datasets).some(x => x.include)) throw new Error('Tick at least one dataset to download.');
    const r = await api('/api/start', { ...chosenBody(), plan });
    S.job = r.job_id; S.jobData = null; S.lastStatus = null; S.taskTrouble = {};
    S.jobs = (await api('/api/jobs')).jobs; S.folderSlug = null;
    showTab('progress'); startPolling(true);
  });
}
/* delegated handlers for the Project tab */
document.addEventListener('change', e => {
  const t = e.target, ds = t.dataset && t.dataset.ds;
  if (t.dataset && t.dataset.inc) { S.sel[t.dataset.inc].include = t.checked; t.closest('.dsp').classList.toggle('off', !t.checked); refreshFooter(); return; }
  if (!ds || !S.sel[ds]) return;
  const f = S.sel[ds].filters;
  if (t.dataset.f) f[t.dataset.f] = t.type === 'number' ? (t.value === '' ? '' : +t.value) : t.value;
  else if (t.dataset.usep !== undefined) f.use_period = t.checked;
  else if (t.dataset.fm) { const k = t.dataset.fm, cur = new Set(f[k] || (planItems().find(x => x.id === ds).schema.find(c => c.key === k).default)); t.checked ? cur.add(t.value) : cur.delete(t.value); f[k] = [...cur]; }
  else if (t.dataset.fmt) { const s = S.sel[ds]; const set = new Set(s.formats); t.checked ? set.add(t.dataset.fmt) : set.delete(t.dataset.fmt); s.formats = [...set]; }
  else if (t.dataset.attrField !== undefined) { f.attr = { field: t.value, values: [] }; if (S.vals) delete S.vals[ds]; rerenderDs(ds); }
  else if (t.dataset.attrVal !== undefined) { f.attr = f.attr || { field: '', values: [] }; const v = new Set(f.attr.values); t.checked ? v.add(t.value) : v.delete(t.value); f.attr.values = [...v]; }
});
document.addEventListener('click', e => {
  const b = e.target.closest('[data-act2]'); if (!b) return;
  const a = b.dataset.act2, ds = b.dataset.ds;
  if (a === 'estimate') estimateOne(ds);
  else if (a === 'replan') run('replan', () => loadPlan());
  else if (a === 'start') startDownload();
  else if (a === 'loadvals') run('vals:' + ds, async () => {
    const field = (S.sel[ds].filters.attr || {}).field; if (!field) throw new Error('Choose a field first.');
    const r = await api('/api/dataset/values', { dataset_id: ds, field, region: S.chosen.region || undefined });
    (S.vals = S.vals || {})[ds] = r.values; if (!r.values.length) toast('That field has no categories to list.'); rerenderDs(ds);
  });
  else if (a === 'disc-find') discSearch('search');
  else if (a === 'disc-gaps') discSearch('gaps');
  else if (a === 'disc-add') discAdd();
});

/* ================= FIND MISSING DATASETS ================= */
function discPanelHtml() {
  return `<div class="discbox"><p class="small mut">Describe data you're missing (for example “rainfall stations” or “building footprints”), or ask the app to spot gaps. It searches the app's verified catalogue, ArcGIS Online public items, the NZ open-data catalogue and GBIF species — using this project, its question, your area and your time period. Nothing is invented: anything a source doesn't report is shown as unknown.</p>
   <div class="row"><input type="text" id="disc_q" placeholder="e.g. rainfall stations, river flow, population by council" value="${esc(S.discQ || '')}" style="flex:1;min-width:220px">
    <button class="primary" data-act2="disc-find" class="${isBusy('disc') ? 'busy' : ''}">${isBusy('disc') ? 'Searching…' : 'Find datasets'}</button><button data-act2="disc-gaps">Identify gaps in this project</button></div>
   <div id="discres">${S.disc ? discHtml(S.disc) : ''}</div></div>`;
}
async function discSearch(mode) {
  S.discQ = ($('#disc_q') || {}).value || '';
  await run('disc', async () => {
    S.busy.disc = Date.now(); $('#discres').innerHTML = '<div class="banner info">Searching real catalogues and checking the top services live… up to a minute.<div class="bar ind" style="margin-top:8px"><i></i></div></div>';
    try { S.disc = await api('/api/discovery', { project_id: S.chosen.id, region: S.chosen.region || undefined, ...periodBody(), query: S.discQ, mode, have: S.extras }, { timeout: 150000 }); S.discSel = new Set(); }
    finally { delete S.busy.disc; const r = $('#discres'); if (r) r.innerHTML = S.disc ? discHtml(S.disc) : ''; }
  });
}
const READY = { ready: ['ok', 'Ready to download'], unverified: ['', 'Will be checked when added'], manual: ['warn', 'Manual step needed'], needs_access: ['bad', 'Needs access / login'] };
function discHtml(d) {
  const c = d.context;
  return `<div class="disc">
   <div class="small"><b>Using:</b> ${esc(c.project)} · ${esc(c.region)} · ${esc(c.period)} · ${c.have.length} existing dataset(s)<br><b>Question:</b> ${esc(c.question)}</div>
   ${d.gaps && d.gaps.length ? `<div class="banner small"><b>Possible gaps in this project's data</b> (rule-based): ${d.gaps.map(g => esc(g.label)).join('; ')}.</div>` : ''}
   <div class="small mut">Searched: ${d.searched.map(esc).join(' · ')}. ${esc(d.method)}</div>${(d.notes || []).map(n => `<div class="banner small">${esc(n)}</div>`).join('')}
   <div class="disclist">${d.candidates.map(x => candHtml(x)).join('') || '<div class="banner info">No candidates found.</div>'}</div>
   ${d.candidates.some(x => x.dataset_id || x.spec) ? `<div class="actions"><button class="primary" data-act2="disc-add">Add selected to this project</button><span class="small mut">Added datasets join the list above, where you can filter them before anything downloads.</span></div>` : ''}</div>`;
}
function candHtml(x) {
  const addable = !!(x.dataset_id || x.spec), r = READY[x.ready] || ['', x.ready];
  return `<div class="cand">
   <div class="cand-top">${addable ? `<input type="checkbox" data-disc="${esc(x.id)}" ${(S.discSel && S.discSel.has(x.id)) ? 'checked' : ''} aria-label="Select ${esc(x.title)}">` : '<span class="nocb">—</span>'}
    <b>${esc(x.title)}</b><span class="chip ${r[0]}">${r[1]}</span></div>
   <div class="small mut">${esc(x.source)} · ${esc(x.origin)}</div>
   <div class="small">${esc(x.why)}</div>
   <dl class="cand-dl"><dt>Time coverage</dt><dd>${esc(x.time_coverage)}</dd><dt>Area</dt><dd>${esc(x.geo_coverage)}</dd><dt>Format</dt><dd>${esc(x.format)}</dd>
    <dt>Size</dt><dd>${esc(x.size_text)}</dd><dt>Records</dt><dd>${x.records != null ? fmtN(x.records) : 'unknown'}</dd><dt>Licence</dt><dd>${esc(x.licence || 'unknown')}</dd></dl>
   <div class="small ${x.ready === 'ready' || x.ready === 'unverified' ? 'mut' : ''}">${esc(x.ready_note)} ${x.link ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">open source</a>` : ''}</div></div>`;
}
document.addEventListener('change', e => { const t = e.target; if (t.dataset && t.dataset.disc !== undefined) { (S.discSel = S.discSel || new Set()); t.checked ? S.discSel.add(t.dataset.disc) : S.discSel.delete(t.dataset.disc); } });
async function discAdd() {
  if (!S.chosen) return toast('Choose a project first, then add datasets to it.');
  const ids = [...(S.discSel || [])]; if (!ids.length) return toast('Tick at least one dataset first.');
  await run('disc-add', async () => {
    const r = await api('/api/discovery/add', { ids });
    for (const d of r.datasets) {
      if (S.extras.includes(d.id) || planItems().some(x => x.id === d.id)) continue;
      const est = await api('/api/plan/estimate', { dataset_id: d.id, region: S.chosen.region || undefined, ...periodBody(), filters: {} }, { timeout: 120000 });
      S.plan.datasets.push({ ...est, extra: true }); S.sel[d.id] = { include: true, filters: { use_period: true }, formats: est.default_formats.slice() }; S.extras.push(d.id);
    }
    S.discSel = new Set(); toast(`${r.datasets.length} dataset(s) added — scroll up to filter them.`); S.tab === 'project' && renderProject();
  });
}

/* ================= PROGRESS TAB ================= */
const STATE_LBL = { queued: 'Queued', running: 'Running', retrying: 'Retrying', waiting_input: 'Waiting for you', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled', skipped: 'Skipped' };
const STATE_CLS = { queued: '', running: 'run', retrying: 'warn', waiting_input: 'ask', completed: 'ok', failed: 'bad', cancelled: 'bad', skipped: '' };
const STAGE_LBL = { queued: 'Queued', searching: 'Searching', filtering: 'Filtering', downloading: 'Downloading', converting: 'Converting', completed: 'Completed', failed: 'Stopped', cancelled: 'Stopped', skipped: 'Skipped' };
const ACTIVE = ['running', 'retrying', 'waiting_input'];
function startPolling(now) {
  clearInterval(S.pollTimer); S.pollTimer = setInterval(() => pollOnce(false), 1500); if (now) pollOnce(false);
}
async function pollOnce(manual) {
  if (!S.job) return;
  try { const j = await api('/api/jobs/' + S.job, undefined, { timeout: 20000 }); onJob(j); S.pollFail = 0; }
  catch (e) { S.pollFail = (S.pollFail || 0) + 1; if (manual || S.pollFail === 4) toast('Couldn’t reach the server just now. It is probably still working — press “Refresh status” in a moment.', 'bad'); }
}
function jobBusy(j) { return j.status === 'running' || Object.values(j.datasets).some(t => ACTIVE.includes(t.state)); }
function onJob(j) {
  const prev = S.lastStatus; S.jobData = j; S.offset = j.now - Date.now() / 1000; S.lastStatus = j.status;
  S.folderSlug = j.folder.split(/[\\/]/).pop();
  if (S.tab === 'progress') renderProgress(); renderStageBar();
  if (S.tab === 'quality') renderQuality();
  if (!jobBusy(j) && !(S.pollKeep)) { clearInterval(S.pollTimer); S.pollTimer = null; }
  if (prev && prev !== 'ready' && j.status === 'ready' && S.tab === 'progress') { toast('Downloads finished — here is the quality check.'); showTab('quality'); }
}
async function refreshStatus() { await run('status', async () => { await pollOnce(true); toast('Status refreshed — nothing was restarted.'); if (S.job && jobBusy(S.jobData || { status: '', datasets: {} })) startPolling(); }); }
function actAgo(el) {
  const ts = +el.dataset.ts; if (!ts) { el.textContent = 'no activity yet'; return; }
  const idle = nowSrv() - ts, stall = (S.jobData && S.jobData.stall_seconds) || 90;
  el.textContent = 'Last activity: ' + ago(idle); el.className = 'act ' + (idle > stall ? 'stalled' : idle > stall / 2 ? 'slow' : '');
}
setInterval(() => $$('.act').forEach(actAgo), 1000);

function taskProgress(t) {
  if (!ACTIVE.includes(t.state) && t.state !== 'completed') return '';
  if (t.state === 'completed') return `<div class="bar"><i style="width:100%"></i></div>`;
  if (t.measurable && t.total) { const p = Math.min(100, Math.round(100 * (t.records || 0) / t.total)); return `<div class="bar"><i style="width:${p}%"></i></div><div class="small">${fmtN(t.records || 0)} of ${fmtN(t.total)} records${t.bytes ? ' · ' + fmtB(t.bytes) : ''} (${p}%)</div>`; }
  if (t.state === 'waiting_input') return '';
  return `<div class="bar ind"><i></i></div><div class="small mut">Progress can't be measured for this step${t.bytes ? ` — ${fmtB(t.bytes)} received so far` : ' — the size is unknown until it arrives'}.</div>`;
}
function decisionHtml(t, j) {
  const d = t.decision; if (!d) return '';
  const opts = d.options.map(o => {
    const num = o.needs === 'number' ? `<input type="number" min="1" class="n" data-numfor="${esc(t.id)}:${o.id}" value="${o.default || ''}" aria-label="How many records">` : '';
    return `<span class="optwrap">${num}<button class="${o.id === 'skip' ? '' : 'primary'}" data-dec="${esc(t.id)}" data-opt="${esc(o.id)}" data-needs="${esc(o.needs || '')}">${esc(o.label)}</button></span>`;
  }).join('');
  return `<div class="decision ${d.kind === 'stalled' ? 'stall' : ''}"><div class="dec-h">❓ ${esc(d.title)}</div><div class="dec-m">${esc(d.message)}</div><div class="dec-o">${opts}</div><div id="fe-${esc(t.id)}"></div></div>`;
}
function taskHtml(t, j) {
  const state = t.stalled ? 'stalled' : t.state, lbl = t.stalled ? 'Appears stalled' : STATE_LBL[t.state], cls = t.stalled ? 'bad' : STATE_CLS[t.state];
  const tr = S.taskTrouble[t.id], active = ACTIVE.includes(t.state), done = t.state === 'completed';
  const name = t.id === 'regc' ? 'Study-area boundaries' : t.name;
  return `<div class="task ${state}" data-task="${esc(t.id)}">
   <div class="task-top"><b>${esc(name)}</b><span class="chip ${cls}">${lbl}</span><span class="chip">${esc(STAGE_LBL[t.stage] || t.stage)}</span>${t.auto_retries ? `<span class="chip warn">auto-retried ${t.auto_retries}×</span>` : ''}</div>
   <div class="small mut">${esc(t.publisher)}${t.attempt > 1 ? ` · attempt ${t.attempt}` : ''}</div>
   ${taskProgress(t)}
   <div class="task-msg">${esc(t.message || '')}</div>
   ${active || t.last_activity_ts ? `<div class="act" data-ts="${t.last_activity_ts || ''}"></div>` : ''}
   ${t.coverage && ['gap', 'partial'].includes(t.coverage.status) ? `<div class="small">⚠ ${esc(t.coverage.note)}</div>` : ''}
   ${decisionHtml(t, j)}
   ${t.state === 'failed' ? `<div class="banner bad small"><b>What went wrong:</b> ${esc(t.error || '')}<ul>${(t.diagnosis || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
   ${done ? `<div class="small">✓ ${fmtN(t.records)} records · ${t.exports.length} export file(s) ready (${t.exports.map(e => esc(e.format.toUpperCase())).join(', ')}) <a href="#" data-go="files">View in Files &amp; maps</a></div>` : ''}
   ${(t.warnings || []).length && done ? `<details class="small"><summary>${t.warnings.length} note(s)</summary><ul>${t.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></details>` : ''}
   ${tr ? tsItem(tr, '', j.id) : ''}
   <div class="actions task-act">
    <button data-tact="status" data-ds="${esc(t.id)}">↻ Refresh status</button>
    <button data-tact="diagnose" data-ds="${esc(t.id)}" class="${isBusy('diag:' + t.id) ? 'busy' : ''}">🔧 ${isBusy('diag:' + t.id) ? 'Troubleshooting…' : 'Troubleshoot'}</button>
    ${done ? '' : `<button data-tact="retry" data-ds="${esc(t.id)}" class="${t.state === 'failed' || t.stalled || t.state === 'cancelled' || t.state === 'skipped' ? 'primary' : ''}">⟲ Retry</button>`}
    ${done || t.state === 'skipped' ? '' : `<button data-tact="skip" data-ds="${esc(t.id)}">Skip</button>`}
    ${active ? `<button data-tact="cancel" data-ds="${esc(t.id)}">Cancel</button>` : ''}
   </div></div>`;
}
function renderProgress() {
  const el = $('#progress'), j = S.jobData;
  if (!S.job) { el.innerHTML = '<div class="banner info">No project started yet. Choose a project, review its datasets and press Start download.</div>'; return; }
  if (!j) { el.innerHTML = '<div class="banner info">Starting…</div>'; return; }
  const p = projById(j.project_id) || {}, sel = S.jobs.map(x => `<option value="${x.id}" ${x.id === S.job ? 'selected' : ''}>${esc(x.title.slice(0, 60))} — ${esc(x.region || 'NZ')} — ${esc(x.status)}</option>`).join('');
  const tasks = Object.values(j.datasets), waiting = tasks.filter(t => t.state === 'waiting_input'), failed = tasks.filter(t => t.state === 'failed' || t.stalled);
  const stages = Object.entries(j.stages).map(([k, s]) => `<div class="stg ${s.status}"><i></i><span>${esc(s.label)}</span></div>`).join('');
  const chip = j.status === 'ready' ? ['ok', 'Finished'] : waiting.length ? ['ask', 'Waiting for you'] : j.status === 'running' ? ['run', 'Running'] : ['bad', j.status];
  const doneN = tasks.filter(t => t.state === 'completed').length;
  el.innerHTML = `${S.jobs.length > 1 ? `<div class="row" style="margin-bottom:8px"><select id="jsel" style="max-width:520px">${sel}</select></div>` : ''}
   <div class="projhead small-head"><h1>${esc(j.title)}</h1><div class="bigq"><span class="bq-label">Main research question</span>${esc(j.question || p.question || '')}</div></div>
   ${waiting.length ? `<div class="banner ask"><b>${waiting.length} dataset(s) are waiting for your decision.</b> The others keep going. Answer below to continue.</div>` : ''}
   ${j.status === 'ready' ? `<div class="banner okb"><b>${esc(j.message)}</b> <div class="actions"><button class="primary" data-go="quality">Next: Quality check →</button></div></div>` : ''}
   ${j.status === 'failed' || j.status === 'cancelled' || j.status === 'interrupted' ? `<div class="banner bad"><b>${esc(j.message || j.status)}</b></div>` : ''}
   <div class="card"><div class="row between"><div><b>Overall:</b> <span class="chip ${chip[0]}">${esc(chip[1])}</span> <span class="small mut">${doneN} of ${tasks.length} datasets complete · stage ${Math.min(j.stages_done + 1, j.stages_total)} of ${j.stages_total}</span></div>
     <div class="row"><button data-jact="status">↻ Refresh status</button>${['failed', 'cancelled', 'interrupted'].includes(j.status) ? '<button class="primary" data-jact="retry">⟲ Retry job</button>' : ''}${jobBusy(j) ? '<button data-jact="cancel">Cancel all</button>' : ''}</div></div>
     <div class="stages">${stages}</div><div class="small mut">Bars show real progress where the source reports it; otherwise the page says it can't be measured.</div></div>
   <div id="tasklist">${tasks.sort((a, b) => (a.id === 'regc' ? -1 : b.id === 'regc' ? 1 : 0)).map(t => taskHtml(t, j)).join('')}</div>
   <details style="margin-top:12px"><summary>Activity log</summary><pre id="jlog">${esc(j.log.join('\n'))}</pre></details>`;
  const s = $('#jsel'); if (s) s.onchange = async e => { S.job = e.target.value; S.jobData = null; await pollOnce(true); startPolling(); };
  $$('.act').forEach(actAgo);
}
document.addEventListener('click', e => {
  const g = e.target.closest('[data-go]'); if (g) { e.preventDefault(); return showTab(g.dataset.go); }
  const ja = e.target.closest('[data-jact]');
  if (ja) { const a = ja.dataset.jact; if (a === 'status') return refreshStatus(); return run('job-' + a, async () => { await api(`/api/jobs/${S.job}/${a}`, {}); toast(a === 'retry' ? 'Restarting — finished datasets are reused.' : 'Cancelling…'); startPolling(true); }); }
  const ta = e.target.closest('[data-tact]');
  if (ta) return taskAction(ta.dataset.tact, ta.dataset.ds);
  const de = e.target.closest('[data-dec]');
  if (de) return decide(de.dataset.dec, de.dataset.opt, de.dataset.needs);
  const fa = e.target.closest('[data-fapply]');
  if (fa) return applyFilterEditor(fa.dataset.fapply);
});
async function taskAction(act, ds) {
  if (act === 'status') return refreshStatus();
  await run(`t:${act}:${ds}`, async () => {
    if (act === 'diagnose') {
      S.busy['diag:' + ds] = Date.now() + 1e9; renderProgress();
      try { S.taskTrouble[ds] = await api(`/api/jobs/${S.job}/task/${ds}/diagnose`, {}, { timeout: 200000 }); } finally { delete S.busy['diag:' + ds]; renderProgress(); }
      return;
    }
    const r = await api(`/api/jobs/${S.job}/task/${ds}/${act}`, {});
    if (act === 'retry') toast(r.message || 'Restarted.', r.started ? '' : 'bad');
    if (act === 'skip') toast('Skipped — the other datasets continue.');
    if (act === 'cancel') toast('Cancelled that dataset.');
    startPolling(true);
  });
}
async function decide(ds, opt, needs) {
  if (needs === 'filters') return openFilterEditor(ds);
  const num = document.querySelector(`[data-numfor="${CSS.escape(ds + ':' + opt)}"]`);
  const params = num ? { n: +num.value } : {};
  await run(`dec:${ds}:${opt}`, async () => {
    if (opt === 'alternative') { S.taskTrouble[ds] = await api(`/api/jobs/${S.job}/task/${ds}/diagnose`, {}, { timeout: 200000 }); toast('Pick a replacement below, or choose another option.'); renderProgress(); return; }
    await api(`/api/jobs/${S.job}/task/${ds}/decide`, { option: opt, params });
    toast('Got it — continuing with your choice.'); startPolling(true);
  });
}
async function openFilterEditor(ds) {
  const box = document.getElementById('fe-' + ds); if (!box) return;
  box.innerHTML = '<div class="small mut">Loading what this source can filter…</div>';
  try {
    const r = await api('/api/plan/estimate', { dataset_id: ds, region: S.jobData.region || undefined, ...periodBody(), filters: {} });
    S.feSchema = S.feSchema || {}; S.feSchema[ds] = r.schema;
    box.innerHTML = `<div class="fe"><b>Apply more filters</b><div class="fgrid">${r.schema.map(c => c.type === 'number' ? `<label>${esc(c.label)}<input type="number" data-fe="${esc(ds)}" data-k="${c.key}" placeholder="${c.default ?? ''}"></label>` : c.type === 'select' ? `<label>${esc(c.label)}<select data-fe="${esc(ds)}" data-k="${c.key}">${c.options.map(o => `<option value="${esc(o)}">${o ? esc(o.replace(/_/g, ' ').toLowerCase()) : '(any)'}</option>`).join('')}</select></label>` : '').join('')}
      <label>Maximum number of records<input type="number" min="1" data-fe="${esc(ds)}" data-k="max_records" placeholder="no limit"></label></div>
      <div class="actions"><button class="primary" data-fapply="${esc(ds)}">Apply and continue</button></div></div>`;
  } catch (e) { box.innerHTML = `<div class="banner bad small">${esc(e.message)}</div>`; }
}
async function applyFilterEditor(ds) {
  const f = {}; $$(`[data-fe="${CSS.escape(ds)}"]`).forEach(i => { if (i.value !== '') f[i.dataset.k] = i.type === 'number' ? +i.value : i.value; });
  if (!Object.keys(f).length) return toast('Enter at least one filter value.');
  await run('fe:' + ds, async () => { await api(`/api/jobs/${S.job}/task/${ds}/decide`, { option: 'filter', params: { filters: f } }); toast('Filters applied — re-checking this dataset.'); startPolling(true); });
}

/* ================= QUALITY TAB (plain language) ================= */
const shapeWord = gt => { const k = Object.keys(gt || {}).filter(x => x !== 'null'); if (!k.length) return 'no map shapes (a table of records)'; const w = new Set(k.map(x => /Point/.test(x) ? 'points' : /Line/.test(x) ? 'lines' : 'areas')); return [...w].join(' and '); };
function renderQuality() {
  const el = $('#quality'), j = S.jobData;
  if (!j) { el.innerHTML = '<div class="banner info">Start a project to see its quality check.</div>'; return; }
  const ids = Object.keys(j.datasets).filter(d => d !== 'regc');
  const rows = ids.map(d => {
    const t = j.datasets[d], q = j.inspections[d], ts = j.tag_stats && j.tag_stats[d];
    const warn = [...new Set([...(q ? q.warnings : []), ...(t.warnings || [])])];
    let status, cls;
    if (t.state === 'completed') { status = warn.length ? `⚠ Usable — ${warn.length} thing${warn.length > 1 ? 's' : ''} to be aware of` : '✓ Looks fine'; cls = warn.length ? 'warn' : 'ok'; }
    else if (t.state === 'skipped') { status = '— Left out of this package'; cls = ''; }
    else { status = '✗ Not included yet — ' + (STATE_LBL[t.state] || t.state).toLowerCase(); cls = 'bad'; }
    const dates = q && Object.entries(q.date_fields || {}).filter(([, v]) => v.min).map(([k, v]) => `${esc(k)}: ${esc((v.min || '').slice(0, 10))} to ${esc((v.max || '').slice(0, 10))}`)[0];
    return `<div class="qcard ${cls}"><div class="qtop"><b>${esc(t.name)}</b><span class="chip ${cls}">${status}</span></div>
      ${q ? `<ul class="qfacts"><li><b>${fmtN(q.records)}</b> records</li><li>Shapes: ${shapeWord(q.geometry_types)}</li>${dates ? `<li>Dates covered — ${dates}</li>` : ''}${q.invalid_geometry ? `<li>${q.invalid_geometry} shapes are invalid and need repairing in ArcGIS Pro</li>` : ''}
       ${ts ? `<li>${fmtN(ts.total - ts.untagged)} of ${fmtN(ts.total)} points sit inside a regional council area${ts.untagged ? ` (${fmtN(ts.untagged)} don't — often offshore)` : ''}</li>` : ''}</ul>` : `<div class="small mut">${esc(t.message || '')}</div>`}
      ${warn.length ? `<div class="small"><b>Things to be aware of</b></div><ul class="small">${warn.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
      ${q ? `<details class="small"><summary>Technical details</summary><div>Fields: ${esc((q.fields || []).slice(0, 40).join(', '))}</div><div>${Object.entries(q.special || {}).map(([k, v]) => esc(k) + ': ' + esc(JSON.stringify(v))).join('<br>')}</div></details>` : ''}</div>`;
  }).join('');
  const ok = ids.filter(d => j.datasets[d].state === 'completed').length;
  const cm = (j.compat || []).filter(r => !/^Spatial overlap/.test(r.need));
  const compat = cm.length ? `<h2 class="sect">Can this data answer your question?</h2><div class="card">${cm.map(r => `<div class="crow"><span class="cmark ${r.status}">${r.status === 'ok' ? '✓' : r.status === 'warning' ? '⚠' : '✗'}</span><div><b>${esc(r.need)}</b><div class="small mut">${r.status === 'ok' ? 'Found in the data.' : r.status === 'warning' ? 'Possible but needs care.' : 'Missing — this part of the question cannot be answered with the datasets that were downloaded.'}</div><details class="small"><summary>Evidence</summary>${esc(r.detail)}</details></div></div>`).join('')}</div>` : '';
  el.innerHTML = `<div class="projhead small-head"><h1>Quality check</h1><p class="purpose">A plain-language look at what was downloaded. These are mechanical checks — they don't prove the data is right or complete in the real world.</p></div>
   <div class="card qsum"><b>${ok} of ${ids.length}</b> datasets are in your package.${ok < ids.length ? ' The rest need attention on the Progress tab.' : ' '} <div class="actions"><button class="primary" data-go="files">Next: Files &amp; maps →</button><button data-go="progress">Back to Progress</button></div></div>
   <h2 class="sect">Dataset by dataset</h2>${rows || '<div class="banner info">No datasets yet.</div>'}${compat}`;
}

/* ================= FILES & MAPS ================= */
let MAP = null, OVERLAY = null, REGION_LAYER = null;
async function loadFiles() {
  const el = $('#files'); if (!S.folderSlug) { el.innerHTML = '<div class="banner info">Start a project to see its files.</div>'; return; }
  const token = S.filesToken = (S.filesToken || 0) + 1;  // only the newest load may redraw the page
  try {
    const [ds, tree] = await Promise.all([api(`/api/projects/${encodeURIComponent(S.folderSlug)}/datasets`), api(`/api/projects/${encodeURIComponent(S.folderSlug)}/tree`)]);
    let agol = null; try { agol = await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/agol`); } catch (e) { agol = { error: e.message }; }
    if (token !== S.filesToken) return;
    // never wipe a map the user has just opened: if the viewer is showing, keep it and refresh the rest later
    if (MAP && S.files && $('#viewer') && $('#viewer').style.display !== 'none') { S.files = { ds: ds.datasets, tree, agol }; return; }
    S.files = { ds: ds.datasets, tree, agol }; renderFiles();
  } catch (e) { el.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
}
function renderFiles() {
  const el = $('#files'), f = S.files, slug = encodeURIComponent(S.folderSlug);
  if (MAP) { MAP.remove(); MAP = null; OVERLAY = null; REGION_LAYER = null; }
  const done = f.ds.filter(d => d.state === 'completed');
  const dl = (p, label, cls = '') => `<a class="btn ${cls}" href="/api/projects/${slug}/dl?path=${encodeURIComponent(p)}" download>${label}</a>`;
  el.innerHTML = `<div class="projhead small-head"><h1>Files &amp; maps</h1><p class="purpose">Download each dataset on its own, or everything at once. Click <b>View on map</b> to check a dataset on a basemap before you use it.</p></div>
   <div class="card dlall"><div><b>${done.length}</b> dataset(s) ready</div><div class="row"><a class="btn primary big" href="/api/projects/${slug}/zip?scope=datasets" download>⬇ Download all datasets (.zip)</a>
    <a class="btn" href="/api/projects/${slug}/zip?scope=project" download>Download whole project folder (.zip)</a></div></div>
   ${agolHtml(f.agol, dl)}
   <div id="viewer" class="viewer" style="display:none"><div class="viewer-h"><b id="v_title"></b><span class="small mut" id="v_note"></span><label class="chk small"><input type="checkbox" id="v_regions"> Show regional council outlines</label><button id="v_close">Close ×</button></div><div id="mapbox"></div><div id="tablebox"></div></div>
   ${f.ds.map(d => `<div class="dfile ${d.state}"><div class="dfile-top"><div><b>${esc(d.id === 'regc' ? 'Study-area boundaries' : d.name)}</b> <span class="chip ${STATE_CLS[d.state]}">${STATE_LBL[d.state]}</span>
      <div class="small mut">${esc(d.publisher)} · ${fmtN(d.records)} records</div></div>
      <div class="row">${d.state === 'completed' ? `${d.has_geometry ? `<button class="primary" data-view="${esc(d.id)}">🗺 View on map</button>` : ''}<button data-table="${esc(d.id)}">▦ View table</button><a class="btn" href="/api/projects/${slug}/zip?scope=datasets&ds=${esc(d.id)}" download>⬇ Download this dataset (.zip)</a>` : ''}</div></div>
      ${d.files.length ? `<div class="ffiles">${d.files.map(x => `<div class="ffile"><span class="fmt">${esc(x.format)}</span><div><b>${esc(x.label)}</b><div class="small mut">${esc(x.note)} · ${fmtB(x.bytes)}</div></div>${dl(x.path, '⬇ Download')}</div>`).join('')}</div>` : '<div class="small mut">No files yet.</div>'}
      ${d.skipped_exports.map(s => `<div class="small mut">• ${esc(s.format.toUpperCase())} not created: ${esc(s.reason)}.</div>`).join('')}</div>`).join('')}
   <details style="margin-top:14px"><summary>All files in the project folder (reports, guides, metadata)</summary><div class="small mut">Folder: <code>${esc(f.tree.folder)}</code></div><ul class="treelist">${f.tree.files.map(x => `<li><a href="/api/projects/${slug}/dl?path=${encodeURIComponent(x.path)}" download>${esc(x.path)}</a> <span class="mut">${fmtB(x.bytes)}</span></li>`).join('')}</ul></details>
   <div class="actions"><button class="primary" data-go="story">Next: StoryMap plan →</button></div>`;
  $('#v_close').onclick = () => { $('#viewer').style.display = 'none'; if (MAP) { MAP.remove(); MAP = null; } };
  $('#v_regions').onchange = e => toggleRegions(e.target.checked);
  $$('[data-view]').forEach(b => b.onclick = () => viewLayer(b.dataset.view));
  $$('[data-table]').forEach(b => b.onclick = () => viewTable(b.dataset.table));
}
function agolHtml(a, dl) {
  if (!a) return '';
  if (a.error) return `<div class="card agol"><h2>🌏 Final map in ArcGIS Online</h2><div class="banner bad small">The map files could not be made: ${esc(a.error)}</div></div>`;
  const style = s => !s ? 'keep one symbol' : `Styles → <b>${esc(s.field)}</b> → ${esc(s.how)}${s.values ? ' (' + s.values.slice(0, 6).map(esc).join(', ') + ')' : ''}`;
  const ups = (a.uploads || []).filter(u => u.recommended), extra = (a.uploads || []).filter(u => !u.recommended);
  return `<div class="card agol"><h2>🌏 Final map in ArcGIS Online</h2>
   <p class="small">Works with your <b>school login</b>: the button opens Map Viewer, you sign in as usual, and the live layers appear <b>with their legends</b>. Then add the files below and press <b>Save</b>.</p>
   <div class="row">${a.mapviewer_link ? `<a class="btn primary big" href="${esc(a.mapviewer_link)}" target="_blank" rel="noopener">① Open in ArcGIS Online (${a.live_layers.length} live layer${a.live_layers.length === 1 ? '' : 's'})</a>` : '<a class="btn primary big" href="https://www.arcgis.com/apps/mapviewer/index.html" target="_blank" rel="noopener">① Open ArcGIS Online Map Viewer</a>'}
    ${dl('maps/arcgis_online_publish.md', 'Step-by-step guide')}</div>
   ${a.live_layers && a.live_layers.length ? `<div class="small mut" style="margin-top:6px">Live layers: ${a.live_layers.map(x => esc(x.name)).join(' · ')}</div>` : ''}
   ${ups.length ? `<h3 style="margin-top:12px">② Add these files (Map Viewer → Add → Add layer from file)</h3>${ups.map(u => `<div class="ffile"><span class="fmt">GEOJSON</span><div><b>${esc(u.name)}</b><div class="small mut">${fmtB(u.bytes)} · ${fmtN(u.features)} features · ${esc(u.how_to_add)}</div><div class="small">③ Legend: ${style(u.style)}</div>${u.why ? `<div class="small mut">${esc(u.why)}</div>` : ''}</div>${dl(u.file, '⬇ Download')}</div>`).join('')}` : '<div class="small mut" style="margin-top:8px">② Nothing to upload — every layer is live.</div>'}
   ${extra.length ? `<details class="small"><summary>Optional: your filtered copies of the live layers (${extra.length})</summary>${extra.map(u => `<div class="ffile"><div><b>${esc(u.name)}</b><div class="small mut">${fmtB(u.bytes)} · ${esc(u.how_to_add)}</div></div>${dl(u.file, '⬇')}</div>`).join('')}</details>` : ''}
   ${(a.notes || []).map(n => `<div class="small mut">• ${esc(n)}</div>`).join('')}
   <div class="small mut" style="margin-top:8px">④ Save the map, then Share it <b>and</b> every uploaded layer at the same level — a shared map with private layers looks blank to others.</div></div>`;
}
const propsTable = p => '<table class="pp">' + Object.entries(p || {}).slice(0, 12).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(String(v ?? ''))}</td></tr>`).join('') + '</table>';
function ensureMap() {
  if (typeof L === 'undefined') { $('#mapbox').innerHTML = '<div class="banner bad">The map library did not load. Check that static/vendor/leaflet.js exists.</div>'; return null; }
  if (MAP) { MAP.remove(); MAP = null; }
  MAP = L.map('mapbox', { preferCanvas: true }).setView([-41, 173], 5);
  const carto = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors © CARTO' });
  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' });
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Tiles © Esri' });
  carto.addTo(MAP); L.control.layers({ 'Light basemap': carto, 'OpenStreetMap': osm, 'Satellite': sat }).addTo(MAP); L.control.scale().addTo(MAP);
  return MAP;
}
function geoLayer(fc, color) {
  return L.geoJSON(fc, {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4.5, color: '#fff', weight: 1, fillColor: color, fillOpacity: .85 }),
    style: () => ({ color, weight: 2, fillColor: color, fillOpacity: .28 }),
    onEachFeature: (f, l) => l.bindPopup(propsTable(f.properties), { maxWidth: 320 }),
  });
}
async function viewLayer(ds) {
  await run('view:' + ds, async () => {
    const d = S.files.ds.find(x => x.id === ds); $('#viewer').style.display = ''; $('#tablebox').innerHTML = ''; $('#mapbox').style.display = '';
    $('#v_title').textContent = d.name; $('#v_note').textContent = 'Loading layer…'; $('#v_regions').parentElement.style.display = '';
    $('#viewer').scrollIntoView({ behavior: 'smooth', block: 'start' });
    const map = ensureMap(); if (!map) return;
    const fc = await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/layer?ds=${encodeURIComponent(ds)}`, undefined, { timeout: 180000 });
    OVERLAY = geoLayer(fc, '#e87a3d').addTo(map);
    const b = OVERLAY.getBounds(); if (b.isValid()) map.fitBounds(b.pad(0.1), { maxZoom: 12 });
    const m = fc.meta; $('#v_note').textContent = `Showing ${fmtN(m.shown)} of ${fmtN(m.with_geometry)} features with a location (${m.geometry_types.join(', ').toLowerCase()})${m.sampled || m.simplified ? ' — thinned for the browser; the files you download are complete' : ''}. Click a feature to see its attributes.`;
    setTimeout(() => { if (MAP === map) map.invalidateSize(); }, 150);
    if (!navigator.onLine) toast('You appear to be offline: the layer draws, but the basemap tiles need internet.', 'bad');
  });
}
async function toggleRegions(on) {
  if (!MAP) return;
  if (REGION_LAYER) { MAP.removeLayer(REGION_LAYER); REGION_LAYER = null; }
  if (!on) return;
  await run('regions', async () => {
    const fc = await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/layer?ds=regc`, undefined, { timeout: 180000 });
    REGION_LAYER = L.geoJSON(fc, { style: () => ({ color: '#2b7fff', weight: 1.5, fillOpacity: 0 }), onEachFeature: (f, l) => l.bindTooltip(f.properties && (f.properties.REGC2023_V1_00_NAME || ''), { sticky: true }) }).addTo(MAP);
    if (OVERLAY) OVERLAY.bringToFront();
  });
}
async function viewTable(ds) {
  await run('table:' + ds, async () => {
    const d = S.files.ds.find(x => x.id === ds); $('#viewer').style.display = ''; $('#mapbox').style.display = 'none'; $('#v_regions').parentElement.style.display = 'none';
    if (MAP) { MAP.remove(); MAP = null; }
    $('#v_title').textContent = d.name + ' — table preview'; $('#viewer').scrollIntoView({ behavior: 'smooth', block: 'start' });
    const t = await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/table?ds=${encodeURIComponent(ds)}`);
    $('#v_note').textContent = `First ${t.rows.length} of ${fmtN(t.total)} records, ${t.columns.length} columns shown.`;
    $('#tablebox').innerHTML = `<div class="tscroll"><table class="dt"><tr>${t.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${t.rows.map(r => `<tr>${r.map(v => `<td>${esc(String(v ?? ''))}</td>`).join('')}</tr>`).join('')}</table></div>`;
  });
}
