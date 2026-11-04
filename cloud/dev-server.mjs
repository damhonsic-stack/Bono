// Lokální běh Bono Cloud bez Netlify (test): node dev-server.mjs [port]
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { handle } from './netlify/functions/core.mjs';
import { memStore } from './memstore.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), 'site');
const store = memStore(process.env.BONO_DEV_STORE || null);
const port = Number(process.argv[2] || 8888);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css',
  '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json' };

createServer(async (req, res) => {
  const url = `http://localhost:${port}${req.url}`;
  if (req.url.startsWith('/api/')) {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const r = await handle(new Request(url, { method: req.method, headers: req.headers,
      body: ['GET', 'HEAD'].includes(req.method) ? undefined : body }), store);
    res.writeHead(r.status, Object.fromEntries(r.headers));
    res.end(Buffer.from(await r.arrayBuffer()));
    return;
  }
  let p = normalize(decodeURIComponent(new URL(url).pathname));
  if (p === '/' || !extname(p)) p = '/index.html';
  try {
    const f = await readFile(join(root, p));
    res.writeHead(200, { 'content-type': types[extname(p)] || 'application/octet-stream' });
    res.end(f);
  } catch {
    res.writeHead(404); res.end('not found');
  }
}).listen(port, () => console.log(`Bono Cloud dev: http://localhost:${port}`));
