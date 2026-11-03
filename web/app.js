'use strict';
// F1 25 AI inženýr – frontend (vanilla JS, bez build kroku)

const $ = (id) => document.getElementById(id);
let S = null;              // poslední snapshot
let track = null;          // obrys trati + zatáčky
let trackVersion = -1;
let compareLap = null;
let lastSpoken = null;
let radioOn = false;
let settingsLoaded = false;

// ------------------------------------------------------------------ formát
function fmtLap(ms) {
  if (!ms) return '–';
  ms = Math.round(ms);
  const m = Math.floor(ms / 60000);
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, '0');
  return `${m}:${s}`;
}
function fmtDelta(ms, digits = 2) {
  if (ms === null || ms === undefined) return '–';
  const s = (ms / 1000).toFixed(digits);
  return (ms > 0 ? '+' : ms < 0 ? '' : '±') + s;
}
function fmtSec(ms) { return ms ? (ms / 1000).toFixed(3) : '–'; }
function cls(el, c, on) { el.classList.toggle(c, !!on); }
function esc(t) { return String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

// ------------------------------------------------------------------ taby
document.querySelectorAll('nav#tabs button').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('nav#tabs button').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    $('tab-' + b.dataset.tab).classList.add('active');
    if (b.dataset.tab === 'corners') loadCompare(true);
    if (b.dataset.tab === 'laps') loadHistory();
    if (b.dataset.tab === 'live') drawMap();
  };
});

// ------------------------------------------------------------------ data stream
function connect() {
  const es = new EventSource('/events');
  es.onmessage = (e) => {
    try { S = JSON.parse(e.data); } catch (_) { return; }
    render();
  };
  es.onerror = () => { $('conn').classList.remove('on'); };
}

function render() {
  const s = S;
  cls($('conn'), 'on', s.connected);
  const sess = s.session || {};
  $('track').textContent = sess.track || (s.connected ? 'Načítám session…' : 'Čekám na telemetrii ze hry…');
  $('stype').textContent = sess.type || '';
  $('ai').textContent = sess.ai !== null && sess.ai !== undefined ? 'AI ' + sess.ai : '';
  $('weather').textContent = sess.weather ? `${sess.weather} · track ${sess.track_temp}°C · air ${sess.air_temp}°C` : '';
  $('warning').textContent = s.warning || '';
  cls($('warning'), 'hidden', !s.warning);
  if (!settingsLoaded) fillSettings(s);

  renderLive(s);
  renderRadio(s);
  if (document.querySelector('#tab-corners.active')) renderCorners(s);
  if (document.querySelector('#tab-laps.active')) renderLaps(s);
  if (document.querySelector('#tab-race.active')) renderRace(s);
  $('aiMode').textContent = s.has_gemini ? 'Odpovídá Gemini (online).' : 'Offline režim. Pro chytřejší odpovědi vlož Gemini klíč v Nastavení.';

  if (s.track_version !== trackVersion) {
    trackVersion = s.track_version;
    fetch('/api/track').then((r) => r.json()).then((t) => { track = t; drawMap(); });
  }
  if (s.compare_lap !== compareLap) {
    compareLap = s.compare_lap;
    if (document.querySelector('#tab-corners.active')) loadCompare(false);
  }
  speakNew(s.messages);
}

