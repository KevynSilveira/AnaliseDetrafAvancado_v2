// Cliente HTTP simples
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request(path, { method='GET', headers={}, body, timeout=30000 } = {}) {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeout);
  const res = await fetch(BASE + path, { method, headers, body, signal: ctrl.signal });
  clearTimeout(id);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || ('HTTP ' + res.status));
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return await res.json();
  return await res.text();
}

export const api = {
  get: (p) => request(p),
  post: (p, data) => request(p, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data) }),
  upload: (p, file, fields={}) => {
    const form = new FormData();
    form.append('arquivo', file);
    Object.entries(fields).forEach(([k,v]) => form.append(k, v));
    return request(p, { method:'POST', body: form });
  },
  delete: (p) => request(p, { method:'DELETE' }),
  put: (p, data) => request(p, { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data) }),
};

export const API_BASE = BASE;
