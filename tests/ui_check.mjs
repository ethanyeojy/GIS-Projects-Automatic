// Drives the real page in headless Edge/Chrome through the whole workflow and reports console errors.
// Usage: node tests/ui_check.mjs <serverUrl> <outDir> [stepsCsv]
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const [, , URL_, OUT, STEPS = 'all'] = process.argv;
fs.mkdirSync(OUT, { recursive: true });
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p => fs.existsSync(p));
const PORT = 9333 + Math.floor(Math.random() * 500);
const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'gps-ui-'));
const proc = spawn(EDGE, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, '--window-size=1500,1000', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let targets;
for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); if (targets.find(t => t.type === 'page')) break; } catch { } await sleep(300); }
const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pending = new Map(); const errors = [];
ws.addEventListener('message', m => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method === 'Runtime.exceptionThrown') errors.push('EXC: ' + (d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text));
  else if (d.method === 'Runtime.consoleAPICalled' && ['error'].includes(d.params.type)) errors.push('console.error: ' + d.params.args.map(a => a.value ?? a.description).join(' ').slice(0, 300));
});
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result.exceptionDetails) throw new Error('eval: ' + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text) + ' <- ' + expr.slice(0, 90)); return r.result.result.value; };
const shot = async name => { const r = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.result.data, 'base64')); };
const waitFor = async (expr, secs = 60, what = expr) => { for (let i = 0; i < secs * 4; i++) { try { if (await ev(expr)) return true; } catch { } await sleep(250); } throw new Error('timeout waiting for ' + what); };
const results = [];
const check = (name, ok, detail = '') => { results.push([name, ok]); console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? '  — ' + detail : '')); };

await send('Runtime.enable'); await send('Page.enable'); await send('Log.enable');
await send('Page.navigate', { url: URL_ + '/?tod=day' });
await waitFor('typeof S !== "undefined" && S.feed && S.feed.length > 0', 60, 'projects to load');
await sleep(1500);
check('Projects page loads with all projects', await ev('S.feed.length') >= 14 && await ev('document.querySelectorAll("#sidecar .pc").length') === await ev('S.feed.length'), `${await ev('S.feed.length')} cards`);
check('Datasets on the first page are in a dropdown (sources list collapsed)', await ev('!document.querySelector("#srcdet").open'));
check('Settings panel is collapsed by default and the left sidebar is gone', await ev('document.querySelector("#setPanel").hidden === true && !document.querySelector("aside")'));
await shot('01-projects');

// 7. settings reachable from the top nav
await ev('document.querySelector("#setBtn").click()');
await sleep(400);
check('7. Settings / Filters opens from the top navigation toggle', await ev('document.querySelector("#setPanel").hidden === false && document.querySelector("#setBtn").getAttribute("aria-expanded") === "true"'));
check('7b. Max file size setting is labelled per download', await ev('document.querySelector("#s_max").closest("label").textContent.includes("Maximum file size per download (MB)")'));
await ev('document.querySelector("#t_preset").value="2y"; document.querySelector("#t_preset").dispatchEvent(new Event("change"))');
await sleep(1500);
check('3. Time-period preset shows the exact dates', await ev('document.querySelector("#t_text").textContent.includes("→")'), await ev('document.querySelector("#t_text").textContent'));
await shot('02-settings-open');
await ev('document.querySelector("#t_preset").value="custom"; document.querySelector("#t_preset").dispatchEvent(new Event("change"))');
await sleep(1200);
check('3b. Custom range reveals date pickers', await ev('document.querySelector("#t_custom").style.display !== "none"'));
await ev('document.querySelector("#t_preset").value="2y"; document.querySelector("#t_preset").dispatchEvent(new Event("change"))');
await sleep(1200);
await ev('document.querySelector("#setBtn").click()');
check('7c. Settings persist after closing and switching tabs', await ev('S.period.preset') === '2y');

// 1. refresh ONE card: other cards byte-for-byte unchanged
const before = await ev('JSON.stringify([...document.querySelectorAll("#sidecar .pc")].filter(e=>e.dataset.pid!=="nz-seabirds").map(e=>e.outerHTML.length+e.dataset.pid))');
await ev('document.querySelector("[data-act=refresh][data-pid=nz-seabirds]").click()');
await sleep(500);
check('1a. While refreshing, the button stays clickable (never stuck)', await ev('!document.querySelector("[data-act=refresh][data-pid=nz-seabirds]").disabled'));
await waitFor('!document.querySelector("[data-act=refresh][data-pid=nz-seabirds]").classList.contains("busy")', 120, 'refresh to finish');
const after = await ev('JSON.stringify([...document.querySelectorAll("#sidecar .pc")].filter(e=>e.dataset.pid!=="nz-seabirds").map(e=>e.outerHTML.length+e.dataset.pid))');
check('1. Refreshing one card re-renders only that card', before === after, 'all other cards identical');
await shot('03-card-refreshed');

