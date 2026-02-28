/**
 * PLM Lite V1.0 — Centralized API client
 *
 * BASE_PATH: Detects the app's root automatically so this works whether
 * served at / (local server) or at /plm (VPS via Traefik StripPrefix).
 * Traefik strips /plm before it hits the backend, so the server always
 * sees paths without the prefix. The browser however is at /plm/app,
 * so absolute paths like /api/... would miss the prefix.
 * We resolve all paths relative to the page's own origin+pathname root.
 */
const BASE_PATH = (() => {
  // e.g. at https://3dprintdudes.io/plm/app → base is /plm
  // e.g. at http://192.168.1.37:8070/app    → base is (empty string)
  const parts = window.location.pathname.split('/');
  // pathname is like /plm/app or /app — drop the last segment (page name)
  parts.pop();
  return parts.join('/'); // '/plm' or ''
})();

class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
  }
}

async function apiFetch(path, options = {}) {
  // If path starts with / it's absolute from app root — prepend BASE_PATH
  const url = path.startsWith('/') ? BASE_PATH + path : path;
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    credentials: 'same-origin',
    ...options,
  });

  if (resp.status === 401) {
    window.location.href = BASE_PATH + '/login';
    return;
  }

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new ApiError(resp.status, detail);
  }

  const ct = resp.headers.get('content-type') || '';
  if (ct.includes('application/json')) return resp.json();
  return resp;  // blob/stream response
}

const api = {
  get: (path) => apiFetch(path),
  post: (path, body) => apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
  put: (path, body) => apiFetch(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: (path) => apiFetch(path, { method: 'DELETE' }),

  upload: (path, formData) =>
    apiFetch(path, {
      method: 'POST',
      body: formData,
      headers: {},  // let browser set Content-Type with boundary
    }),
};

window.api = api;
