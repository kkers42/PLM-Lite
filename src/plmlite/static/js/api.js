/**
 * PLM Lite v2.1 — API client
 *
 * Server always runs at the root (localhost:8080), so BASE_PATH is empty.
 */
const BASE_PATH = '';

class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
  }
}

async function apiFetch(path, options = {}) {
  const url = path.startsWith('/') ? BASE_PATH + path : path;
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    credentials: 'same-origin',
    ...options,
  });

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
  return resp;
}

const api = {
  get:    (path)        => apiFetch(path),
  post:   (path, body)  => apiFetch(path, { method: 'POST',   body: JSON.stringify(body) }),
  put:    (path, body)  => apiFetch(path, { method: 'PUT',    body: JSON.stringify(body) }),
  patch:  (path, body)  => apiFetch(path, { method: 'PATCH',  body: JSON.stringify(body) }),
  delete: (path)        => apiFetch(path, { method: 'DELETE' }),
  upload: (path, fd)    => apiFetch(path, { method: 'POST',   body: fd, headers: {} }),
};

window.api = api;
