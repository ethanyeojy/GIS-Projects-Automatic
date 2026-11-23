/* ===== core: helpers, state, API, time period, filters, settings panel, navigation ===== */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const EXPECT_VERSION = '0.2.0';
const THEME_LBL = { hazards: 'Natural hazards', freshwater: 'Freshwater', wildlife: 'Wildlife', outdoors: 'Outdoors', marine: 'Marine', weather: 'Weather', climate: 'Climate', environment: 'Other environmental factors' };
const THEME_COL = { hazards: '#e0653a', freshwater: '#2e86de', wildlife: '#3aa760', outdoors: '#b8863b', marine: '#17a2b8', weather: '#6c5ce7', climate: '#d6336c', environment: '#2f9e8f' };
const DIFFS = ['Beginner', 'Intermediate', 'Advanced'];
const defaultFilters = () => ({ themes: Object.keys(THEME_LBL), diffs: DIFFS.slice(), hours: 20, period: '', dtype: '', region: '', hideOver: true });

const S = {
  feed: [], regions: [], periods: [], refresh: {}, settings: {}, filters: defaultFilters(),
  period: { preset: '10y', start: '', end: '' }, periodInfo: null, periodError: '',
  open: true, tab: 'projects', chosen: null, plan: null, sel: {}, extras: [], disc: null,
  job: null, jobs: [], jobData: null, folderSlug: null, trouble: {}, taskTrouble: {}, expanded: new Set(), busy: {}, offset: 0,
  files: null, outline: null, sec: null, pollTimer: null, lastStatus: null, view: 'preview', mapDs: null,
};

