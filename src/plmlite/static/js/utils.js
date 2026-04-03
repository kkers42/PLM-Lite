/**
 * PLM Lite v2.1 — Shared utilities
 */

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Date formatting ───────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatDateShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return d.toLocaleDateString();
}

// ── Debounce ──────────────────────────────────────────────────────────────────
function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ── Status chip ───────────────────────────────────────────────────────────────
function statusChip(status) {
  const map = {
    released:   ['chip-released',   'Released'],
    locked:     ['chip-released',   'Locked'],
    in_work:    ['chip-prototype',  'In Work'],
    active:     ['chip-prototype',  'Active'],
    obsolete:   ['chip-available',  'Obsolete'],
  };
  const [cls, label] = map[(status || '').toLowerCase()] || ['chip-available', status || '—'];
  return `<span class="chip ${cls}">${label}</span>`;
}

function checkoutChip(checkedOutBy) {
  if (!checkedOutBy) return `<span class="chip chip-available">Available</span>`;
  return `<span class="chip chip-checked-out" title="Checked out by ${checkedOutBy}">Out: ${checkedOutBy}</span>`;
}

// ── File type icon ────────────────────────────────────────────────────────────
function fileIcon(fileType) {
  const icons = {
    pdf: '📄', docx: '📝', xlsx: '📊', pptx: '📊',
    prt: '⚙', asm: '⚙', drw: '📐', sldprt: '⚙', sldasm: '⚙',
    stl: '🔩', obj: '🔩', step: '🔩', stp: '🔩',
    ipt: '⚙', iam: '⚙', jpg: '🖼', jpeg: '🖼', png: '🖼',
  };
  return icons[(fileType || '').toLowerCase()] || '📎';
}

// ── HTML escaping ─────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── CAD extension check ───────────────────────────────────────────────────────
const CAD_EXTS = new Set(['prt','asm','drw','stl','sldprt','sldasm','ipt','iam','step','stp']);
function isCadFile(fileType) {
  return CAD_EXTS.has((fileType || '').toLowerCase());
}

// ── Modal helpers ─────────────────────────────────────────────────────────────
function openModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { const m = document.getElementById(id); if (m) m.style.display = 'none'; }

function createModal(id, title, bodyHtml, onConfirm, confirmLabel = 'Save', confirmClass = 'btn-primary') {
  let modal = document.getElementById(id);
  if (!modal) {
    modal = document.createElement('div');
    modal.id = id;
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">${title}</span>
        <button class="modal-close" onclick="closeModal('${id}')">&times;</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeModal('${id}')">Cancel</button>
        <button class="btn ${confirmClass}" id="${id}-confirm">${confirmLabel}</button>
      </div>
    </div>`;
  document.getElementById(`${id}-confirm`).onclick = onConfirm;
  openModal(id);
  return modal;
}

// ── Pagination helper ─────────────────────────────────────────────────────────
function paginationHtml(total, page, perPage) {
  const pages = Math.ceil(total / perPage);
  if (pages <= 1) return '';
  let html = '<div style="display:flex;gap:6px;padding:4px 8px;align-items:center;font-size:11px;color:var(--muted)">';
  html += `<span>${(page - 1) * perPage + 1}–${Math.min(page * perPage, total)} of ${total}</span>`;
  html += `<button class="btn btn-sm btn-secondary" ${page <= 1 ? 'disabled' : ''} onclick="changePage(${page - 1})">‹</button>`;
  html += `<button class="btn btn-sm btn-secondary" ${page >= pages ? 'disabled' : ''} onclick="changePage(${page + 1})">›</button>`;
  html += '</div>';
  return html;
}

window.escapeHtml      = escapeHtml;
window.showToast       = showToast;
window.formatDate      = formatDate;
window.formatDateShort = formatDateShort;
window.debounce        = debounce;
window.statusChip      = statusChip;
window.checkoutChip    = checkoutChip;
window.fileIcon        = fileIcon;
window.isCadFile       = isCadFile;
window.openModal       = openModal;
window.closeModal      = closeModal;
window.createModal     = createModal;
window.paginationHtml  = paginationHtml;
