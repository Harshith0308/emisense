/* EMISense live dashboard.

   Talks to the ESP32 running emi_classify over Web Serial (Chrome or Edge),
   at 921600 baud, with the firmware's own commands:
     c       capture 100 ms and classify       -> RESULT ..., FEAT ..., LOGITS ...
     t150    wait for a dip 150 counts deep    -> ARMED ..., then TRIGGERED ... or TIMEOUT
     k       re-measure the resting reference  -> rest_ref=NNNN
     w / x   send / stop sending the window    -> WAVE on / off, then WAVE v0 ... v1999
   The board decides; this page only draws what it reports. The amplitude
   threshold is computed here from the same window, as analyze.py defines it:
   A = rest_ref - min(window), alarm when A > T. */

'use strict';

const BAUD = 921600;
const N_SAMPLES = 2000;
const PRE_TRIGGER = 400;
const EVENT_LEVEL = 150;
const TRIG_DEPTH = 150;
const FEATURES = ['max_dip', 'mean_dip', 'act150', 'act400', 'rough', 'n_events', 'width_med',
  'interval_med', 'interval_cv', 'ac_peak', 'ac_lag_ms', 'zcr', 'level_drop', 'lag_fine_ms',
  'depth_cv'];                                   // features.FEATURE_NAMES, in order
const F = Object.fromEntries(FEATURES.map((n, i) => [n, i]));
const CLASS_INFO = {
  ambient: { name: 'Ambient', what: 'nothing near the coil' },
  spark: { name: 'Spark', what: 'a piezo igniter' },
  switching_supply: { name: 'Switching supply', what: 'a phone charger or adapter' },
  display: { name: 'Display', what: 'a phone screen' },
  sparking_motor: { name: 'Sparking motor', what: 'a mixer-grinder' },
  mains_hum: { name: 'Mains hum', what: 'a large mains power supply' },
  emp: { name: 'Attack', what: 'an EMI emitter' },
};
// fixed display order: the paper's class order, so a colour never moves
const ORDER = ['ambient', 'spark', 'switching_supply', 'display', 'sparking_motor', 'mains_hum', 'emp'];
let CLASSES = ['ambient', 'display', 'emp', 'mains_hum', 'spark', 'sparking_motor',
  'switching_supply'];                         // logits order; replaced from emi_model.h
let T = 194;                                   // replaced from analysis/results.json

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const colour = (c) => cssVar('--c-' + c) || cssVar('--axis');
const nameOf = (c) => (CLASS_INFO[c] ? CLASS_INFO[c].name : c);
const clock = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

const S = {
  port: null, reader: null, writer: null, readLoop: null,
  restRef: null, waveOn: false, running: false, mode: 'continuous',
  pending: null, next: null, watchdog: null,
  demo: null, demoTimer: null, demoIndex: 0,
  history: [], counts: {}, tally: { n: 0, thr: 0, clf: 0, avoided: 0 },
  last: null, hover: null,
};

/* ---------- page set-up ---------- */

function buildProbList() {
  const ul = $('prob-list');
  ul.innerHTML = '';
  for (const c of ORDER) {
    const li = document.createElement('li');
    li.className = 'prob';
    li.dataset.cls = c;
    li.innerHTML = `<span class="prob-name"><span class="prob-key"></span>${nameOf(c)}</span>
      <span class="prob-track"><span class="prob-bar"></span></span>
      <span class="prob-val">&ndash;</span>`;
    ul.appendChild(li);
  }
  paintKeys();
}

function paintKeys() {
  for (const li of document.querySelectorAll('.prob')) {
    const c = li.dataset.cls;
    li.querySelector('.prob-key').style.background = colour(c);
    li.querySelector('.prob-bar').style.background = colour(c);
  }
  renderSession();
}

