// Cliente HTTP simples
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request(path, { method='GET', headers={}, body, timeout=30000 } = {}) {
  const ctrl = new AbortController();
  const timeoutMs = typeof timeout === 'number' ? timeout : 30000;
  let timerId = null;
  if (timeoutMs > 0) {
    timerId = setTimeout(() => ctrl.abort(), timeoutMs);
  }
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body, signal: ctrl.signal });
  } catch (err) {
    if (timerId) clearTimeout(timerId);
    if (err?.name === 'AbortError') {
      throw new Error('Requisição cancelada por tempo excedido.');
    }
    throw err;
  }
  if (timerId) clearTimeout(timerId);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || ('HTTP ' + res.status));
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return await res.json();
  return await res.text();
}

export const api = {
  get: (p, opts) => request(p, opts),
  post: (p, data, opts={}) => {
    const { headers: extraHeaders = {}, ...rest } = opts || {};
    return request(p, {
      method:'POST',
      headers:{'Content-Type':'application/json', ...extraHeaders},
      body: JSON.stringify(data),
      ...rest,
    });
  },
  upload: (p, file, fields={}, opts={}) => {
    const form = new FormData();
    form.append('arquivo', file);
    Object.entries(fields).forEach(([k,v]) => form.append(k, v));
    const { timeout, ...rest } = opts || {};
    const uploadTimeout = timeout ?? 0; // 0 = sem timeout (útil para arquivos grandes)
    return request(p, { method:'POST', body: form, timeout: uploadTimeout, ...rest });
  },
  delete: (p) => request(p, { method:'DELETE' }),
  put: (p, data) => request(p, { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data) }),
};

export const API_BASE = BASE;
