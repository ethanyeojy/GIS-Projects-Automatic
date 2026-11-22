/* ===== StoryMap plan: draft case study laid out like an ArcGIS StoryMap, with labelled ILLUSTRATIONS ===== */

/* ---------- illustrative New Zealand outline (hand-simplified; for mock-ups only) ---------- */
const NZ_NI = [[172.65, -34.45], [173.4, -34.5], [174.15, -35.15], [174.6, -36.0], [174.8, -36.45], [175.4, -36.6], [175.5, -37.1], [175.9, -36.9], [175.95, -37.45], [176.6, -37.65], [177.15, -37.95], [177.95, -37.7], [178.55, -37.7], [178.3, -38.6], [177.9, -39.15], [177.05, -39.65], [176.6, -40.3], [176.2, -41.1], [175.8, -41.45], [175.25, -41.6], [174.85, -41.35], [175.15, -40.75], [175.0, -40.3], [174.85, -39.9], [174.3, -39.6], [173.85, -39.25], [174.2, -38.95], [174.65, -38.3], [174.8, -37.8], [174.75, -37.25], [174.55, -36.95], [174.4, -36.35], [174.1, -35.6], [173.45, -35.0], [172.95, -34.6]];
const NZ_SI = [[172.7, -40.5], [173.4, -40.95], [173.85, -41.25], [174.15, -41.25], [173.95, -41.55], [174.15, -41.7], [173.7, -42.4], [173.2, -42.95], [172.7, -43.5], [173.1, -43.8], [172.2, -43.9], [171.4, -44.35], [170.85, -45.0], [170.7, -45.8], [169.6, -46.55], [168.4, -46.65], [167.5, -46.2], [166.6, -45.9], [166.8, -45.2], [167.4, -44.5], [168.4, -43.9], [169.2, -43.5], [170.3, -43.0], [171.0, -42.7], [171.5, -42.2], [171.6, -41.75], [172.1, -40.95]];
const MW = 270, MH = 350, KX = Math.cos(40.5 * Math.PI / 180) * 26, KY = 26;
const mp = ([lon, lat]) => [(lon - 166) * KX, (-34.2 - lat) * KY];
const NZ_PTS = [NZ_NI.map(mp), NZ_SI.map(mp)];
const polyD = p => 'M' + p.map(([x, y]) => x.toFixed(1) + ',' + y.toFixed(1)).join('L') + 'Z';
function inPoly(x, y, p) { let c = false; for (let i = 0, j = p.length - 1; i < p.length; j = i++) { const [xi, yi] = p[i], [xj, yj] = p[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; }
const onLand = (x, y) => NZ_PTS.some(p => inPoly(x, y, p));
function rng(seed) { let h = 1779033703 ^ seed.length; for (let i = 0; i < seed.length; i++) { h = Math.imul(h ^ seed.charCodeAt(i), 3432918353); h = h << 13 | h >>> 19; } let a = h >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

function landPts(r, n, clusters) {
  const out = [], cs = []; while (cs.length < clusters) { const x = r() * MW, y = r() * MH; if (onLand(x, y)) cs.push([x, y]); }
  let guard = 0; while (out.length < n && guard++ < n * 60) { const c = cs[Math.floor(r() * cs.length)], x = c[0] + (r() - .5) * 70, y = c[1] + (r() - .5) * 90; if (onLand(x, y)) out.push([x, y]); }
  return out;
}
function mockMap(style, seed, opt = {}) {
  const r = rng(seed + style), id = 'm' + Math.floor(r() * 1e8);
  const land = NZ_PTS.map(p => `<path d="${polyD(p)}" fill="#e3e8da" stroke="#9aab8a" stroke-width="1.2"/>`).join('');
  const clip = `<clipPath id="${id}"><path d="${NZ_PTS.map(polyD).join(' ')}"/></clipPath>`;
  let layer = '', legend = '';
  if (style === 'points') {
    layer = landPts(r, 70, 4).map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(2 + r() * 3.2).toFixed(1)}" fill="#e0653a" fill-opacity=".72" stroke="#fff" stroke-width=".6"/>`).join('');
    legend = [['#e0653a', 'Records (size = value)']];
  } else if (style === 'lines') {
    for (let k = 0; k < 7; k++) { let [x, y] = landPts(r, 1, 1)[0] || [100, 100], d = 'M' + x + ',' + y; for (let s = 0; s < 9; s++) { x += (r() - .5) * 26; y += (r() - .2) * 22; d += 'L' + x.toFixed(1) + ',' + y.toFixed(1); } layer += `<path d="${d}" fill="none" stroke="#2e86de" stroke-width="${(1 + r() * 1.6).toFixed(1)}" stroke-linecap="round" clip-path="url(#${id})"/>`; }
    legend = [['#2e86de', 'Lines (tracks / rivers)']];
  } else if (style === 'polygons') {
    for (let k = 0; k < 6; k++) { const [x, y] = landPts(r, 1, 1)[0] || [100, 100], rr = 14 + r() * 26; let d = ''; for (let a = 0; a < 9; a++) { const ang = a / 9 * 6.283, rad = rr * (0.7 + r() * .6); d += (a ? 'L' : 'M') + (x + Math.cos(ang) * rad).toFixed(1) + ',' + (y + Math.sin(ang) * rad).toFixed(1); } layer += `<path d="${d}Z" fill="#3aa760" fill-opacity=".42" stroke="#2c7a48" stroke-width="1" clip-path="url(#${id})"/>`; }
    legend = [['#3aa760', 'Areas (zones / extents)']];
  } else {  // choropleth: shaded grid cells (stand-in for regions)
    const pal = ['#d6e6f7', '#a9c9ec', '#6fa3d8', '#3b78b8', '#1f4f86']; let cells = '';
    for (let gx = 0; gx < 6; gx++) for (let gy = 0; gy < 8; gy++) cells += `<rect x="${gx * 45}" y="${gy * 44}" width="45" height="44" fill="${pal[Math.floor(r() * 5)]}" stroke="#fff" stroke-width="1.2"/>`;
    layer = `<g clip-path="url(#${id})">${cells}</g>`; legend = pal.map((c, i) => [c, i === 0 ? 'Low' : i === 4 ? 'High' : '']);
  }
  const lg = Array.isArray(legend[0]) ? legend.map(([c, t], i) => `<rect x="8" y="${MH - 16 - (legend.length - 1 - i) * 13}" width="11" height="9" fill="${c}"/><text x="24" y="${MH - 8 - (legend.length - 1 - i) * 13}" font-size="8" fill="#334">${t}</text>`).join('') : '';
  const slider = opt.time ? `<g><rect x="20" y="${MH - 6}" width="${MW - 40}" height="4" rx="2" fill="#ccd"/><rect x="20" y="${MH - 6}" width="${(MW - 40) * .62}" height="4" rx="2" fill="#0e7c72"/><circle cx="${20 + (MW - 40) * .62}" cy="${MH - 4}" r="6" fill="#fff" stroke="#0e7c72" stroke-width="2"/></g>` : '';
  return `<svg class="mocksvg" viewBox="0 0 ${MW} ${MH + (opt.time ? 10 : 0)}" role="img" aria-label="Illustration of a ${style} map of New Zealand"><defs>${clip}<linearGradient id="sea${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#cfe3f1"/><stop offset="1" stop-color="#b5d1e6"/></linearGradient></defs>
    <rect width="${MW}" height="${MH + (opt.time ? 10 : 0)}" fill="url(#sea${id})"/>${[1, 2, 3, 4].map(i => `<line x1="0" y1="${i * 70}" x2="${MW}" y2="${i * 70}" stroke="#fff" stroke-opacity=".35"/>`).join('')}${land}${layer}${lg}
    <g transform="translate(${MW - 22},22)"><path d="M0,-12 L5,4 L0,0 L-5,4Z" fill="#334"/><text y="16" text-anchor="middle" font-size="8" fill="#334">N</text></g>${slider}</svg>`;
}
function mockChart(kind, seed) {
  const r = rng(seed + kind), W = 320, H = 190, L0 = 34, B = H - 26, T = 14, R = W - 12;
  let g = `<line x1="${L0}" y1="${B}" x2="${R}" y2="${B}" stroke="#889"/><line x1="${L0}" y1="${T}" x2="${L0}" y2="${B}" stroke="#889"/>` + [1, 2, 3].map(i => `<line x1="${L0}" y1="${B - i * (B - T) / 4}" x2="${R}" y2="${B - i * (B - T) / 4}" stroke="#dde" />`).join('');
  const n = kind === 'histogram' ? 12 : kind === 'line' ? 24 : 8, bw = (R - L0) / n;
  if (kind === 'line') { let y = 40 + r() * 50, d = ''; for (let i = 0; i < n; i++) { y = Math.max(14, Math.min(B - 10, y + (r() - .5) * 38)); d += (i ? 'L' : 'M') + (L0 + 6 + i * (R - L0 - 12) / (n - 1)).toFixed(1) + ',' + (B - y).toFixed(1); } g += `<path d="${d}" fill="none" stroke="#0e7c72" stroke-width="2.4"/>`; }
  else if (kind === 'stacked') for (let i = 0; i < n; i++) { let y = B; ['#0e7c72', '#e87a3d', '#6c5ce7'].forEach(c => { const h = 12 + r() * 36; y -= h; g += `<rect x="${L0 + i * bw + 4}" y="${y.toFixed(1)}" width="${bw - 8}" height="${h.toFixed(1)}" fill="${c}"/>`; }); }
  else for (let i = 0; i < n; i++) { const h = kind === 'histogram' ? (B - T) * Math.exp(-Math.pow((i - n * .3) / (n * .28), 2)) * (.75 + r() * .25) : 18 + r() * (B - T - 26); g += `<rect x="${L0 + i * bw + (kind === 'histogram' ? 1 : 5)}" y="${(B - h).toFixed(1)}" width="${bw - (kind === 'histogram' ? 2 : 10)}" height="${h.toFixed(1)}" fill="${kind === 'bar' ? '#2e86de' : '#0e7c72'}" fill-opacity=".85"/>`; }
  return `<svg class="mocksvg chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Illustration of a ${kind} chart"><rect width="${W}" height="${H}" fill="#fff" fill-opacity=".7"/>${g}<text x="${W / 2}" y="${H - 6}" text-anchor="middle" font-size="9" fill="#667">${kind === 'line' ? 'time →' : 'category →'}</text><text transform="translate(10,${H / 2}) rotate(-90)" text-anchor="middle" font-size="9" fill="#667">value →</text></svg>`;
}
function mockTable(m) {
  const real = m.data && m.data.length;
  const rows = real ? m.data.slice(0, 8) : Array.from({ length: m.rows || 4 }, (_, i) => m.columns.map((c, j) => null));
  return `<div class="tscroll"><table class="dt mock"><tr>${m.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${rows.map(r => `<tr>${r.map((v, j) => `<td>${v == null ? `<i class="skel" style="width:${50 + ((j * 37) % 40)}%"></i>` : esc(String(v))}</td>`).join('')}</tr>`).join('')}</table></div>`;
}
function mockTimeline(m) {
  return `<div class="mtl">${m.steps.map((s, i) => `<div class="mtl-i ${i < m.done ? 'done' : ''}"><i>${i < m.done ? '✓' : i + 1}</i><span>${esc(s)}</span></div>`).join('')}</div>`;
}
function mockSwipe(seed) {
  const a = mockMap('polygons', seed + 'A'), b = mockMap('points', seed + 'B');
  return `<div class="mswipe"><div class="mswipe-a">${a}</div><div class="mswipe-b">${b}</div><div class="mswipe-h"><span>◀ ▶</span></div><div class="mswipe-l l1">Layer A</div><div class="mswipe-l l2">Layer B</div></div>`;
}
function visualHtml(v, seed) {
  const badge = t => `<div class="mock-badge">ILLUSTRATION · ${t} — not real data</div>`;
  const cap = `<figcaption>${esc(v.label)}${v.mock && v.mock.note ? ' — <i>' + esc(v.mock.note) + '</i>' : ''}</figcaption>`;
  if (v.kind === 'map') return `<figure class="mock">${badge('map')}${mockMap(v.mock.style, seed + v.label)}${cap}</figure>`;
  if (v.kind === 'timeseries') return `<figure class="mock">${badge('time-series map')}<div class="tsplay"><span>▶</span><span class="mut small">Time slider</span></div>${mockMap(v.mock.style, seed + 'ts', { time: true })}${cap}</figure>`;
  if (v.kind === 'chart') return `<figure class="mock">${badge('chart')}${mockChart(v.mock.chart, seed + v.label)}${cap}</figure>`;
  if (v.kind === 'table') return `<figure class="mock wide">${v.mock.real ? '<div class="mock-badge real">REAL dataset information</div>' : badge('table layout')}${mockTable(v.mock)}${cap}</figure>`;
  if (v.kind === 'timeline') return `<figure class="mock wide">${badge('timeline')}${mockTimeline(v.mock)}${cap}</figure>`;
  return '';
}

/* ---------- loading + rendering ---------- */
async function loadStory() {
  const el = $('#story');
  const useJob = S.folderSlug && (!S.chosen || (S.jobData && (S.jobData.project_id === S.chosen.id)));
  if (!useJob) {  // no download yet for this project: show the rough outlook so you can see what it will look like
    if (!S.chosen) { el.innerHTML = '<div class="banner info">Choose a project first.</div>'; return; }
    el.innerHTML = '<div class="banner info">Preparing the rough outlook…</div>';
    try {
      const q = new URLSearchParams({ project_id: S.chosen.id, preset: S.period.preset, ...(S.period.start ? { start: S.period.start } : {}), ...(S.period.end ? { end: S.period.end } : {}), ...(S.chosen.region ? { region: S.chosen.region } : {}) });
      const d = await api('/api/outlook?' + q.toString(), undefined, { timeout: 60000 });
      el.innerHTML = `<div class="projhead small-head"><h1>StoryMap plan — rough outlook</h1><div class="bigq"><span class="bq-label">Main research question</span>${esc(d.question)}</div></div>
        <div class="banner small"><b>This is a rough outlook, before any download.</b> It shows how the finished story could be laid out (ArcGIS StoryMaps blocks, photos, and labelled illustrations). Download the datasets to unlock the editable draft with your real dataset information.
        <div class="actions"><button class="primary" data-go="project">Back to the project to review datasets →</button></div></div><div class="smap">${smPreview(d)}</div>`;
    } catch (e) { el.innerHTML = `<div class="banner bad">Couldn't build the outlook: ${esc(e.message)}</div>`; }
    return;
  }
  try { S.outline = await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/storymap`); } catch (e) { S.outline = null; }
  renderStory();
}
const imgUrl = f => /^https?:/.test(f) ? f : `/api/projects/${encodeURIComponent(S.folderSlug)}/img?path=${encodeURIComponent(f)}`;
const partCls = t => /^\s*\[/.test(t) ? 'prompt' : '';
function normSections(o) { o.sections.forEach(s => { if (!s.parts) s.parts = [{ label: 'Text', text: s.text || '' }]; s.visuals = s.visuals || []; s.layout = s.layout || 'text'; }); return o; }
function partsHtml(s) {
  return s.parts.filter(p => p.text && p.text.trim()).map(p => `<div class="sm-part ${partCls(p.text)}"><div class="sm-plabel">${esc(p.label)}</div>${p.text.split('\n').map(l => l.startsWith('- ') ? `<li>${esc(l.slice(2))}</li>` : `<p>${esc(l)}</p>`).join('').replace(/(<li>.*?<\/li>)+/gs, m => `<ul>${m}</ul>`)}</div>`).join('');
}
function smPreview(o) {
  normSections(o);
  const ims = id => o.images.filter(im => im.section === id && im.file);
  const seed = o.title || 'x';
  const vis = s => s.visuals.filter(v => v.kind !== 'image').map(v => visualHtml(v, seed)).join('');
  return o.sections.map(s => {
    const im = ims(s.id)[0], parts = partsHtml(s), v = vis(s);
    const photo = im ? `<figure class="sm-photo"><img src="${imgUrl(im.file)}" alt="${esc(im.alt)}" loading="lazy"><figcaption>Photo: ${esc(im.credit)}</figcaption></figure>` : '';
    const head = `<div class="sm-tag">${esc(s.layout.replace(/-/g, ' '))} block</div>`;
    if (s.layout === 'cover') { const c = ims('cover')[0]; return `<header class="sm-cover" ${c ? `style="background-image:linear-gradient(rgba(0,0,0,.2),rgba(0,0,0,.62)),url('${imgUrl(c.file)}')"` : ''}><h1>${esc(s.parts[0].text)}</h1><div class="sub">${esc(s.parts[1] ? s.parts[1].text : '')}</div>${c ? `<small>Photo: ${esc(c.credit)}</small>` : ''}</header>`; }
    if (s.layout === 'immersive') { const c = ims('intro')[0] || ims('q1')[0]; return `<section class="sm-imm" ${c ? `style="background-image:linear-gradient(rgba(0,0,0,.35),rgba(0,0,0,.35)),url('${imgUrl(c.file)}')"` : ''}><div class="sm-card">${head}<h2>${esc(s.title)}</h2>${parts}</div>${c ? `<small class="cred">Photo: ${esc(c.credit)}</small>` : ''}</section>`; }
    if (s.layout === 'callout') return `<section class="sm-callout">${head}<blockquote>${esc(s.parts[0].text)}</blockquote>${s.parts[1] ? `<p>${esc(s.parts[1].text)}</p>` : ''}</section>`;
    if (s.layout === 'timeline') return `<section class="sm-sec">${head}<h2>${esc(s.title)}</h2>${v}<div class="sm-cols">${parts}</div></section>`;
    if (s.layout === 'table') return `<section class="sm-sec">${head}<h2>${esc(s.title)}</h2><div class="sm-cols two">${parts}</div>${v}</section>`;
    if (s.layout === 'sidecar-right') return `<section class="sm-sec sidecar">${head}<h2>${esc(s.title)}</h2><div class="sm-side"><div class="sm-media">${v}${photo}</div><div class="sm-narr">${parts}</div></div></section>`;
    if (s.layout === 'sidecar-stack') return `<section class="sm-sec sidecar">${head}<h2>${esc(s.title)}</h2><div class="sm-side flip"><div class="sm-narr">${parts}</div><div class="sm-media stack">${v}${photo}</div></div></section>`;
    if (s.layout === 'swipe') return `<section class="sm-sec">${head}<h2>${esc(s.title)}</h2><div class="sm-side"><div class="sm-media"><figure class="mock"><div class="mock-badge">ILLUSTRATION · swipe — not real data</div>${mockSwipe(seed + s.id)}<figcaption>Swipe to compare two layers</figcaption></figure>${v}${photo}</div><div class="sm-narr">${parts}</div></div></section>`;
    if (s.layout === 'sidecar-down') return `<section class="sm-sec down">${head}<h2>${esc(s.title)}</h2><div class="sm-bg">${v || photo}</div><div class="sm-over">${parts}</div></section>`;
    return `<section class="sm-sec">${head}<h2>${esc(s.title)}</h2><div class="sm-cols">${parts}</div>${v}${photo}</section>`;
  }).join('');
}
const secMd = s => `## ${s.title}\n\n` + (s.parts || [{ label: '', text: s.text }]).map(p => `**${p.label}**\n\n${(p.text || '').trim()}\n`).join('\n');
async function renderStory() {
  const el = $('#story'), o = S.outline;
  if (!o) { el.innerHTML = '<div class="banner info">The draft is not available yet (the package is still being built, or this project failed).</div>'; return; }
  normSections(o);
  let vers = []; try { vers = (await api(`/api/projects/${encodeURIComponent(S.folderSlug)}/storymap/versions`)).versions; } catch (e) { }
  const slug = encodeURIComponent(S.folderSlug), edit = S.view === 'edit';
  el.innerHTML = `<div class="projhead small-head"><h1>StoryMap plan</h1><div class="bigq"><span class="bq-label">Main research question</span>${esc(o.question || '')}</div></div>
   <div class="banner small"><b>This is a draft to make your own.</b> It is laid out like an ArcGIS StoryMap so you can copy the structure and wording. Maps, charts and tables are <b>labelled illustrations</b> of what they could look like — build the real ones from your own analysis. The text says what was done and what is planned; findings are left as <b>[prompts]</b> for you to write. Please edit it in your own words and follow your course's rules on using AI help.</div>
   <div class="row toolbar"><div class="seg"><button class="${edit ? '' : 'on'}" data-sview="preview">StoryMaps preview</button><button class="${edit ? 'on' : ''}" data-sview="edit">Edit text</button></div>
    <button class="primary" id="ssave">Save (creates a version)</button><button id="scopyall">Copy all text</button>
    <select id="svers"><option value="">Version history (${vers.length})…</option>${vers.map(v => `<option value="${v.id}">${esc(v.id)} · ${esc((v.saved_at || '').slice(0, 19))} · ${esc(v.note)}</option>`).join('')}</select><button id="srestore">Restore</button></div>
   ${edit ? `<div id="sbody">${o.sections.map((s, i) => `<div class="sec"><div class="row between"><b>${esc(s.title)}</b><span class="chip">${esc(s.layout.replace(/-/g, ' '))}</span></div>
      ${s.parts.map((p, k) => `<label class="plabel">${esc(p.label)}<textarea data-i="${i}" data-k="${k}" rows="${Math.min(9, Math.max(2, Math.ceil((p.text || '').length / 90)))}">${esc(p.text)}</textarea></label>`).join('')}
      <div class="small mut">StoryMaps tip: ${esc(s.suggest || '')}</div>
      ${s.visuals.filter(v => v.kind !== 'image').map(v => `<div class="ph">${{ map: '🗺️', chart: '📊', table: '▦', timeline: '⏱', timeseries: '🕒' }[v.kind] || ''} ${esc(v.kind)} placeholder: ${esc(v.label)}<small>Build this from your own analysis; the Preview shows an illustration of how it could look.</small></div>`).join('')}
      ${o.images.filter(im => im.section === s.id).map(im => `<figure class="fig">${im.file ? `<img class="simg" src="${imgUrl(im.file)}" alt="${esc(im.alt)}" loading="lazy">` : `<div class="ph">Photo not downloaded — <a href="${esc(im.source_page)}" target="_blank" rel="noopener">open source page</a></div>`}<figcaption class="small">${esc(im.caption || '')} · <b>Credit:</b> ${esc(im.credit || '—')} ${im.source_page ? `· <a href="${esc(im.source_page)}" target="_blank" rel="noopener">source</a>` : ''}</figcaption></figure>`).join('')}
      <button class="scopy" data-copy="${i}">Copy this section</button></div>`).join('')}
     <div class="card"><b>Add your own image</b> <span class="small mut">(the original is stored untouched in images/originals)</span>
      <div class="row"><input type="file" id="im_file" accept="image/*"><select id="im_sec">${o.sections.map(s => `<option value="${s.id}">${esc(s.title)}</option>`).join('')}</select></div>
      <input type="text" id="im_cap" placeholder="Caption" style="margin-top:6px"><input type="text" id="im_cr" placeholder="Credit / source" style="margin-top:6px"><input type="text" id="im_alt" placeholder="Alt text (describe the image for screen readers)" style="margin-top:6px"><button id="im_add" style="margin-top:6px">Add image</button></div></div>`
      : `<div class="smap">${smPreview(o)}</div>`}`;
  $$('[data-sview]').forEach(b => b.onclick = () => { S.view = b.dataset.sview; renderStory(); });
  $$('#sbody textarea').forEach(t => { t.oninput = () => { o.sections[t.dataset.i].parts[t.dataset.k].text = t.value; o.sections[t.dataset.i].text = o.sections[t.dataset.i].parts.map(p => p.text).join('\n\n'); }; });
  $('#ssave').onclick = () => run('ssave', async () => { await api(`/api/projects/${slug}/storymap`, o); toast('Saved — a version was recorded.'); renderStory(); });
  const clip = async (t, btn) => { try { await navigator.clipboard.writeText(t); const x = btn.textContent; btn.textContent = 'Copied ✓'; setTimeout(() => btn.textContent = x, 1400); } catch (e) { prompt('Copy this text:', t); } };
  $('#scopyall').onclick = e => clip(`# ${o.title}\n\n` + o.sections.map(secMd).join('\n'), e.target);
  $$('[data-copy]').forEach(b => b.onclick = () => clip(secMd(o.sections[b.dataset.copy]), b));
  $('#srestore').onclick = () => run('srestore', async () => { const v = $('#svers').value; if (!v) return; const r = await api(`/api/projects/${slug}/storymap/restore`, { id: v }); S.outline = r.outline; renderStory(); });
  const add = $('#im_add'); if (add) add.onclick = () => run('imadd', async () => {
    const f = $('#im_file').files[0]; if (!f) throw new Error('Choose an image first.');
    const b64 = await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result.split(',')[1]); r.readAsDataURL(f); });
    const r = await api(`/api/projects/${slug}/storymap/image`, { filename: f.name, data_base64: b64, section: $('#im_sec').value, caption: $('#im_cap').value, credit: $('#im_cr').value, alt: $('#im_alt').value });
    S.outline = r.outline; renderStory();
  });
}
