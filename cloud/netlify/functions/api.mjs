// Netlify Function: /api/* → Bono Cloud API nad Netlify Blobs.
import { getStore } from '@netlify/blobs';
import { handle } from './core.mjs';

export default async (req) => handle(req, getStore({ name: 'bono', consistency: 'strong' }));

export const config = { path: '/api/*' };
