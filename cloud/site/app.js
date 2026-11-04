'use strict';
// Bono Cloud – paměť a historie Bona mezi zařízeními. Data zapisuje Bono server na Macu,
// web je čte (a umí upravit Bonovu paměť a sdílené nastavení).

const $ = (id) => document.getElementById(id);
const app = $('app');
const TOKEN = 'bonoCloudCode';
let code = (() => { try { return localStorage.getItem(TOKEN) || ''; } catch (_) { return ''; } })();

function esc(t) { return String(t === undefined || t === null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function fmtLap(ms) {
  if (!ms) return '–';
  ms = Math.round(ms);
  return `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(3).padStart(6, '0')}`;
}
function fmtDelta(ms, d = 2) { if (ms === null || ms === undefined) return '–'; return (ms > 0 ? '+' : ms < 0 ? '' : '±') + (ms / 1000).toFixed(d); }
function fmtSec(ms) { return ms ? (ms / 1000).toFixed(3) : '–'; }
function fmtDate(ts) { return ts ? new Date((ts > 1e12 ? ts : ts * 1000)).toLocaleString('cs-CZ', { day: 'numeric', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '–'; }

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const r = await fetch('/api/' + path, {
    ...opts, headers: { 'content-type': 'application/json', 'x-bono-code': code, ...(opts.headers || {}) },
  });
  if (r.status === 401) { logout(); throw new Error('unauthorized'); }
  if (r.status === 404) return null;
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}
const kv = (key) => api('kv?key=' + encodeURIComponent(key));
const put = (key, value) => api('kv?key=' + encodeURIComponent(key), { method: 'PUT', body: JSON.stringify(value) });

function logout() {
  try { localStorage.removeItem(TOKEN); } catch (_) { /* */ }
  code = '';
  location.hash = '#/login';
}

// ------------------------------------------------------------------ router
const routes = {
  login: renderLogin, home: renderHome, track: renderTrack, session: renderSession,
  memory: renderMemory, settings: renderSettings,
};
async function route() {
  const parts = (location.hash.replace(/^#\/?/, '') || 'home').split('/');
  let name = parts[0] || 'home';
  if (!code && name !== 'login') { location.hash = '#/login'; return; }
  $('nav').classList.toggle('hidden', !code);
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.r === name));
  if (!routes[name]) name = 'home';
  app.innerHTML = '<div class="card muted">Načítám…</div>';
  try { await routes[name](...parts.slice(1)); } catch (e) {
    if (e.message !== 'unauthorized') app.innerHTML = `<div class="card err">Chyba: ${esc(e.message)}</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);
window.addEventListener('resize', () => { if (window.__redraw) window.__redraw(); });

// ------------------------------------------------------------------ přihlášení
function renderLogin() {
  app.innerHTML = `<div class="card login">
    <h1>Bono Cloud</h1>
    <p class="muted">Paměť a historie tvého AI race engineera, na všech zařízeních. Zadej svůj <b>sync kód</b>,
    stejný jako v Bonovi na Macu (Settings → Bono Cloud). Úplně poprvé ho tímhle zadáním nastavíš.</p>
    <label>Sync kód <input id="codeIn" type="password" autocomplete="current-password" placeholder="min. 8 znaků"></label>
    <button class="primary" id="loginBtn">Přihlásit</button>
    <div id="loginErr"></div></div>`;
  const go = async () => {
    const c = $('codeIn').value.trim();
    const r = await fetch('/api/auth', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ code: c }) });
    const d = await r.json();
    if (!r.ok) { $('loginErr').innerHTML = `<div class="err">${esc(d.error || 'Chyba')}</div>`; return; }
    code = c;
    try { localStorage.setItem(TOKEN, c); } catch (_) { /* */ }
    location.hash = '#/';
  };
  $('loginBtn').onclick = go;
  $('codeIn').onkeydown = (e) => { if (e.key === 'Enter') go(); };
  $('codeIn').focus();
}

// ------------------------------------------------------------------ přehled
async function renderHome() {
  const [idx, mem] = await Promise.all([kv('tracks_index'), kv('memory')]);
  if (!idx) {
    app.innerHTML = `<div class="card"><h2>Zatím žádná data</h2><p class="muted">Na Macu v Bonovi otevři
      Settings → Bono Cloud, vyplň adresu tohoto webu a stejný sync kód a klikni na „Připojit a synchronizovat“.</p></div>`;
    return;
  }
  const tracks = (idx.tracks || []).slice().sort((a, b) => (b.last || 0) - (a.last || 0));
  const recent = (idx.debriefs || []).slice().sort((a, b) => b.ts - a.ts).slice(0, 12);
  const notes = (mem && mem.notes) || [];
  app.innerHTML = `
    <div class="card"><div class="label">Tratě</div><div class="grid">${tracks.map((t) => `
      <a class="tile" href="#/track/${t.track_id}"><b>${esc(t.name)}</b>
        <div class="big mono">${fmtLap(t.pb_ms || t.tt_pb_ms)}</div>
        <div class="small muted">${t.pb_ms ? 'osobní rekord' : t.tt_pb_ms ? 'Time Trial PB' : ''}${t.pb_date ? ' · ' + esc(t.pb_date) : ''}<br>
        ${t.sessions} session${t.last ? ' · naposledy ' + fmtDate(t.last) : ''}</div></a>`).join('') || '<span class="muted">Žádné tratě.</span>'}
    </div></div>
    <div class="card"><div class="label">Poslední session</div>${sessionTable(recent)}</div>
    <div class="card"><div class="row between"><div class="label">Bono si pamatuje</div><a class="btn" href="#/memory">Upravit</a></div>
      ${notes.length ? notes.slice(-5).reverse().map((n) => `<div class="note"><span>${esc(n.text)}</span></div>`).join('')
        : '<span class="muted">Zatím nic. Řekni v závodě „Bono, zapamatuj si, že …“ nebo to dopiš tady.</span>'}</div>`;
  bindRows();
}
function sessionTable(list) {
  if (!list.length) return '<span class="muted">Zatím žádný debrief.</span>';
  return `<table class="tbl"><thead><tr><th>Kdy</th><th>Trať</th><th>Session</th><th>Best lap</th></tr></thead><tbody>${list.map((d) => `
    <tr class="link" data-href="#/session/${encodeURIComponent(d.key)}"><td>${fmtDate(d.ts)}</td><td>${esc(d.track)}</td>
    <td>${esc(d.session)}</td><td class="num">${esc(d.best || '–')}</td></tr>`).join('')}</tbody></table>`;
}
function bindRows() {
  document.querySelectorAll('tr.link').forEach((tr) => { tr.onclick = () => { location.hash = tr.dataset.href; }; });
}

// ------------------------------------------------------------------ trať
async function renderTrack(id) {
  const [idx, hist, mem] = await Promise.all([kv('tracks_index'), kv('history/' + id), kv('memory')]);
  const t = ((idx && idx.tracks) || []).find((x) => String(x.track_id) === String(id)) || { name: 'Trať ' + id };
  const laps = ((hist && hist.laps) || []).filter((l) => l.valid && l.lap_ms);
  const tm = mem && mem.tracks && mem.tracks[id];
  const weak = tm ? Object.entries(tm.weak_turns || {}).sort((a, b) => b[1].count - a[1].count || b[1].avg_loss_ms - a[1].avg_loss_ms) : [];
  const sessions = ((idx && idx.debriefs) || []).filter((d) => d.track === t.name).sort((a, b) => b.ts - a.ts);
  app.innerHTML = `
    <div class="card"><h1>${esc(t.name)}</h1>
      <div class="row"><span class="chip">Osobní rekord <b class="mono">${fmtLap(t.pb_ms)}</b></span>
      ${t.tt_pb_ms ? `<span class="chip">Time Trial <b class="mono">${fmtLap(t.tt_pb_ms)}</b></span>` : ''}
      <span class="chip">${laps.length} platných kol</span><span class="chip">${sessions.length} session</span></div></div>
    <div class="card"><div class="label">Zlepšování (všechna platná kola)</div><canvas class="chart" id="progress"></canvas>
      <div class="small muted">Tečky = kola, fialově = nový osobní rekord v čase.</div></div>
    <div class="card"><div class="label">Kde tady opakovaně ztrácíš (Bonova paměť)</div>
      ${weak.length ? weak.slice(0, 6).map(([turn, w]) => `<span class="chip"><b>${esc(turn)}</b> · ${w.count}× · Ø ${fmtDelta(w.avg_loss_ms, 2)} s</span>`).join('')
        : '<span class="muted">Zatím málo session.</span>'}</div>
    <div class="card"><div class="label">Session na této trati</div>${sessionTable(sessions)}</div>`;
  bindRows();
  const draw = () => drawProgress($('progress'), laps);
  window.__redraw = draw; draw();
}
function drawProgress(c, laps) {
  if (!c) return;
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  c.width = w * dpr; c.height = h * dpr;
  const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  if (laps.length < 2) { ctx.fillStyle = '#8b93a7'; ctx.font = '15px -apple-system'; ctx.fillText('Málo kol na graf.', 16, 30); return; }
  const ys = laps.map((l) => l.lap_ms);
  const min = Math.min(...ys), max = Math.min(Math.max(...ys), min * 1.05);
  ctx.fillStyle = '#8b93a7'; ctx.font = '11px -apple-system';
  ctx.fillText(fmtLap(max), 6, 14); ctx.fillText(fmtLap(min), 6, h - 8);
  let best = Infinity;
  const pts = laps.map((l, i) => {
    const x = 64 + (i / (laps.length - 1)) * (w - 76);
    const y = 12 + (1 - (Math.min(l.lap_ms, max) - min) / (max - min || 1)) * (h - 28);
    const pb = l.lap_ms < best; if (pb) best = l.lap_ms;
    return { x, y, pb };
  });
  ctx.strokeStyle = 'rgba(168,85,247,.7)'; ctx.lineWidth = 2; ctx.beginPath();
  pts.filter((p) => p.pb).forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.stroke();
  pts.forEach((p) => { ctx.fillStyle = p.pb ? '#a855f7' : 'rgba(225,6,0,.8)'; ctx.beginPath(); ctx.arc(p.x, p.y, p.pb ? 4 : 2.5, 0, Math.PI * 2); ctx.fill(); });
}

// ------------------------------------------------------------------ session (debrief + recap)
let recap = null, recapMode = 'avg';
const RECAP_KEY = { avg: 'avg_loss', best: 'best_vs_avg', worst: 'worst_vs_avg' };
async function renderSession(key) {
  const d = await kv(decodeURIComponent(key));
  if (!d) { app.innerHTML = '<div class="card">Session nenalezena.</div>'; return; }
  const s = d.summary || {};
  recap = s.recap || null;
  app.innerHTML = `
    <div class="card"><div class="row between"><div><h1>${esc(d.track)} · ${esc(d.session)}</h1>
      <div class="muted">${fmtDate(d.ts)} · debrief: ${esc(d.source)}</div></div><a class="btn" href="#/">← Přehled</a></div>
      <div class="row" style="margin-top:10px">
        <span class="chip">Best <b class="mono">${esc(s.best_lap || '–')}</b></span>
        <span class="chip">Ideální kolo <b class="mono purple">${esc(s.theoretical_best || '–')}</b></span>
        <span class="chip">Kol ${s.laps || 0} (platných ${s.valid_laps || 0})</span>
        ${s.consistency_stdev_s ? `<span class="chip">Konzistence ±${s.consistency_stdev_s} s</span>` : ''}
        ${s.finish_position ? `<span class="chip">Cíl P${s.finish_position}${s.grid ? ' (start P' + s.grid + ')' : ''}</span>` : ''}
      </div></div>
    <div class="card"><div class="label">Debrief od Bona</div><div class="debrief">${esc(d.text)}</div></div>
    ${recap && recap.outline ? `
    <div class="card"><div class="row between"><div class="label">Recap</div>
      <div class="seg" id="modes"><button data-mode="avg" class="active">Kde ztrácím</button>
      <button data-mode="best">Best lap: kde jsem nahnal</button><button data-mode="worst">Worst lap: kde jsem ztratil</button></div></div>
      <div class="recap-grid"><canvas class="map" id="map"></canvas>
        <div><div class="high">${(recap.text || []).map((t) => `<div>${esc(t)}</div>`).join('')}</div>
        <div class="legend-bar"><span>méně ztrácím</span><i></i><span>víc ztrácím</span></div></div></div>
      <div class="label" style="margin-top:14px">Sektory</div><div id="sectors"></div>
      <div class="label" style="margin-top:14px">Zatáčky</div><div id="turns"></div>
    </div>` : '<div class="card muted">K této session není recap s mapou.</div>'}
    ${(s.setup_advice || []).length ? `<div class="card"><div class="label">Setup návrhy</div>${s.setup_advice.map((a) =>
      `<div class="note"><span><b>${esc(a.issue)}</b><br>${esc(a.change)} <span class="muted">${esc(a.current || '')}</span></span></div>`).join('')}</div>` : ''}`;
  if (!recap || !recap.outline) return;
  document.querySelectorAll('#modes button').forEach((b) => {
    b.onclick = () => { recapMode = b.dataset.mode; document.querySelectorAll('#modes button').forEach((x) => x.classList.toggle('active', x === b)); drawMap(); };
  });
  renderRecapTables();
  window.__redraw = drawMap; drawMap();
}
function renderRecapTables() {
  const sec = recap.sectors;
  if (sec) {
    const rows = [['Best lap', sec.best], ['Worst lap', sec.worst], ['Průměr', sec.avg], ['Ideál', sec.ideal]];
    $('sectors').innerHTML = `<table class="tbl"><thead><tr><th></th><th>Lap</th><th>S1</th><th>S2</th><th>S3</th><th>Čas</th></tr></thead><tbody>${rows.map(([n, r]) =>
      `<tr><td><b>${n}</b></td><td>${r.lap || '–'}</td>${r.s.map((v, i) => { const d = v - sec.ideal.s[i];
        return `<td class="num ${d === 0 ? 'cool' : d > 150 ? 'hot' : ''}">${fmtSec(v)}${d ? ` <span class="${d > 0 ? 'loss' : 'gain'}">${fmtDelta(d)}</span>` : ''}</td>`; }).join('')}
      <td class="num"><b>${fmtLap(r.time)}</b></td></tr>`).join('')}</tbody></table>`;
  }
  const hl = recap.highlights || {};
  const worst = new Set((hl.most_loss || []).map((x) => x.turn)), least = new Set((hl.least_loss || []).map((x) => x.turn));
  $('turns').innerHTML = `<table class="tbl"><thead><tr><th>Turn</th><th>Ø ztráta</th><th>Best lap vs Ø</th><th>Worst lap vs Ø</th><th>Co bylo ve worst lapu jinak</th></tr></thead><tbody>${(recap.corners || []).map((t) => `
    <tr><td><b>${esc(t.name)}</b></td><td class="num ${worst.has(t.name) ? 'hot' : least.has(t.name) ? 'cool' : ''}">${fmtDelta(t.avg_loss, 3)}</td>
    <td class="num ${t.best_vs_avg < 0 ? 'gain' : 'loss'}">${fmtDelta(t.best_vs_avg, 3)}</td>
    <td class="num ${t.worst_vs_avg > 0 ? 'loss' : 'gain'}">${fmtDelta(t.worst_vs_avg, 3)}</td>
    <td>${esc((t.worst_tips || []).join('; ') || '–')}</td></tr>`).join('')}</tbody></table>`;
}
function lossColor(t) {
  if (t <= 0) { const a = Math.min(1, -t); return `rgb(${Math.round(34 + 56 * (1 - a))},197,${Math.round(94 + 60 * (1 - a))})`; }
  t = Math.min(1, t);
  if (t < 0.5) { const k = t / 0.5; return `rgb(${Math.round(34 + 216 * k)},${Math.round(197 + 7 * k)},${Math.round(94 - 73 * k)})`; }
  const k = (t - 0.5) / 0.5; return `rgb(${Math.round(250 - 11 * k)},${Math.round(204 - 136 * k)},${Math.round(21 + 47 * k)})`;
}
function drawMap() {
  const c = $('map'); if (!c || !recap) return;
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  c.width = w * dpr; c.height = h * dpr;
  const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  const o = recap.outline, turns = recap.corners || [];
  const minX = Math.min(...o.x), maxX = Math.max(...o.x), minZ = Math.min(...o.z), maxZ = Math.max(...o.z);
  const pad = 34, sc = Math.min((w - 2 * pad) / (maxX - minX || 1), (h - 2 * pad) / (maxZ - minZ || 1));
  const ox = (w - (maxX - minX) * sc) / 2, oz = (h - (maxZ - minZ) * sc) / 2;
  const P = (x, z) => [ox + (x - minX) * sc, oz + (z - minZ) * sc];
  const key = RECAP_KEY[recapMode];
  const scale = Math.max(30, ...turns.map((t) => Math.abs(t[key])));
  const turnAt = (d) => turns.find((t) => d >= t.start && d <= t.end);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.lineWidth = 12; ctx.strokeStyle = '#232a38';
  ctx.beginPath(); o.x.forEach((x, i) => { const [px, pz] = P(x, o.z[i]); i ? ctx.lineTo(px, pz) : ctx.moveTo(px, pz); }); ctx.closePath(); ctx.stroke();
  ctx.lineWidth = 7;
  for (let i = 0; i < o.x.length - 1; i++) {
    const t = turnAt(o.dist[i]); if (!t) continue;
    let v = t[key] / scale; if (recapMode === 'avg') v = Math.max(0, v);
    ctx.strokeStyle = lossColor(v);
    const [a, b] = P(o.x[i], o.z[i]), [c2, d] = P(o.x[i + 1], o.z[i + 1]);
    ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c2, d); ctx.stroke();
  }
  (recap.sector_starts || []).forEach((sd, k) => {
    if (sd === null || sd === undefined) return;
    let j = 0; while (j < o.dist.length - 1 && o.dist[j] < sd) j++;
    const [px, pz] = P(o.x[j], o.z[j]);
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(px, pz, 5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#cbd5e1'; ctx.font = 'bold 11px -apple-system'; ctx.fillText(k === 0 ? 'START / S1' : 'S' + (k + 1), px + 8, pz + 16);
  });
  turns.forEach((t) => {
    const [px, pz] = P(t.x, t.z); const v = t[key];
    const label = `${t.name} ${fmtDelta(v)}`; ctx.font = 'bold 12px -apple-system';
    const tw = ctx.measureText(label).width + 10;
    ctx.fillStyle = 'rgba(11,13,18,.85)'; ctx.fillRect(px - tw / 2, pz - 24, tw, 18);
    ctx.fillStyle = lossColor(recapMode === 'avg' ? Math.max(0, v / scale) : v / scale);
    ctx.textAlign = 'center'; ctx.fillText(label, px, pz - 11); ctx.textAlign = 'left';
  });
}

// ------------------------------------------------------------------ paměť
async function renderMemory() {
  const mem = (await kv('memory')) || { notes: [], tracks: {} };
  mem.notes = mem.notes || []; mem.tracks = mem.tracks || {};
  const save = async () => { mem.updated = Date.now(); await put('memory', mem); renderMemory(); };
  app.innerHTML = `
    <div class="card"><h1>Co si Bono pamatuje</h1>
      <p class="muted small">Bono tyhle věci zná v každém závodě, na každém zařízení. Na Macu se změny projeví do 2 minut.
      Hlasem: „Bono, zapamatuj si, že …“ / „Bono, zapomeň“.</p>
      <div id="notes">${mem.notes.length ? mem.notes.map((n, i) => `<div class="note"><span>${esc(n.text)}</span>
        <span class="small muted">${fmtDate(n.ts)}</span><button data-del="${i}">Smazat</button></div>`).join('') : '<p class="muted">Zatím nic.</p>'}</div>
      <div class="row" style="margin-top:12px"><input id="newNote" placeholder="např. Jezdím s ABS off, v Monze brzdím pozdě do T1">
        <button class="primary" id="addNote">Přidat</button></div></div>
    <div class="card"><div class="label">Tratě v paměti</div>
      ${Object.entries(mem.tracks).map(([id, t]) => `<div class="note"><span><b>${esc(t.name)}</b> · ${t.sessions || 0} session · best ${fmtLap(t.best_ms)}<br>
        <span class="small muted">Slabá místa: ${Object.entries(t.weak_turns || {}).sort((a, b) => b[1].count - a[1].count).slice(0, 4)
          .map(([k, w]) => `${esc(k)} (${w.count}×)`).join(', ') || '–'}</span></span><a class="btn" href="#/track/${esc(id)}">Detail</a></div>`).join('')
        || '<p class="muted">Paměť tratí se plní po každém debriefu.</p>'}</div>`;
  document.querySelectorAll('[data-del]').forEach((b) => { b.onclick = () => { mem.notes.splice(+b.dataset.del, 1); save(); }; });
  $('addNote').onclick = () => {
    const t = $('newNote').value.trim(); if (!t) return;
    mem.notes.push({ text: t, ts: Math.floor(Date.now() / 1000) }); save();
  };
  $('newNote').onkeydown = (e) => { if (e.key === 'Enter') $('addNote').click(); };
}

// ------------------------------------------------------------------ nastavení (sdílené)
async function renderSettings() {
  const sh = (await kv('settings/shared')) || { values: {} };
  const v = sh.values || {};
  const opt = (val, cur, text) => `<option value="${val}" ${String(cur) === String(val) ? 'selected' : ''}>${text}</option>`;
  app.innerHTML = `<div class="card"><h1>Nastavení Bona</h1>
    <p class="muted small">Platí pro Bona na všech zařízeních (Mac si je stáhne do 2 minut). API klíče se sem neukládají, zůstávají jen na Macu.</p>
    <label>Jazyk <select id="lang">${opt('cs', v.lang || 'cs', 'Čeština')}${opt('en', v.lang, 'English')}</select></label>
    <label>Kolik Bono mluví sám od sebe <select id="radio">${opt('quiet', v.radio_mode || 'quiet', 'Tiché: jen důležité')}
      ${opt('normal', v.radio_mode, 'Normální: + lap times a gapy')}${opt('full', v.radio_mode, 'Vše')}</select></label>
    <label>Úroveň rad <select id="level">${opt(1, v.level, 'Rookie')}${opt(2, v.level || 2, 'Advanced')}${opt(3, v.level, 'Pro')}</select></label>
    <label>Jméno inženýra <input id="name" value="${esc(v.engineer_name || 'Bono')}"></label>
    <label>Wake word <input id="wake" value="${esc(v.wake_word || 'bono')}"></label>
    <div class="row"><button class="primary" id="saveS">Uložit</button><span id="saved" class="ok"></span></div></div>
    <div class="card"><div class="label">Toto zařízení</div><button id="logoutBtn">Odhlásit</button></div>`;
  $('saveS').onclick = async () => {
    const values = { ...v, lang: $('lang').value, radio_mode: $('radio').value, level: +$('level').value,
      engineer_name: $('name').value.trim() || 'Bono', wake_word: ($('wake').value.trim() || 'bono').toLowerCase() };
    await put('settings/shared', { updated: Date.now(), values });
    $('saved').textContent = 'Uloženo ✓';
  };
  $('logoutBtn').onclick = logout;
}

route();
