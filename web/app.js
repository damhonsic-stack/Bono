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
let lastHeardTs = null;
let lastZones = '';

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
    if (b.dataset.tab === 'debrief') { loadDebriefs(); if (!recapData) loadRecap(); }
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
  $('aiMode').textContent = (s.has_gemini || s.has_groq)
    ? `AI online (${[s.has_groq && 'Groq', s.has_gemini && 'Gemini'].filter(Boolean).join(' + ')})${s.llm && s.llm.model ? ' · ' + s.llm.model : ''}${s.llm && s.llm.error ? ' · poslední chyba: ' + s.llm.error : ''}`
    : 'Offline režim. Pro chytřejší odpovědi vlož Gemini klíč v Nastavení.';

  const zKey = JSON.stringify((s.regs && (s.regs.aero_zones || s.regs.drs_zones)) || []);
  if (zKey !== lastZones) { lastZones = zKey; drawMap(); }
  if (s.track_version !== trackVersion) {
    trackVersion = s.track_version;
    fetch('/api/track').then((r) => r.json()).then((t) => { track = t; drawMap(); });
  }
  if (s.compare_lap !== compareLap) {
    compareLap = s.compare_lap;
    if (document.querySelector('#tab-corners.active')) loadCompare(false);
  }
  speakNew(s.messages);
  if (listenSeq === null) listenSeq = s.listen_seq;
  if (s.listen_seq !== listenSeq) { listenSeq = s.listen_seq; Voice.listenNow(); }
  renderRegs(s);
  renderStrip(s);
  $('muteBtn').textContent = s.settings.voice === false ? '🔊 Unmute' : '🔇 Mute';
  if (s.heard && s.heard.ts !== lastHeardTs) {        // přepis z mikrofonu Macu (Whisper)
    lastHeardTs = s.heard.ts;
    const tag = { ignore: '  (bez „Bono“ – ignoruji)', arm: '  → poslouchám…', ask: '  ✓' }[s.heard.action] || '';
    showHeard(s.heard.text + tag, true);
  }
  const vd = s.voice_devices || {};
  if (!radioOn && vd.count) {
    $('micState').textContent = `🎧 Bono on ${vd.names.join(', ')}`;
    $('micState').className = 'mic wake';
    $('micHint').classList.add('hidden');
  }
  $('pad').querySelector('.talk').classList.toggle('live', Voice.mode === 'command' && Voice.on);
  if (document.querySelector('#tab-strat.active')) renderStrategy(s);
  if (document.querySelector('#tab-debrief.active')) renderSetup(s);
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

// ------------------------------------------------------------------ regulace 2026
function renderRegs(s) {
  const r = s.regs || {};
  $('fmt').textContent = s.format ? `UDP ${s.format}` : '';
  const live = r.active && r.aero;
  cls($('regsLive'), 'hidden', !live && !(r.ers && s.format === 2026));
  if (r.aero) {
    $('aeroMode').textContent = r.aero.mode.toUpperCase();
    $('aeroInfo').textContent = r.aero.available ? 'zone available' :
      (r.aero.distance ? `in ${r.aero.distance} m` : '');
    $('aeroBox').className = 'reg ' + (r.aero.mode === 'Straight' ? 'on' : (r.aero.available ? 'warn' : ''));
    if (r.aero_status === 'Partial') $('aeroInfo').textContent += ' · PARTIAL';
  }
  if (r.overtake) {
    const o = r.overtake;
    $('otState').textContent = o.active ? 'ACTIVE' : o.available ? 'READY' : '–';
    $('otInfo').textContent = !o.active && !o.available && o.distance ? `in ${o.distance} m` : '';
    $('otBox').className = 'reg ' + (o.active ? 'hot' : o.available ? 'on' : '');
  }
  if (r.ers) {
    const e = r.ers;
    $('ersPct').textContent = e.pct + ' %';
    $('ersBar').style.width = Math.min(100, e.pct) + '%';
    $('ersInfo').textContent = `${e.mode}` + (e.harvest_left_mj !== undefined ? ` · harvest left ${e.harvest_left_mj} MJ` : '');
  }
  if (document.querySelector('#tab-race.active')) {
    if (!r.ers) { $('ersRace').textContent = 'Jen s UDP formátem 2026 (Season Pass).'; return; }
    const e = r.ers, last = r.last_lap || {};
    $('ersRace').innerHTML =
      `Battery <b>${e.pct} %</b> (${e.store_mj} MJ) · deploy mode <b>${e.mode}</b><br>` +
      `This lap: deployed ${e.deployed_lap_mj} MJ · harvested ${e.harvested_lap_mj} MJ` +
      (e.harvest_limit_mj ? ` / limit ${e.harvest_limit_mj} MJ` : '') + '<br>' +
      (r.aero ? `Active aero <b>${r.aero.mode}</b>${r.aero_status ? ' · track status ' + r.aero_status : ''}<br>` : '') +
      (r.overtake ? `Overtake mode <b>${r.overtake.active ? 'ACTIVE' : r.overtake.available ? 'READY' : 'not available'}</b><br>` : '') +
      (last.straight_pct !== undefined ? `Last lap: straight mode ${last.straight_pct} % of zones · overtake used ${last.ot_uses || 0}×` : '');
  }
}

