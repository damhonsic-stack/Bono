import { test } from 'node:test';
import assert from 'node:assert/strict';
import { handle } from '../netlify/functions/core.mjs';
import { memStore } from '../memstore.mjs';

const call = (store, method, path, { body, code } = {}) => handle(new Request('https://x.netlify.app' + path, {
  method, headers: { 'content-type': 'application/json', ...(code ? { 'x-bono-code': code } : {}) },
  body: body === undefined ? undefined : JSON.stringify(body),
}), store);

test('first code claims the cloud, wrong code rejected', async () => {
  const s = memStore();
  assert.equal((await call(s, 'POST', '/api/auth', { body: { code: 'short' } })).status, 400);
  const r1 = await (await call(s, 'POST', '/api/auth', { body: { code: 'monza-2026-bono' } })).json();
  assert.equal(r1.created, true);
  assert.equal((await call(s, 'POST', '/api/auth', { body: { code: 'monza-2026-bono' } })).status, 200);
  assert.equal((await call(s, 'POST', '/api/auth', { body: { code: 'someone-else' } })).status, 401);
  assert.equal((await call(s, 'GET', '/api/list', { code: 'someone-else' })).status, 401);
});

test('kv put/get/list/batch/delete with valid code', async () => {
  const s = memStore();
  const code = 'monza-2026-bono';
  await call(s, 'POST', '/api/auth', { body: { code } });
  assert.equal((await call(s, 'PUT', '/api/kv?key=tracks/17', { body: { name: 'Austria' }, code })).status, 200);
  assert.deepEqual(await (await call(s, 'GET', '/api/kv?key=tracks/17', { code })).json(), { name: 'Austria' });
  assert.equal((await call(s, 'GET', '/api/kv?key=tracks/99', { code })).status, 404);
  await call(s, 'PUT', '/api/kv?key=debriefs/1', { body: { a: 1 }, code });
  const list = await (await call(s, 'GET', '/api/list?prefix=debriefs/', { code })).json();
  assert.deepEqual(list.keys, ['debriefs/1']);
  const all = await (await call(s, 'GET', '/api/list', { code })).json();
  assert.ok(!all.keys.some((k) => k.startsWith('_')));   // hash kódu se nikdy nevrací
  const b = await (await call(s, 'POST', '/api/batch', { body: { keys: ['tracks/17', 'debriefs/1', 'x'] }, code })).json();
  assert.equal(b['tracks/17'].name, 'Austria');
  assert.equal(b.x, null);
  await call(s, 'DELETE', '/api/kv?key=debriefs/1', { code });
  assert.equal((await call(s, 'GET', '/api/kv?key=debriefs/1', { code })).status, 404);
});

test('rejects bad keys and access to auth record', async () => {
  const s = memStore();
  const code = 'monza-2026-bono';
  await call(s, 'POST', '/api/auth', { body: { code } });
  for (const k of ['_auth/hash', '../x', 'a b', '']) {
    assert.equal((await call(s, 'GET', '/api/kv?key=' + encodeURIComponent(k), { code })).status, 400, k);
  }
});