async function loadModelInfo() {
  try {
    const h = await (await fetch('../emi_classify/emi_model.h', { cache: 'no-store' })).text();
    const m = h.match(/EMI_CLASSES\[[^\]]*\]\s*=\s*\{([^}]*)\}/);
    if (m) CLASSES = [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
    const nh = h.match(/#define EMI_N_HIDDEN (\d+)/);
    const nf = h.match(/#define EMI_N_FEATURES (\d+)/);
    if (nh && nf) {
      $('m-net').textContent = `${nf[1]} features, ${nh[1]} hidden units, ${CLASSES.length} classes, int8 weights`;
    }
  } catch (e) { /* keep the defaults */ }
  try {
    const r = await (await fetch('../analysis/results.json', { cache: 'no-store' })).json();
    const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
    const pct = (x) => (100 * x).toFixed(1) + '%';
    const ev = r.evaluations;
    $('m-acc').textContent = `${pct(mean(ev.blocks.accuracy))} on held-out recordings, `
      + `${pct(mean(ev.rooms.accuracy))} in unseen rooms, ${pct(mean(ev.models.accuracy))} on unseen device models`;
    if (r.attack) {
      const thr = r.attack.threshold;
      const det = r.attack.classifier_blocks;
      T = thr.T;
      $('m-attack').textContent = `detects ${pct(mean(det.map((d) => d.detection)))} of attack captures; `
        + `false alarms on ${pct(mean(det.map((d) => d.false_alarm_sources)))} of harmless sources`;
      $('m-thr').textContent = `T = ${Math.round(thr.T)} counts: detects ${pct(thr.detection)} of the attack; `
        + `false alarms on ${pct(thr.false_alarm_sources)} of harmless sources`;
    }
  } catch (e) { /* the page still works without the numbers */ }
  $('thr-sub').textContent = `alarms when the dip exceeds T = ${Math.round(T)} counts`;
}

/* ---------- serial link ---------- */

async function connect() {
  if (S.port) { await disconnect(); return; }
  if (!('serial' in navigator)) {
    notice('This browser cannot talk to USB serial. Open the page in Chrome or Edge.');
    return;
  }
  stopDemo();
  let port;
  try { port = await navigator.serial.requestPort(); } catch (e) { return; }   // cancelled
  setStatus('busy', 'Connecting');
  try {
    await port.open({ baudRate: BAUD, bufferSize: 1 << 16 });
  } catch (e) {
    setStatus('error', 'Port busy');
    notice('Could not open the port. Close capture.py, the Arduino Serial Monitor or any other '
      + 'program using it, then connect again.');
    return;
  }
  clearNotice();
  S.port = port;
  S.writer = port.writable.getWriter();
  S.restRef = null;
  S.waveOn = false;
  S.readLoop = readLines(port);
  $('btn-connect').textContent = 'Disconnect';
  try {                    // restart the sketch: EN low through RTS, GPIO0 high (DTR off)
    await port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await sleep(120);
    await port.setSignals({ dataTerminalReady: false, requestToSend: false });
  } catch (e) { /* some adapters refuse; the k below still works */ }
  if (!await waitFor(() => S.restRef !== null, 5000)) {
    await send('k');
    await waitFor(() => S.restRef !== null, 3000);
  }
  if (S.restRef === null) {
    setStatus('error', 'No reply');
    notice('The board did not answer. Is emi_classify flashed? The collection firmware '
      + '(emi_capture) does not classify.');
    return;
  }
  await send('w');
  if (!await waitFor(() => S.waveOn, 1500)) {
    notice('Connected, but this firmware does not send the waveform. Flash the latest '
      + 'emi_classify to see the signal; decisions still show.');
  }
  setStatus('live', 'Connected');
  enableControls(true);
}

async function readLines(port) {
  const decoder = new TextDecoderStream();
  const piped = port.readable.pipeTo(decoder.writable).catch(() => {});
  const reader = decoder.readable.getReader();
  S.reader = reader;
  let buf = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, '');
        buf = buf.slice(i + 1);
        if (line) onLine(line);
      }
      if (buf.length > 100000) buf = '';            // never a real line: boot noise
    }
  } catch (e) { /* the port went away */ }
  try { reader.releaseLock(); } catch (e) { /* already released */ }
  await piped;
  if (S.port === port) lostPort();
}