// ------------------------------------------------------------------ strategie, soupeři, incidenty
function planText(p) {
  if (!p) return '–';
  if (!p.stops) return 'No stop – to the end';
  return `${p.stops}-stop: ` + p.laps.map((k, i) => `L${k} → ${p.tyres[i]}`).join(', ');
}
function renderStrip(s) {
  const parts = [];
  const inc = s.incidents || {};
  if (inc.sc) parts.push(`<span class="sc">${inc.sc}</span>`);
  const p = s.strategy && s.strategy.plan;
  if (p && p.stops && s.live) parts.push(`<span>Box L${p.laps[0]} → ${p.tyres[0]}</span>`);
  if (inc.track_limits) parts.push(`<span class="${inc.track_limits >= 3 ? 'warn' : ''}">Track limits ${inc.track_limits}</span>`);
  if (inc.penalty_s) parts.push(`<span class="warn">+${inc.penalty_s} s penalty</span>`);
  const q = s.quali;
  if (q && q.status && s.session && s.session.type_id !== 15 && s.session.type_id !== 16 && s.session.type_id !== 17) {
    parts.push(`<span>${q.status}</span>`);
    if (q.ahead_s !== null && q.ahead_s < 10) parts.push(`<span>Car ahead on track ${q.ahead_s} s</span>`);
  }
  const dmg = inc.damage || {};
  const worst = Object.entries(dmg).sort((a, b) => b[1] - a[1])[0];
  if (worst) parts.push(`<span class="warn">${worst[0].replace('_', ' ')} ${worst[1]} %</span>`);
  $('liveStrip').innerHTML = parts.join('');
}
function renderStrategy(s) {
  const st = s.strategy || {};
  const p = st.plan;
  $('planBig').textContent = planText(p);
  const info = [];
  if (p && p.alt) info.push(`Alternative ${p.alt.stops}-stop: +${(p.alt.delta_ms / 1000).toFixed(1)} s`);
  if (p && p.window) info.push(`Optimal window for first stop: lap ${p.window[0]}–${p.window[1]}`);
  if (st.game_window && st.game_window[0]) info.push(`Game pit window: ideal lap ${st.game_window[0]}, latest ${st.game_window[1]}`);
  info.push(`Pit loss ${(st.pit_loss_ms / 1000).toFixed(1)} s` + (st.pit_loss_measured ? ` (measured from ${st.pit_loss_measured} stops)` : ' (estimate)'));
  if (st.rejoin) {
    const r = st.rejoin;
    let t = `If you box now: rejoin P${r.pos}`;
    if (r.ahead) t += ` · ${(r.ahead.gap / 1000).toFixed(1)} s behind ${esc(r.ahead.name)}`;
    if (r.behind) t += ` · ${(r.behind.gap / 1000).toFixed(1)} s ahead of ${esc(r.behind.name)}`;
    info.push(t);
  }
  $('planInfo').innerHTML = info.join('<br>');
  $('degInfo').innerHTML = (st.stints || []).map((x) =>
    `${x.tyre} from lap ${x.start_lap}: <b>${(x.deg_ms / 1000).toFixed(3)} s/lap</b> <span class="muted">(${x.deg_src}, ${x.points} laps)</span>`).join('<br>') || 'Spočítám po pár čistých lapech v závodě.';
  if (st.sets) {
    const groups = {};
    st.sets.forEach((t) => {
      const k = t.fitted ? 'fitted' : `${t.tyre}|${t.wear}|${t.life_left}|${t.delta}`;
      (groups[k] = groups[k] || { ...t, n: 0 }).n++;
    });
    $('setsInfo').innerHTML = Object.values(groups).map((t) => t.fitted
      ? `▶ <b>${t.tyre}</b> (fitted) · wear ${t.wear} % · ${t.life_left} laps left`
      : `${t.n}× ${t.tyre} · ${t.wear ? 'used ' + t.wear + ' %' : 'new'} · life ${t.life_left} laps · ` +
        `<span class="${t.delta < 0 ? 'gain' : 'loss'}">${t.delta > 0 ? '+' : ''}${(t.delta / 1000).toFixed(2)} s/lap</span> vs fitted`).join('<br>');
  } else $('setsInfo').textContent = 'Žádná data o sadách.';
  // počasí
  const w = s.weather || {};
  $('wxNow').textContent = w.now ? `${w.now} · track ${w.track_temp}°C` : '–';
  $('wxForecast').innerHTML = (w.forecast || []).map((f) =>
    `<div class="${f.rain >= 40 ? 'rain' : ''}">+${f.min} min<br><b>${esc(f.weather || '?')}</b><br>${f.rain} %</div>`).join('');
  // auta kolem
  $('aroundTable').querySelector('tbody').innerHTML = (s.around || []).map((c) => `
    <tr class="${c.me ? 'me' : ''}"><td>P${c.pos}</td><td>${esc(c.name)}${c.in_pit ? ' 🅿️' : ''}</td>
    <td class="num">${c.me ? '–' : (c.gap > 0 ? '+' : '') + (c.gap / 1000).toFixed(1)}</td>
    <td>${c.tyre}${c.age !== null && c.age !== undefined ? ' ' + c.age : ''}</td><td>${c.pits}</td>
    <td class="num">${fmtLap(c.last)}</td>
    <td class="num ${c.pace_delta < 0 ? 'loss' : 'gain'}">${c.pace_delta === null ? '–' : fmtDelta(c.pace_delta)}</td></tr>`).join('')
    || '<tr><td colspan="7" class="muted">Jen v závodě.</td></tr>';
  // incidenty
  const inc = s.incidents || {};
  const dmg = Object.entries(inc.damage || {}).map(([k, v]) => `${k.replace('_', ' ')} ${v} %`).join(', ');
  $('incInfo').innerHTML = `Warnings ${inc.warnings || 0} · track limits ${inc.track_limits || 0} · time penalties ${inc.penalty_s || 0} s` +
    (inc.unserved_dt ? ` · <b class="red">drive through to serve</b>` : '') + (inc.unserved_sg ? ` · <b class="red">stop & go to serve</b>` : '') +
    `<br>Damage: ${dmg || 'none'}` + (inc.sc ? `<br><b>${inc.sc}</b>` : '');
}
function renderSetup(s) {
  const su = s.setup || {};
  const bal = su.balance || {};
  const rows = ['entry', 'mid', 'exit'].map((ph) => `<tr><td><b>${ph}</b></td>` + ['slow', 'medium', 'fast'].map((sp) => {
    const b = bal[`${ph}_${sp}`];
    return b ? `<td class="bal-${b.state}">${b.state} <span class="muted">(${b.ratio})</span></td>` : '<td class="muted">–</td>';
  }).join('') + '</tr>');
  $('balanceTable').querySelector('tbody').innerHTML = rows.join('');
  const t = su.avg_surface_temps;
  $('balanceInfo').textContent = `Lock-ups front ${su.lockups ? su.lockups.front : 0} / rear ${su.lockups ? su.lockups.rear : 0} · wheelspin ${su.wheelspin || 0}` +
    (t ? ` · avg surface temps FL ${t.FL}° FR ${t.FR}° RL ${t.RL}° RR ${t.RR}°` : '');
  const adv = su.advice || [];
  $('setupAdvice').innerHTML = adv.length ? adv.map((a) =>
    `<div class="advice"><b>${esc(a.issue)}</b>${esc(a.change)}${a.current ? `<i> · ${esc(a.current)}</i>` : ''}</div>`).join('')
    : '<span class="muted">Zatím bez doporučení. Odjeď pár čistých lapů.</span>';
}
let debriefsLoaded = 0;
let debriefList = [];
function showDebrief(d) {
  $('debriefText').textContent = d.text;
  if (d.summary && d.summary.recap) { recapData = d.summary.recap; recapSource = `uložený debrief ${new Date(d.ts * 1000).toLocaleString('cs-CZ')}`; renderRecap(); }
}
function loadDebriefs() {
  fetch('/api/debriefs').then((r) => r.json()).then((list) => {
    debriefList = list;
    if (!list.length) { loadRecap(); return; }
    const d = list[0];
    showDebrief(d);
    $('debriefOld').innerHTML = `${new Date(d.ts * 1000).toLocaleString('cs-CZ')} · ${esc(d.track)} ${esc(d.session)} · ${d.source}` +
      (list.length > 1 ? '<br>Starší: ' + list.slice(1, 8).map((x, i) =>
        `<span class="debrief-item" data-i="${i + 1}">${esc(x.track)} ${esc(x.session)} ${new Date(x.ts * 1000).toLocaleDateString('cs-CZ')}</span>`).join(' · ') : '');
    $('debriefOld').querySelectorAll('.debrief-item').forEach((el) => {
      el.onclick = () => showDebrief(debriefList[+el.dataset.i]);
    });
    debriefsLoaded = list.length;
  });
}

