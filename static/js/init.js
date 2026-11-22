/* ===== look & feel, assistant, startup ===== */
const TODS = [['dawn', 'Dawn'], ['day', 'Day'], ['dusk', 'Dusk'], ['night', 'Night']];
function setTod(t) { document.documentElement.dataset.tod = t; const x = TODS.find(a => a[0] === t) || TODS[0]; $('#todBtn').textContent = x[1]; try { localStorage.setItem('gps_tod', t); } catch (e) { } }
(function () {
  let t = new URLSearchParams(location.search).get('tod'); try { if (!t) t = localStorage.getItem('gps_tod'); } catch (e) { }
  if (!t) { const h = new Date().getHours(); t = h < 6 || h >= 21 ? 'night' : h < 9 ? 'dawn' : h < 17 ? 'day' : 'dusk'; }
  setTod(t);
  $('#todBtn').onclick = () => { const c = document.documentElement.dataset.tod; setTod(TODS[(TODS.findIndex(a => a[0] === c) + 1) % 4][0]); };
})();

/* ---------- assistant ---------- */
function addMsg(who, text, mode, extra) {
  const d = document.createElement('div'); d.className = 'msg ' + (who === 'me' ? 'me' : ''); d.innerHTML = `<div class="m">${who === 'me' ? 'You' : 'Assistant'}${mode ? ' · ' + esc(mode) : ''}</div>`;
  const t = document.createElement('div'); t.textContent = text; d.appendChild(t);
  if (extra && extra.proposal) { const proposal = extra.proposal; const b = document.createElement('button'); b.textContent = 'Apply proposal (undo via version history)'; b.onclick = async () => { const s = S.outline.sections.find(x => x.id === proposal.section); if (!s) return; s.text = proposal.new_text; if (s.parts && s.parts[0]) s.parts[0].text = proposal.new_text; await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/storymap`, S.outline); renderStory(); b.disabled = true; }; d.appendChild(b); }
  if (extra && extra.discovery) { S.disc = extra.discovery; S.discSel = new Set(); const w = document.createElement('div'); w.className = 'assist-disc'; w.innerHTML = discHtml(extra.discovery); d.appendChild(w); d.classList.add('wide'); }
  $('#msgs').appendChild(d); $('#msgs').scrollTop = 1e9;
}
$('#a_form').onsubmit = async e => {
  e.preventDefault(); const m = $('#a_in').value.trim(); if (!m) return; $('#a_in').value = ''; addMsg('me', m);
  await run('assist', async () => {
    const pid = S.chosen ? S.chosen.id : (S.jobData ? S.jobData.project_id : null);
    try {
      const r = await api('/api/assistant', { message: m, job_id: S.job, section: S.sec, project_id: pid || undefined, region: (S.chosen && S.chosen.region) || undefined, ...periodBody() }, { timeout: 150000 });
      addMsg('a', r.reply, r.mode, r); $('#a_mode').textContent = r.mode ? '· ' + r.mode : '';
    } catch (err) { addMsg('a', 'Error: ' + err.message); }
  });
};
function toggleAssist(force) { const a = $('#assist'), on = force === undefined ? !a.classList.contains('open') : force; a.classList.toggle('open', on); $('#fab').setAttribute('aria-expanded', on); if (on) $('#a_in').focus(); }
function helpProject() { return S.chosen ? S.chosen.id : (S.jobData ? S.jobData.project_id : null); }
$('#hb_trouble').onclick = async () => {
  const id = helpProject(); if (!id) { toast('Choose a project first (Projects tab), then press Troubleshoot.', 'bad'); return; }
  await troubleshootProject(id); S.open = true; showTab('projects'); renderFeed(); toast('Troubleshoot results are on the project card.');
};
$('#hb_find').onclick = () => {
  if (!helpProject()) { toast('Choose a project first (Projects tab), then search for other data.', 'bad'); return; }
  toggleAssist(true); $('#a_in').value = 'identify gaps'; $('#a_form').requestSubmit();
};
$('#projBtn').onclick = () => { showTab('projects'); S.open = true; renderFeed(); };
$('#toggleAssist').onclick = $('#fab').onclick = () => toggleAssist(); $('#a_close').onclick = () => toggleAssist(false);
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if ($('#assist').classList.contains('open')) toggleAssist(false);
  else if (!$('#setPanel').hidden) toggleSettings(false);
  else if (S.open && S.tab === 'projects') { S.open = false; renderFeed(); }
});

/* ---------- startup ---------- */
(async function init() {
  try {
    const st = await api('/api/state');
    S.settings = st.settings; S.refresh = st.refresh; S.regions = st.regions; S.periods = st.periods; S.period.preset = st.default_period;
    buildFilters(); bindSettings();
    $('#s_root').value = st.settings.project_root; $('#s_max').value = st.settings.max_file_mb; $('#s_stall').value = st.settings.stall_seconds; $('#s_sched').value = st.settings.schedule_minutes;
    $('#hstatus').textContent = 'backend connected · v' + st.version;
    $('#caps').innerHTML = `Fast point-in-polygon (shapely): ${st.capabilities.shapely ? 'yes' : 'no (pure Python, slower on large files)'}<br>Claude API key on backend: ${st.capabilities.claude_api_key ? 'yes (untested integration)' : 'no — the assistant uses built-in answers and the dataset finder only'}`;
    if (st.version !== EXPECT_VERSION) $('#verwarn').innerHTML = `<div class="banner bad">Your server is running OLD code (v${esc(st.version)}) but this page is v${EXPECT_VERSION}. Close the terminal window running server.py (or press Ctrl+C in it), start it again with <code>py server.py</code>, then press Ctrl+F5. Until then the project list will look wrong.</div>`;
    await updatePeriod(); await loadFeed();
    try {
      S.jobs = (await api('/api/jobs')).jobs;
      if (S.jobs.length) { S.job = S.jobs[0].id; const j = await api('/api/jobs/' + S.job); onJob(j); S.lastStatus = j.status; if (jobBusy(j)) startPolling(); }
    } catch (e) { }
    if (S.refresh.state === 'running') pollRefresh();
    const h = location.hash.replace('#', ''); showTab(['projects', 'project', 'progress', 'quality', 'files', 'story'].includes(h) && tabEnabled(h) ? h : 'projects');
    addMsg('a', 'Try “find missing datasets about rainfall”, “identify gaps”, or “explain the datasets”. I search real catalogues and never invent sources or sizes.', 'built-in (no AI)');
  } catch (e) { $('#hstatus').textContent = 'backend not reachable: ' + e.message; }
})();