async function disconnect() {
  const port = S.port;
  S.port = null;
  stopRunning();
  try { await S.reader?.cancel(); } catch (e) { /* closed */ }
  try { S.writer?.releaseLock(); } catch (e) { /* closed */ }
  try { await S.readLoop; } catch (e) { /* closed */ }
  try { await port?.close(); } catch (e) { /* closed */ }
  S.reader = S.writer = S.readLoop = null;
  setStatus('off', 'Not connected');
  $('btn-connect').textContent = 'Connect detector';
  enableControls(false);
}

function lostPort() {
  const port = S.port;
  S.port = null;
  stopRunning();
  try { S.writer?.releaseLock(); } catch (e) { /* gone */ }
  port?.close().catch(() => {});
  S.reader = S.writer = S.readLoop = null;
  setStatus('error', 'Disconnected');
  $('btn-connect').textContent = 'Connect detector';
  enableControls(false);
  notice('The detector was disconnected. Check the USB cable, then connect again.');
}

async function send(cmd) {
  if (!S.writer) return;
  try { await S.writer.write(new TextEncoder().encode(cmd)); } catch (e) { /* port lost */ }
}

async function waitFor(test, ms) {
  const end = performance.now() + ms;
  while (performance.now() < end) {
    if (test()) return true;
    await sleep(50);
  }
  return test();
}

function onLine(line) {
  let m;
  if ((m = line.match(/^READY classify rest_ref=(-?\d+)/)) || (m = line.match(/^rest_ref=(-?\d+)/))) {
    S.restRef = Number(m[1]);
    $('t-rest').textContent = S.restRef;
    return;
  }
  if (line === 'WAVE on') { S.waveOn = true; return; }
  if (line === 'WAVE off') { S.waveOn = false; return; }
  if (line.startsWith('ARMED')) { $('decision-meta').textContent = 'Armed: waiting for a burst'; return; }
  if (line === 'TIMEOUT') {
    $('decision-meta').textContent = 'No burst in 30 s';
    if (S.running) schedule(0);
    return;
  }
  if ((m = line.match(/^(RESULT|TRIGGERED) class=(\S+) features_us=(\d+) model_us=(\d+)/))) {
    S.pending = { kind: m[1], cls: m[2], featuresUs: Number(m[3]), modelUs: Number(m[4]),
      feat: null, logits: null, wave: null };
    return;
  }
  if (!S.pending) return;
  if (line.startsWith('FEAT ')) {
    S.pending.feat = line.slice(5).trim().split(/\s+/).map(Number);
  } else if (line.startsWith('LOGITS ')) {
    S.pending.logits = line.slice(7).trim().split(/\s+/).map(Number);
    if (!S.waveOn) finish();
  } else if (line.startsWith('WAVE ')) {
    const v = line.slice(5).trim().split(/\s+/).map(Number);
    if (v.length === N_SAMPLES && v.every(Number.isFinite)) S.pending.wave = v;
    finish();
  }
}

function finish() {
  const p = S.pending;
  S.pending = null;
  if (!p || !p.logits || p.logits.length !== CLASSES.length) return;
  clearTimeout(S.watchdog);
  show({ cls: p.cls, logits: p.logits, feat: p.feat, wave: p.wave, restRef: S.restRef,
    triggered: p.kind === 'TRIGGERED', featuresUs: p.featuresUs, modelUs: p.modelUs });
  if (S.running) schedule(S.mode === 'continuous' ? 120 : 0);
}

function schedule(delay) {
  clearTimeout(S.next);
  S.next = setTimeout(async () => {
    if (!S.running || !S.port) return;
    await send(S.mode === 'continuous' ? 'c' : 't' + TRIG_DEPTH);
    clearTimeout(S.watchdog);
    // a lost reply must not stall the loop
    S.watchdog = setTimeout(() => {
      if (S.running) { S.pending = null; schedule(0); }
    }, S.mode === 'continuous' ? 4000 : 36000);
  }, delay);
}