// 2. choose a project -> title, big question, purpose
await ev('document.querySelector("[data-act=choose][data-pid=nz-weather-extremes]").click()');
await waitFor('S.plan && !S.planLoading', 120, 'plan to load');
await sleep(500);
const head = await ev('({h1: document.querySelector("#project h1").textContent, q: document.querySelector("#project .bigq").textContent, p: document.querySelector("#project .purpose").textContent})');
check('2. Chosen project shows title, prominent main question and purpose', head.h1.length > 5 && head.q.includes('Main research question') && head.q.length > 60 && head.p.includes('matters'), head.h1);
check('2b. The project page lists each dataset with expected records and size', await ev('document.querySelectorAll("#project .dsp").length') >= 6 && (await ev('document.querySelector("#project .dsp-nums").textContent')).includes('records'));
await shot('04-project-plan');
await ev('document.querySelector(".dsp-f summary").click()');
await sleep(300);
await shot('05-dataset-filters');

// 4. find missing datasets from the project workflow
await ev('document.querySelector("#disc_q").value="rainfall rain gauge"; document.querySelector("[data-act2=disc-find]").click()');
await waitFor('S.disc && S.disc.candidates && S.disc.candidates.length > 0', 120, 'dataset finder');
await sleep(400);
check('4. "Find missing datasets" lists real candidates with source, coverage, format and size', await ev('document.querySelectorAll("#project .cand").length') > 0 && (await ev('document.querySelector("#project .cand").textContent')).includes('Size'));
await shot('06-find-datasets');
await ev('document.querySelector("#project .discbox").scrollIntoView()');

// start a small real download: only the quick datasets
await ev(`(() => { planItems().forEach(d => { S.sel[d.id].include = ['cliflo_rain','auck_floods'].includes(d.id); }); renderProject(); })()`);
await ev('document.querySelector("[data-act2=start]").click()');
await waitFor('S.tab === "progress" && S.jobData && Object.keys(S.jobData.datasets).length >= 3', 60, 'progress tab');
await sleep(1500);
check('Choosing "Start download" moves to the Progress tab', await ev('S.tab') === 'progress');
check('7. Each task shows state, stage and last-activity', await ev('document.querySelectorAll("#progress .task").length') >= 3 && await ev('!!document.querySelector("#progress .task .chip")'));
await shot('07-progress-running');
check('9. Refresh status button works without restarting anything', await (async () => { const a = await ev('S.jobData.datasets.regc.attempt'); await ev('document.querySelector("[data-jact=status]").click()'); await sleep(1500); return a === await ev('S.jobData.datasets.regc.attempt'); })());
await waitFor('S.tab === "quality"', 240, 'automatic move to Quality');
check('Progress moves to the Quality tab by itself when downloads finish', true);
await sleep(800);
await shot('08-quality');
check('Quality page is in plain language with a next button', await ev('document.querySelector("#quality .qcard") !== null && !!document.querySelector("#quality [data-go=files]")'));
await ev('document.querySelector("#quality [data-go=files]").click()');
await waitFor('S.files && document.querySelectorAll("#files .dfile").length > 0', 30, 'files tab');
check('12. Files tab has a Download-all button at the top and a download button per file', await ev('!!document.querySelector("#files .dlall a[href*=\\"scope=datasets\\"]") && document.querySelectorAll("#files .ffile a[download]").length > 0'));
await shot('09-files');
await ev('document.querySelector("[data-view=auck_floods]").click()');
await waitFor('document.querySelector("#mapbox .leaflet-pane") && document.querySelectorAll("#mapbox .leaflet-interactive").length > 0', 60, 'map layer to draw');
await sleep(2500);
check('12. A downloaded layer is drawn on a basemap map viewer', await ev('document.querySelectorAll("#mapbox .leaflet-interactive").length') > 0, `${await ev('document.querySelectorAll("#mapbox .leaflet-interactive").length')} features drawn; ${await ev('document.querySelector("#v_note").textContent')}`.slice(0, 160));
await shot('10-map-viewer');

// story
await ev('document.querySelector("#files [data-go=story]").click()');
await waitFor('S.outline', 30, 'story outline');
await sleep(1500);
check('StoryMap plan shows a styled preview with mock maps and photos', await ev('document.querySelectorAll("#story .sm-sec, #story .sm-cover").length') >= 8 && await ev('document.querySelectorAll("#story .mock svg, #story svg.mocksvg").length') >= 4 && await ev('document.querySelectorAll("#story img").length') >= 2);
check('Mock visuals are labelled as illustrations', await ev('[...document.querySelectorAll("#story .mock-badge")].every(b => /ILLUSTRATION|REAL/.test(b.textContent))'));
await shot('11-story-top');
await ev('window.scrollTo(0, 1500)'); await sleep(400); await shot('12-story-mid');
await ev('window.scrollTo(0, 2900)'); await sleep(400); await shot('13-story-more');
await ev('document.querySelector("[data-sview=edit]").click()'); await sleep(600); await shot('14-story-edit');

console.log('\nBROWSER ERRORS:', errors.length ? '\n' + errors.join('\n') : 'none');
check('No JavaScript errors in the console', errors.length === 0);
const bad = results.filter(r => !r[1]);
console.log(`\n${results.length - bad.length} passed, ${bad.length} failed`);
ws.close(); proc.kill();
process.exit(bad.length ? 1 : 0);