// ------------------------------------------------------------------ post-race recap
let recapData = null, recapMode = 'avg', recapSource = '';
function loadRecap() {
  fetch('/api/recap').then((r) => r.json()).then((rc) => { recapData = rc; recapSource = 'aktuální session'; renderRecap(); });
}
document.querySelectorAll('#recapModes button').forEach((b) => {
  b.onclick = () => {
    if (b.dataset.mode === 'live') { loadRecap(); return; }
    recapMode = b.dataset.mode;
    document.querySelectorAll('#recapModes button').forEach((x) => x.classList.toggle('active', x === b));
    renderRecap();
  };
});
const RECAP_KEY = { avg: 'avg_loss', best: 'best_vs_avg', worst: 'worst_vs_avg' };
function lossColor(t) {   // t: -1 (zisk) … 0 … 1 (ztráta)
  if (t <= 0) { const a = Math.min(1, -t); return `rgb(${Math.round(34 + (90 - 34) * (1 - a))},${Math.round(197)},${Math.round(94 + 60 * (1 - a))})`; }
  t = Math.min(1, t);
  if (t < 0.5) { const k = t / 0.5; return `rgb(${Math.round(34 + (250 - 34) * k)},${Math.round(197 + (204 - 197) * k)},${Math.round(94 - 73 * k)})`; }
  const k = (t - 0.5) / 0.5; return `rgb(${Math.round(250 - 11 * k)},${Math.round(204 - 136 * k)},${Math.round(21 + 47 * k)})`;
}
function renderRecap() {
  const rc = recapData;
  $('recapSrc').textContent = recapSource ? `· ${recapSource}` : '';
  drawRecapMap();
  if (!rc) return;
  // highlights
  const lines = (rc.text || []).map((t) => `<div>${esc(t)}</div>`);
  if (rc.ok) lines.push(`<div>Best lap <b>${fmtLap(rc.best_lap.time)}</b> (lap ${rc.best_lap.lap}) · worst <b>${fmtLap(rc.worst_lap.time)}</b> (lap ${rc.worst_lap.lap}) · ideální kolo z nejlepších úseků <b class="purple">${fmtLap(rc.ideal_time)}</b></div>`);
  $('recapHigh').innerHTML = lines.join('') || esc(rc.reason || 'Zatím málo dat.');
  // sektory
  const sec = rc.sectors;
  if (sec) {
    const rows = [['Best lap', sec.best], ['Worst lap', sec.worst], ['Průměr', sec.avg], ['Ideál (nejlepší sektory)', sec.ideal]];
    $('recapSectors').querySelector('tbody').innerHTML = rows.map(([name, r]) => `<tr><td><b>${name}</b></td><td>${r.lap || '–'}</td>` +
      r.s.map((v, i) => {
        const d = v - sec.ideal.s[i];
        const c = d === 0 ? 'cool' : (d > 150 ? 'hot' : '');
        return `<td class="num ${c}">${fmtSec(v)}${d ? ` <span class="${d > 0 ? 'loss' : 'gain'}">${fmtDelta(d)}</span>` : ''}</td>`;
      }).join('') + `<td class="num"><b>${fmtLap(r.time)}</b></td></tr>`).join('');
  }
  // zatáčky
  const turns = rc.corners || [];
  const worstIds = new Set((rc.highlights ? rc.highlights.most_loss : []).map((x) => x.turn));
  const bestIds = new Set((rc.highlights ? rc.highlights.least_loss : []).map((x) => x.turn));
  $('recapTurns').querySelector('tbody').innerHTML = turns.map((t) => `<tr>
    <td><b>${t.name}</b></td>
    <td class="num ${worstIds.has(t.name) ? 'hot' : bestIds.has(t.name) ? 'cool' : ''}">${fmtDelta(t.avg_loss, 3)}</td>
    <td class="num ${t.best_vs_avg < 0 ? 'gain' : 'loss'}">${fmtDelta(t.best_vs_avg, 3)}</td>
    <td class="num ${t.worst_vs_avg > 0 ? 'loss' : 'gain'}">${fmtDelta(t.worst_vs_avg, 3)}</td>
    <td>${esc((t.worst_tips || []).join('; ') || '–')}</td></tr>`).join('') ||
    '<tr><td colspan="5" class="muted">Potřebuju aspoň 2 čistá kola s analýzou zatáček.</td></tr>';
}
function drawRecapMap() {
  const c = $('recapMap');
  if (!c || !c.clientWidth) return;
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight || 360;
  c.width = w * dpr; c.height = h * dpr;
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  const rc = recapData;
  const o = rc && rc.outline;
  if (!o || !o.x || !o.x.length) {
    ctx.fillStyle = '#8b93a7'; ctx.font = '15px -apple-system'; ctx.fillText('Mapa se ukáže po prvním čistém kole.', 16, 36); return;
  }
  const minX = Math.min(...o.x), maxX = Math.max(...o.x), minZ = Math.min(...o.z), maxZ = Math.max(...o.z);
  const pad = 34, sc = Math.min((w - 2 * pad) / (maxX - minX || 1), (h - 2 * pad) / (maxZ - minZ || 1));
  const ox = (w - (maxX - minX) * sc) / 2, oz = (h - (maxZ - minZ) * sc) / 2;
  const P = (x, z) => [ox + (x - minX) * sc, oz + (z - minZ) * sc];
  const turns = rc.corners || [];
  const key = RECAP_KEY[recapMode];
  const vals = turns.map((t) => t[key]);
  const scale = Math.max(30, ...vals.map(Math.abs));
  const turnAt = (d) => turns.find((t) => d >= t.start && d <= t.end);
  // podklad
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.lineWidth = 12; ctx.strokeStyle = '#232a38';
  ctx.beginPath(); o.x.forEach((x, i) => { const [px, pz] = P(x, o.z[i]); i ? ctx.lineTo(px, pz) : ctx.moveTo(px, pz); }); ctx.closePath(); ctx.stroke();
  // úseky obarvené podle ztráty
  ctx.lineWidth = 7;
  for (let i = 0; i < o.x.length - 1; i++) {
    const t = turnAt(o.dist[i]);
    if (!t) continue;
    let v = t[key] / scale;
    if (recapMode === 'avg') v = Math.max(0, v);
    ctx.strokeStyle = lossColor(v);
    const [a, b] = P(o.x[i], o.z[i]), [c2, d] = P(o.x[i + 1], o.z[i + 1]);
    ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c2, d); ctx.stroke();
  }
  // hranice sektorů
  (rc.sector_starts || []).forEach((sd, k) => {
    if (sd === null || sd === undefined) return;
    let j = 0; while (j < o.dist.length - 1 && o.dist[j] < sd) j++;
    const [px, pz] = P(o.x[j], o.z[j]);
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(px, pz, 5, 0, Math.PI * 2); ctx.fill();
    ctx.font = 'bold 11px -apple-system'; ctx.fillStyle = '#cbd5e1';
    ctx.fillText(k === 0 ? 'START / S1' : 'S' + (k + 1), px + 8, pz + 16);
  });
  // popisky zatáček s hodnotou
  turns.forEach((t) => {
    const [px, pz] = P(t.x, t.z);
    const v = t[key];
    const label = `${t.name} ${fmtDelta(v)}`;
    ctx.font = 'bold 12px -apple-system';
    const tw = ctx.measureText(label).width + 10;
    ctx.fillStyle = 'rgba(11,13,18,.85)'; ctx.fillRect(px - tw / 2, pz - 24, tw, 18);
    ctx.fillStyle = lossColor(recapMode === 'avg' ? Math.max(0, v / scale) : v / scale);
    ctx.textAlign = 'center'; ctx.fillText(label, px, pz - 11); ctx.textAlign = 'left';
  });
}
window.addEventListener('resize', () => { if (document.querySelector('#tab-debrief.active')) drawRecapMap(); });