function renderLive(s) {
  const l = s.live, ref = s.reference || {}, t = s.target;
  if (l) {
    $('lapNum').textContent = l.lap;
    $('pos').textContent = l.position;
    $('lapTime').textContent = fmtLap(l.lap_ms);
    const d = $('delta');
    d.textContent = l.delta !== undefined ? fmtDelta(l.delta) : '–';
    d.style.color = l.delta === undefined ? '' : l.delta <= 0 ? 'var(--green)' : 'var(--red)';
    $('predicted').textContent = l.predicted ? fmtLap(l.predicted) : '–';
    cls($('invalid'), 'hidden', !l.invalid);
    $('thr').style.width = ((l.throttle || 0) * 100) + '%';
    $('brk').style.width = ((l.brake || 0) * 100) + '%';
    $('speed').textContent = l.speed || 0;
    $('gear').textContent = l.gear === 0 ? 'N' : l.gear === -1 ? 'R' : (l.gear || 'N');
    // sektory
    const cur = [l.s1, l.s2, l.s1 && l.s2 && l.sector === 3 ? null : null];
    const refS = ref.sectors || [];
    const bestS = bestSectors(s);
    for (let i = 0; i < 3; i++) {
      const el = $('sec' + (i + 1));
      const v = i < 2 ? cur[i] : null;
      const done = v && l.sector > i + 1;
      el.querySelector('b').textContent = done ? fmtSec(v) : (refS[i] ? fmtSec(refS[i]) : '–');
      el.querySelector('i').textContent = done && refS[i] ? fmtDelta(v - refS[i]) : (refS[i] ? 'ref' : '');
      el.className = 'sector' + (l.sector === i + 1 ? ' active' : '');
      if (done) {
        if (bestS[i] && v <= bestS[i]) el.classList.add('purple');
        else if (refS[i] && v <= refS[i]) el.classList.add('green');
        else el.classList.add('yellow');
      }
    }
  }
  $('refName').textContent = ref.name || '–';
  $('refTime').textContent = fmtLap(ref.lap_ms);
  if (t) {
    $('tgtName').textContent = `AI ${t.ai}`;
    $('tgtTime').textContent = fmtLap(t.lap_ms);
    let extra = t.src;
    if (t.gap_best !== undefined) extra += ` · session best ${fmtDelta(t.gap_best)} s`;
    if (t.ai_session_best) extra += ` · fastest AI ${fmtLap(t.ai_session_best)}`;
    $('tgtSrc').textContent = extra;
    $('matchAi').textContent = t.match_ai !== undefined && t.match_ai !== null ? '~' + t.match_ai : '–';
  }
  $('bestTime').textContent = s.best ? fmtLap(s.best.time) : '–';
  $('pbTime').textContent = s.pb ? fmtLap(s.pb.lap_ms) : '–';
  $('theoTime').textContent = fmtLap(s.theoretical_best);
  drawMapCar();
}

function bestSectors(s) {
  const out = [null, null, null];
  (s.laps || []).forEach((l) => {
    if (!l.valid) return;
    l.sectors.forEach((v, i) => { if (v && (!out[i] || v < out[i])) out[i] = v; });
  });
  return out;
}

let renderedMsgId = -1;
function renderRadio(s) {
  const msgs = s.messages || [];
  const last = msgs.length ? msgs[msgs.length - 1].id : 0;
  if (last === renderedMsgId) return;
  renderedMsgId = last;
  $('radioLog').innerHTML = msgs.slice().reverse().map((m) => {
    const t = new Date(m.ts * 1000).toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });
    return `<div class="msg p${m.prio}"><time>${t}</time>${esc(m.text)}</div>`;
  }).join('');
}

// ------------------------------------------------------------------ mapa
function mapGeom(canvas) {
  const o = track && track.outline;
  if (!o || !o.x || !o.x.length) return null;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight || 270;
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
  const minX = Math.min(...o.x), maxX = Math.max(...o.x), minZ = Math.min(...o.z), maxZ = Math.max(...o.z);
  const pad = 24;
  const sc = Math.min((w - 2 * pad) / (maxX - minX || 1), (h - 2 * pad) / (maxZ - minZ || 1));
  const ox = (w - (maxX - minX) * sc) / 2, oz = (h - (maxZ - minZ) * sc) / 2;
  return { dpr, w, h, P: (x, z) => [ox + (x - minX) * sc, oz + (z - minZ) * sc] };
}