function stopRunning() {
  S.running = false;
  clearTimeout(S.next);
  clearTimeout(S.watchdog);
  updateRunBtn();
}

/* ---------- demo ---------- */

async function toggleDemo() {
  if (S.demo) { stopDemo(); return; }
  if (S.port) await disconnect();
  try {
    S.demo = await (await fetch('demo.json', { cache: 'no-store' })).json();
  } catch (e) {
    notice('Demo data not found. Run: python dashboard/make_demo.py');
    return;
  }
  clearNotice();
  if (S.demo.classes) CLASSES = S.demo.classes;
  S.demoIndex = 0;
  setStatus('demo', 'Demo: recorded captures');
  $('btn-demo').textContent = 'Stop demo';
  const step = () => {
    const c = S.demo.captures[S.demoIndex++ % S.demo.captures.length];
    show({ cls: c.cls, logits: c.logits, feat: c.feat, wave: c.values, restRef: c.rest_ref,
      triggered: c.mode === 'triggered', featuresUs: null, modelUs: null,
      demo: { truth: c.true, device: c.device, distance: c.distance_cm } });
    S.demoTimer = setTimeout(step, 1800);
  };
  step();
}

function stopDemo() {
  if (!S.demo) return;
  clearTimeout(S.demoTimer);
  S.demo = null;
  $('btn-demo').textContent = 'Demo';
  if (!S.port) setStatus('off', 'Not connected');
}

/* ---------- drawing a result ---------- */

function softmax(z) {
  const mx = Math.max(...z);
  const e = z.map((v) => Math.exp(v - mx));
  const s = e.reduce((a, b) => a + b, 0);
  return e.map((v) => v / s);
}

function show(r) {
  const probs = softmax(r.logits);
  const conf = probs[CLASSES.indexOf(r.cls)] ?? 0;
  const A = r.wave && r.restRef != null ? r.restRef - Math.min(...r.wave) : null;
  const thrAlarm = A != null && A > T;
  const clfAlarm = r.cls === 'emp';
  const now = clock();

  $('v-class').textContent = nameOf(r.cls);
  $('v-what').textContent = CLASS_INFO[r.cls] ? 'The board identifies ' + CLASS_INFO[r.cls].what : '';
  $('v-swatch').style.background = colour(r.cls);
  $('v-conf').textContent = Math.round(conf * 100) + '%';
  $('decision-meta').textContent = r.demo
    ? `Recorded: ${r.demo.device}${r.demo.distance ? ', ' + r.demo.distance + ' cm' : ''}; labelled ${nameOf(r.demo.truth)}`
    : `${now}, ${r.triggered ? 'triggered' : 'continuous'}`;

  setDetector('det-emisense', clfAlarm ? 'alarm' : 'clear', clfAlarm ? 'Attack detected' : 'No attack');
  if (A == null) {
    setDetector('det-threshold', 'idle', 'Needs the waveform');
  } else {
    setDetector('det-threshold', thrAlarm ? 'alarm' : 'clear', thrAlarm ? 'Alarm' : 'Quiet');
    $('thr-sub').textContent = `dip A = ${Math.round(A)} counts ${thrAlarm ? '>' : '≤'} T = ${Math.round(T)}`;
  }
  $('avoided').hidden = !(thrAlarm && !clfAlarm);

  for (const li of document.querySelectorAll('.prob')) {
    const p = probs[CLASSES.indexOf(li.dataset.cls)] ?? 0;
    li.querySelector('.prob-bar').style.width = (p * 100).toFixed(1) + '%';
    li.querySelector('.prob-val').textContent = (p * 100).toFixed(p < 0.1 ? 1 : 0) + '%';
    li.classList.toggle('top', li.dataset.cls === r.cls);
  }

  const f = r.feat;
  $('t-dip').textContent = f ? Math.round(f[F.max_dip]) : (A != null ? Math.round(A) : '–');
  $('t-events').textContent = f ? Math.round(f[F.n_events]) : '–';
  if (f && f[F.ac_peak] >= 0.3 && f[F.lag_fine_ms] > 0) {
    $('t-period').textContent = f[F.lag_fine_ms].toFixed(2) + ' ms';
    $('t-period-unit').textContent = (1000 / f[F.lag_fine_ms]).toFixed(1) + ' Hz';
  } else {
    $('t-period').textContent = '–';
    $('t-period-unit').textContent = 'no clear repetition';
  }
  $('t-drop').textContent = f ? Math.round(f[F.level_drop]) : '–';
  if (r.featuresUs != null) {
    $('t-latency').textContent = ((r.featuresUs + r.modelUs) / 1000).toFixed(1) + ' ms';
    $('t-latency-unit').textContent = `features ${(r.featuresUs / 1000).toFixed(1)} ms, model ${r.modelUs} µs`;
  } else {
    $('t-latency').textContent = '–';
    $('t-latency-unit').textContent = 'measured on the board only';
  }
  if (r.restRef != null) $('t-rest').textContent = r.restRef;

  S.tally.n += 1;
  if (thrAlarm) S.tally.thr += 1;
  if (clfAlarm) S.tally.clf += 1;
  if (thrAlarm && !clfAlarm) S.tally.avoided += 1;
  S.counts[r.cls] = (S.counts[r.cls] || 0) + 1;
  S.history.unshift({ cls: r.cls, time: now, alarm: clfAlarm });
  if (S.history.length > 60) S.history.pop();
  renderSession();

  S.last = r;
  S.hover = null;
  drawWave();
}