/* ---------- API: every call has a time limit, so a hung request can never leave a button stuck */
const inflight = {};
async function api(path, body, opt = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), opt.timeout ?? 120000);
  const o = body === undefined ? { signal: ctl.signal } : { method: 'POST', headers: { 'X-GPS': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal };
  try {
    const r = await fetch(path, o);
    const j = await r.json().catch(() => ({ error: 'bad response' }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('The server took too long to answer (over ' + Math.round((opt.timeout ?? 120000) / 1000) + ' s). Nothing is lost — try again, or use Troubleshoot.');
    throw e;
  } finally { clearTimeout(timer); }
}
/* run(key, fn): one action per key at a time, but a repeat click after a few seconds simply starts again (never "stuck"). */
async function run(key, fn) {
  const now = Date.now();
  if (S.busy[key] && now - S.busy[key] < 3000) return;
  S.busy[key] = now;
  try { return await fn(); }
  catch (e) { toast(e.message, 'bad'); }
  finally { if (S.busy[key] === now) delete S.busy[key]; }
}
const isBusy = k => !!S.busy[k];

function toast(msg, kind = '') {
  const t = $('#toast'); const d = document.createElement('div'); d.className = 'toast ' + kind; d.textContent = msg; t.appendChild(d);
  setTimeout(() => d.classList.add('out'), kind === 'bad' ? 7000 : 3800); setTimeout(() => d.remove(), kind === 'bad' ? 7600 : 4400);
}
const fmtB = b => b == null ? 'unknown' : b >= 1e9 ? (b / 1e9).toFixed(2) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : b >= 1e3 ? Math.round(b / 1e3) + ' kB' : b + ' B';
const fmtN = n => n == null ? 'unknown' : Number(n).toLocaleString();
const ago = s => s < 2 ? 'just now' : s < 90 ? Math.round(s) + ' s ago' : s < 5400 ? Math.round(s / 60) + ' min ago' : Math.round(s / 3600) + ' h ago';
const nowSrv = () => Date.now() / 1000 + S.offset;

/* ---------- time period ---------- */
const periodBody = () => ({ preset: S.period.preset, start: S.period.start || undefined, end: S.period.end || undefined });
const periodQuery = () => new URLSearchParams({ preset: S.period.preset, ...(S.period.start ? { start: S.period.start } : {}), ...(S.period.end ? { end: S.period.end } : {}) }).toString();
async function updatePeriod() {
  try { S.periodInfo = await api('/api/period?' + periodQuery()); S.periodError = ''; }
  catch (e) { S.periodInfo = null; S.periodError = e.message; }
  renderPeriod();
}
function renderPeriod() {
  const p = S.periodInfo;
  $('#t_custom').style.display = S.period.preset === 'custom' ? '' : 'none';
  $('#t_text').innerHTML = S.periodError ? `<span class="bad">⚠ ${esc(S.periodError)}</span>` :
    p ? `<b>${esc(p.label)}</b><br><span class="dates">${esc(p.start)} → ${esc(p.end)}</span> <span class="mut small">(${Number(p.days).toLocaleString()} days)</span>` : '…';
  renderSummary();
}

/* ---------- filters ---------- */
const FILTERS = [
  ['theme', (p, f) => f.themes.includes(p.theme)], ['difficulty', (p, f) => f.diffs.includes(p.difficulty)],
  ['workload', (p, f) => p.workload_h[1] <= f.hours], ['time period', (p, f) => !f.period || p.period_class === f.period],
  ['data type', (p, f) => !f.dtype || p.data_type === f.dtype],
  ['file size', (p, f) => !f.hideOver || p.possible !== false]];
const passes = p => FILTERS.every(([, fn]) => fn(p, S.filters));
function buildFilters() {
  const f = S.filters;
  $('#f_region').innerHTML = '<option value="">New Zealand-wide</option>' + S.regions.map(r => `<option ${r === f.region ? 'selected' : ''}>${esc(r)}</option>`).join('');
  $('#f_theme').innerHTML = Object.keys(THEME_LBL).map(t => `<label class="pill"><input type="checkbox" data-th="${t}"> ${esc(THEME_LBL[t])}</label>`).join('');
  $('#f_diff').innerHTML = DIFFS.map(t => `<label class="pill"><input type="checkbox" data-df="${t}"> ${t}</label>`).join('');
  $$('[data-th]').forEach(c => { c.checked = f.themes.includes(c.dataset.th); c.onchange = () => { f.themes = $$('[data-th]').filter(x => x.checked).map(x => x.dataset.th); onFilters(); }; });
  $$('[data-df]').forEach(c => { c.checked = f.diffs.includes(c.dataset.df); c.onchange = () => { f.diffs = $$('[data-df]').filter(x => x.checked).map(x => x.dataset.df); onFilters(); }; });
  const bind = (id, key, num) => { const el = $(id); el.value = f[key]; el.oninput = el.onchange = () => { f[key] = num ? +el.value : el.value; if (key === 'hours') $('#f_hours_v').textContent = f.hours; onFilters(); }; };
  const ov = $('#f_over'); ov.checked = f.hideOver; ov.onchange = () => { f.hideOver = ov.checked; onFilters(); };
  bind('#f_hours', 'hours', 1); bind('#f_dtype', 'dtype'); bind('#f_period', 'period'); bind('#f_region', 'region');
  $('#f_hours_v').textContent = f.hours;
}
function resetFilters() { S.filters = defaultFilters(); buildFilters(); onFilters(); }
function onFilters() { renderSummary(); if (S.feed.length) renderFeed(); }
function renderSummary() {
  const f = S.filters, all = S.feed.length, n = S.feed.filter(passes).length;
  const per = S.periodInfo ? S.periodInfo.label : '…';
  $('#setSummary').textContent = `· ${per} · ${f.region || 'NZ-wide'}` + (all ? ` · ${n}/${all} projects` : '');
}

/* ---------- collapsible Settings / Filters panel (top navigation) ---------- */
function toggleSettings(force) {
  const p = $('#setPanel'), open = force === undefined ? p.hidden : force;
  p.hidden = !open; $('#setBtn').setAttribute('aria-expanded', open); $('#setBtn').classList.toggle('on', open);
}
function bindSettings() {
  $('#t_preset').innerHTML = S.periods.map(p => `<option value="${p.id}">${esc(p.label)}</option>`).join('');
  $('#t_preset').value = S.period.preset;
  $('#t_preset').onchange = () => {
    S.period.preset = $('#t_preset').value;
    $('#t_custom').style.display = S.period.preset === 'custom' ? '' : 'none';  // show/hide the date pickers straight away
    if (S.period.preset === 'custom' && !S.period.start) { S.period.start = $('#t_start').value = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10); S.period.end = $('#t_end').value = new Date().toISOString().slice(0, 10); }
    onPeriodChanged();
  };
  $('#t_start').onchange = $('#t_end').onchange = () => { S.period.start = $('#t_start').value; S.period.end = $('#t_end').value; onPeriodChanged(); };
  $('#s_save').onclick = () => run('save-settings', async () => {
    const r = await api('/api/settings', { project_root: $('#s_root').value, max_file_mb: +$('#s_max').value, stall_seconds: +$('#s_stall').value, schedule_minutes: +$('#s_sched').value });
    S.settings = r.settings; $('#s_msg').textContent = 'Saved ✓'; setTimeout(() => $('#s_msg').textContent = '', 2500); toast('Settings saved.');
  });
  $('#f_reset').onclick = () => { resetFilters(); toast('All filters reset — every project is shown.'); };
  $('#setBtn').onclick = () => toggleSettings();
}
async function onPeriodChanged() {
  await updatePeriod();
  if (S.periodError) return;
  try { const j = await api('/api/feed?' + periodQuery()); S.feed = j.projects; renderFeed(); } catch (e) { toast(e.message, 'bad'); }
  if (S.chosen && S.tab === 'project') toast('Time period changed — press “Re-check datasets for this period” on the Project tab.');
}

/* ---------- navigation ---------- */
const STEPS = [
  ['projects', 'Projects', 'Pick an idea from the cards on the right.'],
  ['project', 'Project', 'Review the question, filter each dataset and choose what to download.'],
  ['progress', 'Progress', 'Watching the downloads. This moves on to Quality by itself when they finish.'],
  ['quality', 'Quality', 'A plain-language check of what was downloaded.'],
  ['files', 'Files & maps', 'Download each dataset, or everything, and look at them on a map.'],
  ['story', 'StoryMap plan', 'A draft case study laid out like an ArcGIS StoryMap.']];
function tabEnabled(t) {
  if (t === 'projects') return true;
  if (t === 'project') return !!S.chosen;
  if (t === 'story') return !!(S.chosen || S.job);  // a rough outlook is available as soon as a project is chosen
  return !!S.job;
}
function showTab(t) {
  if (!tabEnabled(t)) { toast('Choose a project first (Projects tab).'); t = 'projects'; }
  S.tab = t;
  $$('.tab').forEach(x => { x.classList.toggle('on', x.dataset.t === t); x.classList.toggle('dim', !tabEnabled(x.dataset.t)); });
  $$('.pane').forEach(x => x.classList.toggle('on', x.id === 'p_' + t));
  renderStageBar();
  if (S.feed.length) renderFeed();
  if (t === 'project') renderProject();
  if (t === 'progress') renderProgress();
  if (t === 'quality') renderQuality();
  if (t === 'files') loadFiles();
  if (t === 'story') loadStory();
  window.scrollTo({ top: 0 });
}
function renderStageBar() {
  const i = STEPS.findIndex(s => s[0] === S.tab), s = STEPS[i];
  const j = S.jobData;
  $('#stagebar').innerHTML = `<div class="stagebar"><span class="stepno">Step ${i + 1} of ${STEPS.length}</span><b>${esc(s[1])}</b><span class="mut small"> — ${esc(s[2])}</span>
   ${S.chosen && i > 0 ? `<span class="sbproj">${esc(projById(S.chosen.id)?.title || '')}</span>` : ''}</div>`;
}
const projById = id => S.feed.find(p => p.id === id) || null;
$$('.tab').forEach(b => b.onclick = () => showTab(b.dataset.t));