let mapBase = null;
function drawMap() {
  const c = $('map');
  const g = mapGeom(c);
  const ctx = c.getContext('2d');
  if (!g || !g.w) { mapBase = null; ctx.clearRect(0, 0, c.width, c.height); return; }
  ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
  ctx.clearRect(0, 0, g.w, g.h);
  const o = track.outline;
  ctx.lineWidth = 6; ctx.strokeStyle = '#2b3242'; ctx.lineJoin = 'round';
  ctx.beginPath();
  o.x.forEach((x, i) => { const [px, pz] = g.P(x, o.z[i]); i ? ctx.lineTo(px, pz) : ctx.moveTo(px, pz); });
  ctx.closePath(); ctx.stroke();
  // start
  const [sx, sz] = g.P(o.x[0], o.z[0]);
  ctx.fillStyle = '#fff'; ctx.fillRect(sx - 2, sz - 8, 4, 16);
  // zatáčky obarvené podle ztráty
  const corners = (S && S.corners) || track.corners || [];
  corners.forEach((cn) => {
    const [px, pz] = g.P(cn.x, cn.z);
    const loss = cn.avg_loss;
    let col = '#64748b';
    if (loss !== null && loss !== undefined) col = loss > 80 ? '#ef4444' : loss > 30 ? '#f59e0b' : '#22c55e';
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(px, pz, 12, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#0b0d12'; ctx.font = 'bold 9px -apple-system, sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(cn.name, px, pz + 0.5);
  });
  mapBase = ctx.getImageData(0, 0, c.width, c.height);
  mapBase._g = g;
}

function drawMapCar() {
  if (!mapBase || !S || !S.live || !track || !track.outline) return;
  const c = $('map'), ctx = c.getContext('2d');
  const g = mapBase._g;
  ctx.putImageData(mapBase, 0, 0);
  const o = track.outline, d = S.live.dist;
  let i = 0;
  while (i < o.dist.length - 1 && o.dist[i + 1] < d) i++;
  const j = Math.min(i + 1, o.dist.length - 1);
  const f = o.dist[j] > o.dist[i] ? (d - o.dist[i]) / (o.dist[j] - o.dist[i]) : 0;
  const x = o.x[i] + (o.x[j] - o.x[i]) * f, z = o.z[i] + (o.z[j] - o.z[i]) * f;
  const [px, pz] = g.P(x, z);
  ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
  ctx.fillStyle = '#e10600'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(px, pz, 7, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
}
window.addEventListener('resize', drawMap);

// ------------------------------------------------------------------ zatáčky
function renderCorners(s) {
  $('cRef').textContent = (s.reference && s.reference.name) || 'reference';
  $('cLap').textContent = s.compare_lap ? `analyzovaný lap: ${s.compare_lap}` : 'zatím žádný analyzovaný lap';
  const rows = (s.corners || []).map((c) => {
    const l = c.last;
    const loss = l ? l.loss : null;
    const bar = loss > 0 ? `<span class="loss-bar" style="width:${Math.min(80, loss / 4)}px"></span>` : '';
    const lc = loss === null ? '' : loss > 0 ? 'loss' : 'gain';
    const ac = c.avg_loss === null ? '' : c.avg_loss > 0 ? 'loss' : 'gain';
    const brake = l && l.brake_diff_m !== null ? (l.brake_diff_m < 0 ? `${-l.brake_diff_m} m dřív` : l.brake_diff_m > 0 ? `${l.brake_diff_m} m později` : 'stejně') : '–';
    const thr = l && l.throttle_diff_m !== null ? (l.throttle_diff_m > 0 ? `${l.throttle_diff_m} m později` : l.throttle_diff_m < 0 ? `${-l.throttle_diff_m} m dřív` : 'stejně') : '–';
    const tips = l && l.tips_text && l.tips_text.length ? l.tips_text.join('; ') : (l ? 'OK' : '');
    return `<tr><td><b>${c.name}</b></td>
      <td class="num ${lc}">${loss === null ? '–' : fmtDelta(loss, 3)}${bar}</td>
      <td class="num ${ac}">${c.avg_loss === null ? '–' : fmtDelta(c.avg_loss, 3)}</td>
      <td class="num">${l ? `${l.min_speed} / ${l.ref_min_speed}` : '–'}</td>
      <td>${brake}</td><td>${thr}</td><td>${esc(tips)}</td></tr>`;
  });
  $('cornerTable').querySelector('tbody').innerHTML = rows.join('') ||
    '<tr><td colspan="7" class="muted">Odjeď jeden čistý valid lap. Turns se detekují automaticky.</td></tr>';
}

let cmp = null;
function loadCompare(render) {
  fetch('/api/compare').then((r) => r.json()).then((d) => { cmp = d && d.dist ? d : null; drawChart(); });
}

function drawChart() {
  const c = $('chart'), ctx = c.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = 420;
  c.width = w * dpr; c.height = h * dpr; c.style.height = h + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!cmp) {
    ctx.fillStyle = '#8b93a7'; ctx.font = '15px -apple-system';
    ctx.fillText('Graf se zobrazí po prvním analyzovaném lapu.', 16, 40);
    return;
  }
  const L = cmp.dist[cmp.dist.length - 1] || 1;
  const X = (d) => 40 + (d / L) * (w - 50);
  const top = { y: 10, h: 220 }, dl = { y: 245, h: 80 }, pd = { y: 340, h: 70 };
  // zatáčky
  (cmp.corners || []).forEach((cn) => {
    ctx.fillStyle = 'rgba(255,255,255,0.04)';
    ctx.fillRect(X(cn.start), 0, X(cn.end) - X(cn.start), h);
    ctx.fillStyle = '#8b93a7'; ctx.font = '11px -apple-system';
    ctx.fillText(cn.name, X(cn.apex) - 8, top.y + 12);
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath(); ctx.moveTo(X(cn.start), 0); ctx.lineTo(X(cn.start), h); ctx.stroke();
  });
  const maxV = Math.max(...cmp.speed, ...cmp.lap_speed, 100);
  const line = (arr, col, y0, hh, max, min = 0, width = 2) => {
    ctx.strokeStyle = col; ctx.lineWidth = width; ctx.beginPath();
    arr.forEach((v, i) => {
      const x = X(cmp.dist[i]), y = y0 + hh - ((v - min) / (max - min)) * hh;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  };
  ctx.fillStyle = '#8b93a7'; ctx.font = '11px -apple-system';
  ctx.fillText('km/h', 2, top.y + 10);
  line(cmp.speed, '#38bdf8', top.y, top.h, maxV);
  line(cmp.lap_speed, '#e10600', top.y, top.h, maxV);
  // delta
  const dmax = Math.max(100, ...cmp.delta.map(Math.abs));
  ctx.strokeStyle = '#3b4456'; ctx.beginPath(); ctx.moveTo(40, dl.y + dl.h / 2); ctx.lineTo(w, dl.y + dl.h / 2); ctx.stroke();
  ctx.fillText('delta', 2, dl.y + 10);
  ctx.fillText(fmtDelta(dmax), 2, dl.y + 22);
  line(cmp.delta, '#facc15', dl.y, dl.h, dmax, -dmax);
  // pedály
  ctx.fillText('throttle', 2, pd.y + 12); ctx.fillText('brake', 2, pd.y + pd.h - 4);
  line(cmp.ref_throttle, 'rgba(56,189,248,.7)', pd.y, pd.h / 2 - 2, 1, 0, 1.5);
  line(cmp.throttle, 'rgba(34,197,94,.9)', pd.y, pd.h / 2 - 2, 1, 0, 1.5);
  line(cmp.ref_brake, 'rgba(56,189,248,.7)', pd.y + pd.h / 2 + 2, pd.h / 2 - 2, 1, 0, 1.5);
  line(cmp.brake, 'rgba(239,68,68,.9)', pd.y + pd.h / 2 + 2, pd.h / 2 - 2, 1, 0, 1.5);
}

// ------------------------------------------------------------------ kola
function renderLaps(s) {
  const best = s.best ? s.best.time : null;
  const rows = (s.laps || []).slice().reverse().map((l) => {
    const comp = { 16: 'Soft', 17: 'Medium', 18: 'Hard', 7: 'Inter', 8: 'Wet' }[l.compound] || '';
    return `<tr class="${l.valid ? '' : 'inv'} ${l.time === best ? 'best' : ''}">
      <td>${l.lap}</td><td class="num">${fmtLap(l.time)}</td>
      <td class="num">${fmtSec(l.sectors[0])}</td><td class="num">${fmtSec(l.sectors[1])}</td><td class="num">${fmtSec(l.sectors[2])}</td>
      <td class="num ${l.delta > 0 ? 'loss' : 'gain'}">${l.delta !== undefined ? fmtDelta(l.delta, 3) : '–'}</td>
      <td>${comp}${l.tyre_age !== undefined ? ' ' + l.tyre_age : ''}</td>
      <td>${l.valid ? '' : '⚠️'}${l.clean ? '' : ' 🅿️'}</td></tr>`;
  });
  $('lapTable').querySelector('tbody').innerHTML = rows.join('') || '<tr><td colspan="8" class="muted">Zatím žádné laps.</td></tr>';
}

function loadHistory() {
  fetch('/api/history').then((r) => r.json()).then((h) => {
    const c = $('histChart'), ctx = c.getContext('2d');
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth, hh = 220;
    c.width = w * dpr; c.height = hh * dpr; c.style.height = hh + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, hh);
    const pts = h.filter((e) => e.valid && e.lap_ms);
    if (pts.length < 2) {
      ctx.fillStyle = '#8b93a7'; ctx.font = '15px -apple-system';
      ctx.fillText('Málo dat. Graf se ukáže po víc lapech.', 16, 40); return;
    }
    const ys = pts.map((p) => p.lap_ms);
    const min = Math.min(...ys), max = Math.min(Math.max(...ys), min * 1.06);
    ctx.fillStyle = '#8b93a7'; ctx.font = '11px -apple-system';
    ctx.fillText(fmtLap(min), 2, hh - 6); ctx.fillText(fmtLap(max), 2, 12);
    let bestSoFar = Infinity;
    pts.forEach((p, i) => {
      const x = 60 + (i / (pts.length - 1)) * (w - 70);
      const v = Math.min(p.lap_ms, max);
      const y = 10 + (1 - (v - min) / (max - min || 1)) * (hh - 20);
      const isBest = p.lap_ms < bestSoFar; if (isBest) bestSoFar = p.lap_ms;
      ctx.fillStyle = isBest ? '#a855f7' : '#e10600';
      ctx.beginPath(); ctx.arc(x, y, isBest ? 4 : 2.5, 0, Math.PI * 2); ctx.fill();
    });
  });
}

// ------------------------------------------------------------------ závod
function renderRace(s) {
  const r = s.race;
  if (!r) return;
  const f = r.fuel;
  if (f) {
    const d = f.game_delta_laps;
    $('fuelBig').textContent = (d > 0 ? '+' : '') + d.toFixed(2) + ' laps';
    $('fuelBig').style.color = d < 0 ? 'var(--red)' : 'var(--green)';
    $('fuelInfo').innerHTML = `Fuel in tank ${f.kg} kg · fuel delta z MFD ve hře` +
      (f.burn_per_lap ? `<br>Fuel burn ${f.burn_per_lap} kg/lap · ${f.laps_left} laps to go · můj odhad ${f.own_delta_laps > 0 ? '+' : ''}${f.own_delta_laps} laps` : '<br>Fuel burn spočítám po 2 lapech.');
  }
  const g = r.gaps || {};
  $('gapAhead').textContent = g.ahead ? fmtDelta(g.ahead).replace('+', '') + ' s' : '–';
  $('gapBehind').textContent = g.behind ? fmtDelta(g.behind).replace('+', '') + ' s' : '–';
  $('gapAheadTrend').innerHTML = g.ahead_trend === undefined ? '' :
    g.ahead_trend < 0 ? `<span class="gain">▼ stahuješ ${fmtDelta(-g.ahead_trend).replace('+', '')} s/lap</span>` +
      (g.catch_in_laps ? ` · dojedeš ho za ~${g.catch_in_laps} laps` : '')
      : `<span class="loss">▲ ujíždí ${fmtDelta(g.ahead_trend).replace('+', '')} s/lap</span>`;
  $('gapBehindTrend').innerHTML = g.behind_trend === undefined ? '' :
    g.behind_trend < 0 ? `<span class="loss">▼ dojíždí tě ${fmtDelta(-g.behind_trend).replace('+', '')} s/lap</span>`
      : `<span class="gain">▲ ztrácí ${fmtDelta(g.behind_trend).replace('+', '')} s/lap</span>`;
  const t = r.tyres;
  if (t) {
    $('tyreCompound').textContent = `· ${t.compound} (${t.actual}) · tyre age ${t.age} laps`;
    ['FL', 'FR', 'RL', 'RR'].forEach((w) => {
      const wear = t.wear ? t.wear[w] : null;
      const surf = t.surface ? t.surface[w] : null, inner = t.inner ? t.inner[w] : null;
      const el = $('t' + w);
      el.innerHTML = `<span>${w}</span><b>${wear !== null ? Math.round(wear) + ' %' : '–'}</b>` +
        `<span>${surf !== null ? surf + '° / ' + inner + '°' : ''}</span>`;
      el.style.borderColor = wear === null ? '' : wear > 60 ? 'var(--red)' : wear > 40 ? 'var(--yellow)' : 'var(--green)';
    });
    $('tyreInfo').textContent = (t.wear_per_lap ? `Tyre wear ${t.wear_per_lap} %/lap · 70 % za ~${t.laps_to_70} laps · ` : '') + 'surface / inner temp';
  }
  const p = r.pace;
  $('paceInfo').innerHTML = `Position <b>P${r.position}</b> · pit stops ${r.pit_stops}<br>` + (p ?
    `Last lap <b class="mono">${fmtLap(p.last)}</b> · avg 3 laps <b class="mono">${fmtLap(p.avg3)}</b><br>` +
    `Lap time trend <span class="${p.trend > 0 ? 'loss' : 'gain'}">${fmtDelta(p.trend, 3)} s</span>` : 'Pace spočítám po 2 lapech.');
}

// ------------------------------------------------------------------ hlas
function pickVoice(lang) {
  const voices = speechSynthesis.getVoices();
  const want = lang === 'en' ? ['en-GB', 'en-US', 'en'] : ['cs-CZ', 'cs'];
  for (const w of want) {
    const v = voices.find((x) => x.lang && x.lang.replace('_', '-').startsWith(w));
    if (v) return v;
  }
  return null;
}
function speak(text) {
  if (!radioOn || !('speechSynthesis' in window)) return;
  const lang = (S && S.settings.lang) || 'cs';
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang === 'en' ? 'en-GB' : 'cs-CZ';
  const v = pickVoice(lang); if (v) u.voice = v;
  u.rate = 1.08;
  speechSynthesis.speak(u);
}
function speakNew(msgs) {
  if (!msgs || !msgs.length) return;
  const maxId = msgs[msgs.length - 1].id;
  if (lastSpoken === null) { lastSpoken = maxId; return; }  // nečti historii po načtení
  msgs.filter((m) => m.id > lastSpoken).forEach((m) => {
    if (S.settings.voice !== false) speak(m.text);
  });
  lastSpoken = Math.max(lastSpoken, maxId);
}
let wakeLock = null;
$('radioBtn').onclick = async () => {
  radioOn = !radioOn;
  $('radioBtn').textContent = radioOn ? '🔊 Radio' : '🔇 Radio';
  $('radioBtn').className = radioOn ? 'radio-on' : 'radio-off';
  if (radioOn) {
    speak('Radio check.');
    try { if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen'); } catch (_) { /* nepodstatné */ }
  } else if ('speechSynthesis' in window) speechSynthesis.cancel();
};
if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = () => {};

// ------------------------------------------------------------------ chat
function addBubble(text, who) {
  const d = document.createElement('div');
  d.className = 'bubble ' + who; d.textContent = text;
  $('chat').appendChild(d); $('chat').scrollTop = 1e9;
}
async function ask(q) {
  if (!q) return;
  addBubble(q, 'me');
  $('askInput').value = '';
  try {
    const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q }) });
    const d = await r.json();
    addBubble(d.text || d.error, 'eng');
  } catch (e) { addBubble('Spojení se serverem selhalo.', 'eng'); }
}
$('askForm').onsubmit = (e) => { e.preventDefault(); ask($('askInput').value.trim()); };
document.querySelectorAll('.quick button').forEach((b) => { b.onclick = () => ask(b.dataset.q); });
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) $('micBtn').title = 'Diktování: použij mikrofon na klávesnici iOS';
$('micBtn').onclick = () => {
  if (!SR) { $('askInput').focus(); return; }
  const rec = new SR();
  rec.lang = (S && S.settings.lang === 'en') ? 'en-GB' : 'cs-CZ';
  rec.interimResults = false;
  $('micBtn').textContent = '⏺️';
  rec.onresult = (e) => ask(e.results[0][0].transcript);
  rec.onend = () => { $('micBtn').textContent = '🎙️'; };
  rec.onerror = () => { $('micBtn').textContent = '🎙️'; $('askInput').focus(); };
  rec.start();
};

