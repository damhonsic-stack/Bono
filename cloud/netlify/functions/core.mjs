// Bono Cloud API – čistá logika (bez závislosti na Netlify, testovatelná s jakýmkoli úložištěm).
// Úložiště: { get(key, {type:'json'}), setJSON(key, value, {metadata}), delete(key), list({prefix}) }
//
// Přihlášení: osobní „sync kód“. První zařízení, které ho zadá, ho nastaví (uloží se jen hash).
// Pak každý požadavek posílá hlavičku X-Bono-Code.
import { createHash, timingSafeEqual } from 'node:crypto';

const AUTH_KEY = '_auth/hash';
const KEY_RE = /^[A-Za-z0-9_\-./]{1,200}$/;
const MAX_BODY = 5 * 1024 * 1024;

const hash = (code) => createHash('sha256').update('bono-cloud:' + code).digest('hex');

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'content-type, x-bono-code',
      'access-control-allow-methods': 'GET, PUT, POST, DELETE, OPTIONS',
    },
  });
}

function sameHash(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  return timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

async function checkCode(req, store) {
  const code = req.headers.get('x-bono-code') || '';
  const saved = await store.get(AUTH_KEY, { type: 'json' });
  if (!saved) return { ok: false, res: json({ error: 'Cloud ještě není nastavený – zadej sync kód.' }, 401) };
  if (!code || !sameHash(hash(code), saved.hash)) return { ok: false, res: json({ error: 'Špatný sync kód.' }, 401) };
  return { ok: true };
}

function validKey(key) {
  return key && KEY_RE.test(key) && !key.startsWith('_') && !key.includes('..');
}

export async function handle(req, store) {
  if (req.method === 'OPTIONS') return json({ ok: true });
  const url = new URL(req.url);
  const route = url.pathname.replace(/^\/(\.netlify\/functions\/api|api)\/?/, '');

  if (route === 'auth' && req.method === 'POST') {
    let body = {};
    try { body = await req.json(); } catch { /* prázdné */ }
    const code = String(body.code || '');
    if (code.length < 8) return json({ error: 'Sync kód musí mít aspoň 8 znaků.' }, 400);
    const saved = await store.get(AUTH_KEY, { type: 'json' });
    if (!saved) {
      await store.setJSON(AUTH_KEY, { hash: hash(code), created: Date.now() });
      return json({ ok: true, created: true });
    }
    return sameHash(hash(code), saved.hash) ? json({ ok: true }) : json({ error: 'Špatný sync kód.' }, 401);
  }

  if (route === 'health') return json({ ok: true, service: 'bono-cloud' });

  const auth = await checkCode(req, store);
  if (!auth.ok) return auth.res;

  if (route === 'kv') {
    const key = url.searchParams.get('key');
    if (!validKey(key)) return json({ error: 'Neplatný klíč.' }, 400);
    if (req.method === 'GET') {
      const v = await store.get(key, { type: 'json' });
      return v === null || v === undefined ? json({ error: 'Nenalezeno.' }, 404) : json(v);
    }
    if (req.method === 'PUT') {
      const text = await req.text();
      if (text.length > MAX_BODY) return json({ error: 'Příliš velké.' }, 413);
      let value;
      try { value = JSON.parse(text); } catch { return json({ error: 'Neplatný JSON.' }, 400); }
      await store.setJSON(key, value, { metadata: { updated: Date.now() } });
      return json({ ok: true });
    }
    if (req.method === 'DELETE') {
      await store.delete(key);
      return json({ ok: true });
    }
  }

  if (route === 'list' && req.method === 'GET') {
    const prefix = url.searchParams.get('prefix') || '';
    if (prefix && !validKey(prefix)) return json({ error: 'Neplatný prefix.' }, 400);
    const res = await store.list({ prefix });
    return json({ keys: (res.blobs || []).map((b) => b.key).filter((k) => !k.startsWith('_')) });
  }

  if (route === 'batch' && req.method === 'POST') {
    let body = {};
    try { body = await req.json(); } catch { /* prázdné */ }
    const keys = (body.keys || []).filter(validKey).slice(0, 50);
    const out = {};
    for (const k of keys) out[k] = await store.get(k, { type: 'json' });
    return json(out);
  }

  return json({ error: 'Neznámý požadavek.' }, 404);
}
