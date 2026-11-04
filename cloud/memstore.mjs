// Úložiště v paměti / v souboru – pro testy a lokální vývoj (stejné API jako Netlify Blobs).
import { readFileSync, writeFileSync, existsSync } from 'node:fs';

export function memStore(file = null) {
  let data = {};
  if (file && existsSync(file)) data = JSON.parse(readFileSync(file, 'utf8'));
  const save = () => { if (file) writeFileSync(file, JSON.stringify(data)); };
  return {
    async get(key) { return key in data ? structuredClone(data[key].v) : null; },
    async setJSON(key, v, opts = {}) { data[key] = { v: structuredClone(v), m: opts.metadata || {} }; save(); },
    async delete(key) { delete data[key]; save(); },
    async list({ prefix = '' } = {}) {
      return { blobs: Object.keys(data).filter((k) => k.startsWith(prefix)).sort().map((key) => ({ key })) };
    },
  };
}