$('debriefBtn').onclick = async () => {
  $('debriefBtn').textContent = '⏳ Generating…';
  await fetch('/api/debrief', { method: 'POST' });
  setTimeout(() => { loadDebriefs(); $('debriefBtn').textContent = '📝 Generate debrief now'; }, 4000);
  setTimeout(loadDebriefs, 12000);
};

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
  // active aero zóny (2026) / DRS zóny – zlomky délky kola
  const regs = (S && S.regs) || {};
  const zones = (regs.aero_zones && regs.aero_zones.length) ? regs.aero_zones : (regs.drs_zones || []);
  if (zones.length && o.dist.length) {
    const L = o.dist[o.dist.length - 1] || 1;
    ctx.lineWidth = 6; ctx.strokeStyle = regs.aero_status === 'Partial' ? '#f59e0b' : '#38bdf8';
    zones.forEach(([a, b]) => {
      const segs = b >= a ? [[a, b]] : [[a, 1], [0, b]];
      segs.forEach(([za, zb]) => {
        ctx.beginPath(); let started = false;
        o.dist.forEach((d, i) => {
          const f = d / L;
          if (f < za || f > zb) return;
          const [px, pz] = g.P(o.x[i], o.z[i]);
          started ? ctx.lineTo(px, pz) : ctx.moveTo(px, pz); started = true;
        });
        ctx.stroke();
      });
    });
  }
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
      <td class="num ${l.straight_pct !== undefined && l.straight_pct < 90 ? 'loss' : ''}">${l.straight_pct !== undefined ? l.straight_pct + '%' : '–'}</td>
      <td class="num">${l.ot_uses !== undefined ? l.ot_uses : '–'}</td>
      <td>${l.valid ? '' : '⚠️'}${l.clean ? '' : ' 🅿️'}</td></tr>`;
  });
  $('lapTable').querySelector('tbody').innerHTML = rows.join('') || '<tr><td colspan="10" class="muted">Zatím žádné laps.</td></tr>';
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

// ------------------------------------------------------------------ hlas (výstup)
function lang() { return (S && S.settings.lang) || 'en'; }
function pickVoice(l) {
  const voices = speechSynthesis.getVoices();
  const want = l === 'cs' ? ['cs-CZ', 'cs'] : ['en-GB', 'en-US', 'en'];
  for (const w of want) {
    const v = voices.find((x) => x.lang && x.lang.replace('_', '-').startsWith(w));
    if (v) return v;
  }
  return null;
}
// Fronta rádia: urgentní hlášení jdou dopředu. Hlas iOS = okamžitě, Gemini hlas = realističtější
// (s rádiovým filtrem), ale o 2–4 s později; při chybě se použije iOS.
function speakIOS(text) {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang() === 'cs' ? 'cs-CZ' : 'en-GB';
    const v = pickVoice(lang()); if (v) u.voice = v;
    u.rate = 1.08;
    const t = setTimeout(resolve, 2500 + text.length * 90);   // pojistka, když onend nepřijde
    u.onend = u.onerror = () => { clearTimeout(t); resolve(); };
    beep(660, 0.05, 0.04);
    speechSynthesis.speak(u);
  });
}

let radioNoise = null;
function squelch(when, dur = 0.07, vol = 0.05) {
  if (!audioCtx) return;
  if (!radioNoise) {
    radioNoise = audioCtx.createBuffer(1, audioCtx.sampleRate * 0.3, audioCtx.sampleRate);
    const d = radioNoise.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  const src = audioCtx.createBufferSource(); src.buffer = radioNoise;
  const bp = audioCtx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 1800; bp.Q.value = 0.8;
  const g = audioCtx.createGain(); g.gain.value = vol;
  src.connect(bp); bp.connect(g); g.connect(audioCtx.destination);
  src.start(when); src.stop(when + dur);
}

function radioChain() {
  // týmové rádio: pásmová propust ~300–3400 Hz, lehké zkreslení a komprese
  const hp = audioCtx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 320;
  const lp = audioCtx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 3300;
  const ws = audioCtx.createWaveShaper();
  const curve = new Float32Array(1024);
  for (let i = 0; i < 1024; i++) { const x = i / 512 - 1; curve[i] = Math.tanh(2.2 * x) / Math.tanh(2.2); }
  ws.curve = curve;
  const comp = audioCtx.createDynamicsCompressor(); comp.threshold.value = -24; comp.ratio.value = 6;
  const g = audioCtx.createGain(); g.gain.value = 1.3;
  hp.connect(lp); lp.connect(ws); ws.connect(comp); comp.connect(g); g.connect(audioCtx.destination);
  return hp;
}

async function playGemini(m) {
  if (!audioCtx) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), m.urgent ? 3000 : 8000);
  let buf;
  try {
    const r = await fetch('/api/tts?id=' + m.id, { signal: ctrl.signal });
    if (r.status !== 200) return false;
    buf = await audioCtx.decodeAudioData(await r.arrayBuffer());
  } catch (_) { return false; } finally { clearTimeout(timer); }
  return new Promise((resolve) => {
    const src = audioCtx.createBufferSource(); src.buffer = buf;
    src.connect(radioChain());
    const t0 = audioCtx.currentTime + 0.08;
    squelch(audioCtx.currentTime);
    src.start(t0);
    src.onended = () => { squelch(audioCtx.currentTime, 0.09); setTimeout(() => resolve(true), 120); };
  });
}

const Radio = {
  queue: [], busy: false,
  push(m) { if (m.urgent) this.queue.unshift(m); else this.queue.push(m); this.next(); },
  async next() {
    if (this.busy || !this.queue.length) return;
    if (!radioOn) { this.queue = []; return; }
    this.busy = true;
    const m = this.queue.shift();
    Voice.pause();  // ať Bono neslyší sám sebe
    try {
      const stale = !m.urgent && Date.now() / 1000 - m.ts > 30;
      if (!stale) {
        const eng = (S && S.settings.voice_engine) || 'mixed';
        const useGemini = S && S.has_gemini && eng !== 'ios' && !m.urgent &&
          (eng === 'gemini' || m.prio >= 2) && !(S.tts && S.tts.available === false);
        if (!(useGemini && await playGemini(m))) await speakIOS(m.text);
      }
    } catch (_) { /* pokračuj */ }
    this.busy = false;
    if (!this.queue.length) Voice.resume();
    this.next();
  },
};
function speak(text) { Radio.push({ id: -1, text, urgent: true, ts: Date.now() / 1000 }); }
function speakNew(msgs) {
  if (!msgs || !msgs.length) return;
  if (msgs.some((m) => m.id > (lastSpoken || 0) && /debrief/i.test(m.text))) setTimeout(loadDebriefs, 500);
  const maxId = msgs[msgs.length - 1].id;
  if (lastSpoken === null) { lastSpoken = maxId; return; }  // nečti historii po načtení
  msgs.filter((m) => m.id > lastSpoken).forEach((m) => {
    if (radioOn && (S.settings.voice !== false || m.prio === 3)) Radio.push(m);
  });
  lastSpoken = Math.max(lastSpoken, maxId);
}

let audioCtx = null;
function beep(freq = 880, dur = 0.12, vol = 0.15) {
  try {
    if (!audioCtx) return;
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = freq; g.gain.value = vol;
    o.connect(g); g.connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + dur);
  } catch (_) { /* bez zvuku */ }
}

// ------------------------------------------------------------------ hlas (vstup): wake word "Bono"
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const Voice = {
  rec: null, on: false, paused: false, mode: 'wake', cmdTimer: null, restartTimer: null, errors: 0,
  open: (() => { try { return localStorage.getItem('bonoOpenMic') === '1'; } catch (_) { return false; } })(),
  wakeRe() {
    const w = ((S && S.settings.wake_word) || 'bono').toLowerCase().replace(/[^a-z0-9áéíóúůýčďěňřšťž ]/g, '');
    // rozpoznávání často slyší „Bonnie“, „bone oh“, „bueno“… → bereme podobná slova
    const variants = w === 'bono'
      ? 'b[ou]n+[aeiouy]{1,2}[a-z]{0,3}|bone ?oh?|bo no|buono|bueno|bonneau|bonó|volno' : w;
    return new RegExp('\\b(?:hey |ok )?(?:' + variants + ')\\b[,.!? ]*', 'i');
  },
  supported() { return !!SR; },
  start() {
    if (!SR) { setMic('off', 'Voice not supported in this browser, use the controller buttons'); return false; }
    this.on = true; this.errors = 0; this.mode = 'wake';
    this._create(); this._go();
    return true;
  },
  stop() {
    this.on = false; clearTimeout(this.restartTimer); clearTimeout(this.cmdTimer);
    try { this.rec && this.rec.abort(); } catch (_) { /* */ }
    setMic('off');
  },
  pause() { if (!this.on) return; this.paused = true; try { this.rec && this.rec.abort(); } catch (_) { /* */ } },
  resume() { if (!this.on || !this.paused) return; this.paused = false; this._go(250); },
  listenNow() {  // tlačítko na ovladači / klepnutí: poslouchej příkaz bez wake wordu
    if (!this.on) return;
    this.mode = 'command'; beep(880, 0.12);
    setMic('cmd');
    clearTimeout(this.cmdTimer);
    this.cmdTimer = setTimeout(() => { this.mode = 'wake'; setMic(this.open ? 'open' : 'wake'); }, 8000);
  },
  _create() {
    const rec = new SR();
    rec.lang = lang() === 'cs' ? 'cs-CZ' : 'en-GB';
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => this._onResult(e);
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        this.on = false;
        setMic('off', 'Microphone blocked. Allow mic & speech recognition for Safari, server must run on http://localhost (iPad) or use controller buttons.');
      } else if (e.error !== 'aborted' && e.error !== 'no-speech') {
        this.errors++;
      }
    };
    rec.onend = () => { if (this.on && !this.paused) this._go(this.errors > 5 ? 3000 : 300); };
    this.rec = rec;
  },
  _go(delay = 0) {
    clearTimeout(this.restartTimer);
    this.restartTimer = setTimeout(() => {
      if (!this.on || this.paused) return;
      try { this.rec.start(); setMic(this.mode === 'command' ? 'cmd' : (this.open ? 'open' : 'wake')); } catch (_) { /* už běží */ }
    }, delay);
  },
  _onResult(e) {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      const text = r[0].transcript.trim();
      if (!text) continue;
      const m = text.match(this.wakeRe());
      showHeard(text, r.isFinal);
      if (!r.isFinal) {
        if (m || this.mode === 'command') setMic('cmd', text);
        continue;
      }
      if (this.open && this.mode !== 'command') {          // open mic: každá věta je otázka
        const q = text.replace(this.wakeRe(), '').trim();
        if (!FILLER.test(q.toLowerCase())) this._submit(q);
        continue;
      }
      if (this.mode === 'command') {
        clearTimeout(this.cmdTimer); this.mode = 'wake';
        this._submit(text.replace(this.wakeRe(), ''));
      } else if (m) {
        const rest = text.slice(m.index + m[0].length).trim();
        if (rest.length > 2) this._submit(rest);
        else this.listenNow();
      }
    }
  },
  _submit(q) {
    q = q.trim();
    setMic(this.open ? 'open' : 'wake');
    if (!q) return;
    beep(520, 0.08);
    ask(q, true);
  },
};

const FILLER = /^(|ok|okay|yeah|yes|yep|no|nope|thanks|thank you|cheers|uh|um|hmm|ah|oh|copy|jo|jasně|dík|díky|ne|ano)[.!?]?$/;
let heardTimer = null;
function showHeard(text, final) {
  const el = $('heard');
  if (!el) return;
  el.textContent = 'Slyším: ' + text + (final ? '' : ' …');
  el.classList.remove('hidden');
  clearTimeout(heardTimer);
  heardTimer = setTimeout(() => el.classList.add('hidden'), 6000);
}
function setOpenMic(on) {
  Voice.open = on;
  try { localStorage.setItem('bonoOpenMic', on ? '1' : '0'); } catch (_) { /* */ }
  $('openMicBtn').textContent = on ? '🎙️ Open mic: ON' : '🎙️ Open mic: OFF';
  $('openMicBtn').className = on ? 'radio-on' : 'radio-off';
  if (on && !radioOn) startBono();          // klepnutí = povolení zvuku i mikrofonu
  if (Voice.on) setMic(on ? 'open' : 'wake');
}

function setMic(state, detail) {
  const el = $('micState');
  const name = (S && S.settings.engineer_name) || 'Bono';
  const labels = {
    off: '🎙️ off', wake: `👂 say “${name}”`, cmd: `🔴 ${name} listening…`, open: `🟢 ${name} is listening`,
  };
  el.textContent = labels[state] || state;
  el.className = 'mic ' + state;
  el.title = detail || '';
  if (detail && state === 'cmd') el.textContent = '🔴 ' + detail.slice(-40);
  if (detail && state === 'off') { $('micHint').textContent = detail; $('micHint').classList.remove('hidden'); }
  else $('micHint').classList.add('hidden');
}

let wakeLock = null;
let listenSeq = null;
async function startBono() {
  if (radioOn) return;
  radioOn = true;
  // iOS: hlas, zvuk i mikrofon se musí odemknout SYNCHRONNĚ v reakci na klepnutí (bez await předtím)
  const name = (S && S.settings.engineer_name) || 'Bono';
  speakIOS(lang() === 'cs' ? `${name} tady. Slyšíme se.` : `${name} here. Radio check, loud and clear.`);
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
  } catch (_) { /* bez zvuku */ }
  Voice.start();
  try { if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen'); } catch (_) { /* nepodstatné */ }
  $('bonoBtn').textContent = '⏹ Stop';
  $('bonoBtn').className = 'radio-on';
}
function stopBono() {
  radioOn = false;
  Voice.stop();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  try { wakeLock && wakeLock.release(); } catch (_) { /* */ }
  $('bonoBtn').textContent = '▶ Start Bono';
  $('bonoBtn').className = 'radio-off';
}
$('bonoBtn').onclick = () => (radioOn ? stopBono() : startBono());
$('openMicBtn').onclick = () => setOpenMic(!Voice.open);
setTimeout(() => setOpenMic(Voice.open && false), 0);   // po načtení vždy OFF (zapíná se klepnutím)
$('micState').onclick = () => { if (Voice.on) Voice.listenNow(); };
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && radioOn && 'wakeLock' in navigator) {
    navigator.wakeLock.request('screen').then((w) => { wakeLock = w; }).catch(() => {});
  }
});
if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = () => {};
setMic('off');
if (!SR || !window.isSecureContext) {
  $('micHint').textContent = !SR
    ? 'This browser has no speech recognition. Use controller buttons (UDP Action) to talk to Bono.'
    : 'Voice wake word needs a secure page: run the server on this iPad and open http://localhost:8080. Controller buttons work everywhere.';
  $('micHint').classList.remove('hidden');
}

// ------------------------------------------------------------------ chat
function addBubble(text, who) {
  const d = document.createElement('div');
  d.className = 'bubble ' + who; d.textContent = text;
  $('chat').appendChild(d); $('chat').scrollTop = 1e9;
}
async function ask(q, viaVoice) {
  if (!q) return;
  addBubble((viaVoice ? '🎙️ ' : '') + q, 'me');
  $('askInput').value = '';
  try {
    const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q }) });
    const d = await r.json();
    addBubble(d.text || d.error, 'eng');
  } catch (e) { addBubble('No connection to the server.', 'eng'); }
}
// ------------------------------------------------------------------ ovládací panel
// Bono může mluvit a poslouchat na jiném zařízení (např. MacBook s AirPods) a tenhle displej
// (iPad) slouží jen jako dálkové ovládání. Zařízení se zapnutým Bonem se hlásí serveru.
const deviceId = (() => {
  try {
    let id = localStorage.getItem('bonoDevice');
    if (!id) { id = Math.random().toString(36).slice(2, 10); localStorage.setItem('bonoDevice', id); }
    return id;
  } catch (_) { return Math.random().toString(36).slice(2, 10); }
})();
const deviceName = /iPad|Macintosh.*Mobile/.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Mac/.test(navigator.platform))
  ? 'iPad' : /iPhone/.test(navigator.userAgent) ? 'iPhone' : /Mac/.test(navigator.platform) ? 'Mac' : 'PC';
setInterval(() => {
  if (!radioOn) return;
  fetch('/api/presence', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: deviceId, mic: Voice.on, name: deviceName }) }).catch(() => {});
}, 4000);
function voiceElsewhere() {
  const v = S && S.voice_devices;
  return !radioOn && v && v.count > 0;
}
async function postAction(action) {
  try {
    await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }) });
  } catch (_) { /* bez spojení */ }
}

document.querySelectorAll('#pad button').forEach((b) => {
  b.onclick = async () => {
    const act = b.dataset.act;
    b.classList.add('on'); setTimeout(() => b.classList.remove('on'), 400);
    if (act === 'talk') {
      if (Voice.on) { Voice.listenNow(); return; }                 // mikrofon na tomhle zařízení
      const v = S && S.voice_devices;
      if (!radioOn && v && v.mic > 0) { postAction('listen'); return; }   // poslouchá jiné zařízení (Mac)
      if (SR && window.isSecureContext) { startBono(); setTimeout(() => Voice.listenNow(), 300); return; }
      $('tabs').querySelector('[data-tab=eng]').click();            // bez mikrofonu → psaní / diktování
      $('askInput').focus();
      return;
    }
    let action = act;
    if (act === 'mute') action = S && S.settings.voice === false ? 'unmute' : 'mute';
    if (!radioOn && !voiceElsewhere()) startBono();   // nikde jinde Bono nemluví → zapni ho tady
    postAction(action);
  };
});

$('askForm').onsubmit = (e) => { e.preventDefault(); ask($('askInput').value.trim()); };
document.querySelectorAll('.quick button').forEach((b) => { b.onclick = () => ask(b.dataset.q); });
$('micBtn').onclick = () => {
  if (Voice.on) { Voice.listenNow(); return; }
  if (!SR) { $('askInput').focus(); return; }
  const rec = new SR();
  rec.lang = lang() === 'cs' ? 'cs-CZ' : 'en-GB';
  rec.interimResults = false;
  $('micBtn').textContent = '⏺️';
  rec.onresult = (e) => ask(e.results[0][0].transcript, true);
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
  $('sGroq').value = s.has_groq ? '***' : '';
  $('sName').value = st.engineer_name || 'Bono';
  $('sWake').value = st.wake_word || 'bono';
  $('sVoiceEngine').value = st.voice_engine || 'mixed';
  $('sTtsVoice').value = st.tts_voice || 'Charon';
  settingsLoaded = true;
}
$('saveBtn').onclick = async () => {
  const ai = $('sAi').value.trim();
  const body = {
    lang: $('sLang').value, level: parseInt($('sLevel').value, 10), reference: $('sRef').value,
    difficulty_override: ai === '' ? null : parseInt(ai, 10), voice: $('sVoice').checked,
    gemini_key: $('sKey').value.trim(), gemini_model: $('sModel').value.trim() || 'gemini-flash-lite-latest',
    engineer_name: $('sName').value.trim() || 'Bono', wake_word: ($('sWake').value.trim() || 'bono').toLowerCase(),
    voice_engine: $('sVoiceEngine').value, tts_voice: $('sTtsVoice').value,
    groq_key: $('sGroq').value.trim(),
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