function setDetector(id, state, text) {
  const el = $(id);
  el.dataset.state = state;
  el.querySelector('.det-text').textContent = text;
}

function renderSession() {
  $('s-n').textContent = S.tally.n;
  $('s-thr').textContent = S.tally.thr;
  $('s-clf').textContent = S.tally.clf;
  $('s-avoided').textContent = S.tally.avoided;
  const tl = $('timeline');
  tl.innerHTML = '';
  for (const h of S.history) {
    const li = document.createElement('li');
    li.style.background = colour(h.cls);
    li.title = `${h.time}: ${nameOf(h.cls)}${h.alarm ? ' (attack alarm)' : ''}`;
    li.setAttribute('aria-label', li.title);
    if (h.alarm) li.className = 'alarm';
    tl.appendChild(li);
  }
  const body = $('count-body');
  body.innerHTML = '';
  for (const c of ORDER) {
    const n = S.counts[c] || 0;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><span class="key" style="background:${colour(c)}"></span>${nameOf(c)}</td>`
      + `<td>${n}</td><td>${S.tally.n ? Math.round((100 * n) / S.tally.n) + '%' : '–'}</td>`;
    body.appendChild(tr);
  }
}

/* ---------- the waveform chart ---------- */

function niceTicks(lo, hi, count) {
  const span = hi - lo || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.5; v += step) ticks.push(Math.round(v));
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function drawWave() {
  const cv = $('wave');
  const ctx = cv.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth;
  const H = cv.clientHeight;
  cv.width = Math.round(W * dpr);
  cv.height = Math.round(H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const r = S.last;
  const pad = { l: 46, r: 14, t: 16, b: 26 };
  const pw = W - pad.l - pad.r;
  const ph = H - pad.t - pad.b;
  const ink = cssVar('--ink');
  const ink2 = cssVar('--ink-2');
  const muted = cssVar('--muted');
  const grid = cssVar('--grid');
  const axis = cssVar('--axis');

  let depth = null;
  if (r && r.wave) {
    const rest = r.restRef != null ? r.restRef : [...r.wave].sort((a, b) => a - b)[Math.floor(0.9 * r.wave.length)];
    depth = r.wave.map((v) => rest - v);
  }
  const maxD = depth ? Math.max(...depth) : 0;
  const minD = depth ? Math.min(...depth) : 0;
  const ticks = niceTicks(Math.min(0, minD), Math.max(400, T * 1.5, maxD * 1.05), 5);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const x = (i) => pad.l + (i / (N_SAMPLES - 1)) * pw;
  const y = (d) => pad.t + (1 - (d - yMin) / (yMax - yMin)) * ph;

  ctx.font = '11px system-ui, -apple-system, "Segoe UI", sans-serif';
  ctx.lineWidth = 1;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const t of ticks) {
    const yy = Math.round(y(t)) + 0.5;
    ctx.strokeStyle = t === 0 ? axis : grid;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(W - pad.r, yy); ctx.stroke();
    ctx.fillStyle = muted;
    ctx.fillText(String(t), pad.l - 7, yy);
  }
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let ms = 0; ms <= 100; ms += 10) {
    ctx.fillStyle = muted;
    ctx.textAlign = ms === 100 ? 'right' : 'center';       // keep the last label inside
    ctx.fillText(ms === 100 ? '100 ms' : String(ms), pad.l + (ms / 100) * pw + (ms === 100 ? 4 : 0), H - pad.b + 8);
  }

  // the two levels are close (150, ~194): label T above its line, the burst
  // level below its own, so the labels never collide
  const refLine = (level, dash, label, tone, below) => {
    if (level < yMin || level > yMax) return;
    const yy = Math.round(y(level)) + 0.5;
    ctx.save();
    ctx.setLineDash(dash);
    ctx.strokeStyle = tone;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(W - pad.r, yy); ctx.stroke();
    ctx.restore();
    ctx.fillStyle = tone;
    ctx.textAlign = 'right';
    ctx.textBaseline = below ? 'top' : 'bottom';
    ctx.fillText(label, W - pad.r - 2, below ? yy + 3 : yy - 3);
  };
  refLine(EVENT_LEVEL, [2, 3], `burst level ${EVENT_LEVEL}`, muted, true);
  refLine(T, [6, 4], `threshold T = ${Math.round(T)}`, ink2, false);

  if (r && r.triggered && depth) {
    const xx = Math.round(x(PRE_TRIGGER)) + 0.5;
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = axis;
    ctx.beginPath(); ctx.moveTo(xx, pad.t); ctx.lineTo(xx, pad.t + ph); ctx.stroke();
    ctx.restore();
    ctx.fillStyle = muted;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillText('trigger', xx + 4, pad.t + ph - 3);
  }

  if (!depth) {
    ctx.fillStyle = muted;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(r ? 'This firmware does not send the waveform' : 'No signal yet', pad.l + pw / 2, pad.t + ph / 2);
    return;
  }

  ctx.save();
  ctx.beginPath();
  ctx.rect(pad.l, pad.t, pw, ph);
  ctx.clip();
  ctx.strokeStyle = colour(r.cls);
  ctx.lineWidth = 1.25;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  for (let i = 0; i < depth.length; i++) {
    const px = x(i);
    const py = y(depth[i]);
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.restore();

  if (S.hover != null) {
    const i = S.hover;
    const xx = Math.round(x(i)) + 0.5;
    ctx.strokeStyle = ink2;
    ctx.beginPath(); ctx.moveTo(xx, pad.t); ctx.lineTo(xx, pad.t + ph); ctx.stroke();
    ctx.fillStyle = colour(r.cls);
    ctx.strokeStyle = cssVar('--surface');
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(xx, y(depth[i]), 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }
  S.geom = { pad, pw, depth, ink };
}

function onWaveMove(ev) {
  const g = S.geom;
  const tip = $('tip');
  if (!g || !g.depth) { tip.hidden = true; return; }
  const rect = $('wave').getBoundingClientRect();
  const px = ev.clientX - rect.left;
  const i = Math.round(((px - g.pad.l) / g.pw) * (N_SAMPLES - 1));
  if (i < 0 || i >= N_SAMPLES) { onWaveLeave(); return; }
  S.hover = i;
  drawWave();
  tip.hidden = false;
  tip.innerHTML = `${(i * 0.05).toFixed(2)} ms<br><b>${Math.round(g.depth[i])}</b> counts below rest`;
  const left = Math.min(Math.max(px + 12, 0), rect.width - tip.offsetWidth - 4);
  tip.style.left = left + 'px';
  tip.style.top = '8px';
}

function onWaveLeave() {
  S.hover = null;
  $('tip').hidden = true;
  drawWave();
}

/* ---------- controls ---------- */

function setStatus(state, text) {
  $('status').dataset.state = state;
  $('status-text').textContent = text;
}

function notice(msg) {
  const n = $('notice');
  n.textContent = msg;
  n.hidden = false;
}

function clearNotice() { $('notice').hidden = true; }

function enableControls(on) {
  $('btn-run').disabled = !on;
  $('btn-rest').disabled = !on;
  updateRunBtn();
}

function updateRunBtn() {
  $('btn-run').textContent = S.running ? 'Pause' : 'Start';
  $('btn-run').classList.toggle('btn-primary', !S.running && !!S.port);
}

function setMode(mode) {
  S.mode = mode;
  $('mode-continuous').setAttribute('aria-pressed', String(mode === 'continuous'));
  $('mode-triggered').setAttribute('aria-pressed', String(mode === 'triggered'));
  if (S.running) schedule(0);
}

function toggleRun() {
  if (!S.port) return;
  S.running = !S.running;
  updateRunBtn();
  if (S.running) schedule(0); else stopRunning();
}

async function remeasureRest() {
  if (!S.port) return;
  notice('Measuring the resting level: keep everything away from the coil for a moment.');
  const before = S.restRef;
  S.restRef = null;
  await send('k');
  if (!await waitFor(() => S.restRef !== null, 3000)) S.restRef = before;
  setTimeout(clearNotice, 1500);
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === 'dark'
    : window.matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('emisense-theme', root.dataset.theme); } catch (e) { /* private mode */ }
  paintKeys();
  if (S.last) $('v-swatch').style.background = colour(S.last.cls);
  drawWave();
}

function clearSession() {
  S.history = [];
  S.counts = {};
  S.tally = { n: 0, thr: 0, clf: 0, avoided: 0 };
  renderSession();
}

function init() {
  try {
    const t = localStorage.getItem('emisense-theme');
    if (t) document.documentElement.dataset.theme = t;
  } catch (e) { /* storage blocked */ }
  buildProbList();
  loadModelInfo().then(drawWave);
  $('btn-connect').addEventListener('click', connect);
  $('btn-run').addEventListener('click', toggleRun);
  $('btn-rest').addEventListener('click', remeasureRest);
  $('btn-demo').addEventListener('click', toggleDemo);
  $('btn-theme').addEventListener('click', toggleTheme);
  $('btn-clear').addEventListener('click', clearSession);
  $('mode-continuous').addEventListener('click', () => setMode('continuous'));
  $('mode-triggered').addEventListener('click', () => setMode('triggered'));
  $('wave').addEventListener('mousemove', onWaveMove);
  $('wave').addEventListener('mouseleave', onWaveLeave);
  new ResizeObserver(() => drawWave()).observe($('wave'));
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { paintKeys(); drawWave(); });
  if (!('serial' in navigator)) {
    $('btn-connect').disabled = true;
    $('btn-connect').title = 'Open this page in Chrome or Edge to connect the detector';
    notice('Live mode needs Chrome or Edge (they can talk to the detector over USB). The demo works here.');
  } else {
    navigator.serial.addEventListener('disconnect', (e) => { if (e.target === S.port) lostPort(); });
  }
  updateRunBtn();
}

init();