// ------------------------------------------------------------------ nastavení
function fillSettings(s) {
  const st = s.settings;
  $('sLang').value = st.lang; $('sLevel').value = String(st.level); $('sRef').value = st.reference;
  $('sAi').value = st.difficulty_override === null || st.difficulty_override === undefined ? '' : st.difficulty_override;
  $('sVoice').checked = st.voice !== false;
  $('sKey').value = s.has_gemini ? '***' : '';
  $('sModel').value = st.gemini_model || '';
  settingsLoaded = true;
}
$('saveBtn').onclick = async () => {
  const ai = $('sAi').value.trim();
  const body = {
    lang: $('sLang').value, level: parseInt($('sLevel').value, 10), reference: $('sRef').value,
    difficulty_override: ai === '' ? null : parseInt(ai, 10), voice: $('sVoice').checked,
    gemini_key: $('sKey').value.trim(), gemini_model: $('sModel').value.trim() || 'gemini-2.5-flash',
  };
  await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  $('saveBtn').textContent = 'Uloženo ✓';
  setTimeout(() => { $('saveBtn').textContent = 'Uložit'; }, 1500);
};
$('resetCorners').onclick = async () => {
  await fetch('/api/reset_corners', { method: 'POST' });
  trackVersion = -1;
};

connect();
