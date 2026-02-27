/**
 * PLM Lite V1.0 — Parts panel
 */

const PartsPanel = (() => {
  let currentUser = null;
  let currentPartId = null;
  let currentPage = 1;

  // ── Init ──────────────────────────────────────────────────────────────────
  async function init(user) {
    currentUser = user;
    document.getElementById('parts-search').addEventListener('input', debounce(load, 350));
    document.getElementById('parts-status-filter').addEventListener('change', load);
    document.getElementById('parts-checkout-filter').addEventListener('change', load);
    document.getElementById('btn-new-part').addEventListener('click', showNewPartModal);
    await load();
  }

  // ── Load list ─────────────────────────────────────────────────────────────
  async function load() {
    const search = document.getElementById('parts-search').value;
    const status = document.getElementById('parts-status-filter').value;
    const coOnly = document.getElementById('parts-checkout-filter').checked;
    const tbody = document.getElementById('parts-tbody');
    tbody.innerHTML = '<tr class="loading-row"><td colspan="6"><div class="spinner"></div></td></tr>';

    try {
      const params = new URLSearchParams({ search, status, checked_out_only: coOnly, page: currentPage, per_page: 50 });
      const data = await api.get(`/api/parts?${params}`);
      renderList(data.items);
      document.getElementById('parts-pagination').innerHTML = paginationHtml(data.total, data.page, data.per_page);
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger);padding:20px">${e.message}</td></tr>`;
    }
  }

  window.changePage = (p) => { currentPage = p; load(); };

  function renderList(items) {
    const tbody = document.getElementById('parts-tbody');
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:40px">No parts found</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(p => `
      <tr data-id="${p.id}" onclick="PartsPanel.selectPart(${p.id})">
        <td><strong>${p.part_number}</strong></td>
        <td>${p.part_name}</td>
        <td>${p.part_revision}</td>
        <td>${statusChip(p.release_status)}</td>
        <td>${checkoutChip(p.checked_out_by_name)}</td>
        <td style="color:var(--muted);font-size:12px">${formatDateShort(p.updated_at)}</td>
      </tr>`).join('');
  }

  // ── Select part ───────────────────────────────────────────────────────────
  async function selectPart(id) {
    currentPartId = id;
    document.querySelectorAll('#parts-tbody tr').forEach(r => r.classList.toggle('selected', +r.dataset.id === id));
    document.getElementById('parts-detail-empty').style.display = 'none';
    document.getElementById('parts-detail').style.display = 'flex';

    try {
      const part = await api.get(`/api/parts/${id}`);
      renderDetail(part);
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

  function renderDetail(part) {
    const locked = part.is_locked;
    const isCheckedOut = part.checked_out_by !== null;
    const mineOrAdmin = part.checked_out_by === currentUser.id || currentUser.can_admin;

    document.getElementById('detail-pn').textContent = part.part_number;
    document.getElementById('detail-rev-chip').innerHTML = `<span class="chip" style="background:var(--surface2)">${part.part_revision}</span>`;
    document.getElementById('detail-status-chip').innerHTML = statusChip(part.release_status);
    document.getElementById('detail-checkout-chip').innerHTML = checkoutChip(part.checked_out_by_name);

    // Action buttons
    const actBar = document.getElementById('detail-actions');
    actBar.innerHTML = `
      ${currentUser.can_write && !locked ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.editPart()">✏️ Edit</button>` : ''}
      ${currentUser.can_checkout && !isCheckedOut ? `<button class="btn btn-primary btn-sm" onclick="PartsPanel.checkoutPart()">🔒 Checkout</button>` : ''}
      ${currentUser.can_checkout && isCheckedOut && mineOrAdmin ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkinPart()">🔓 Checkin</button>` : ''}
      ${currentUser.can_release && !locked ? `<button class="btn btn-success btn-sm" onclick="PartsPanel.releasePart()">✅ Release</button>` : ''}
      ${currentUser.can_release && locked ? `<button class="btn btn-danger btn-sm" onclick="PartsPanel.unreleasePart()">↩ Unreleased</button>` : ''}
      ${currentUser.can_write ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.bumpRevision()">📌 New Revision</button>` : ''}
      ${currentUser.can_admin ? `<button class="btn btn-danger btn-sm" onclick="PartsPanel.deletePart()">🗑 Delete</button>` : ''}
    `;

    // Details tab
    document.getElementById('detail-tab-details').innerHTML = `
      <div class="form-grid">
        <div class="form-group"><label>Part Number</label><div class="value">${part.part_number}</div></div>
        <div class="form-group"><label>Revision</label><div class="value">${part.part_revision}</div></div>
        <div class="form-group"><label>Part Name</label><div class="value">${part.part_name}</div></div>
        <div class="form-group"><label>Part Level</label><div class="value">${part.part_level || '—'}</div></div>
        <div class="form-group one-col" style="grid-column:1/-1"><label>Description</label><div class="value">${part.description || '—'}</div></div>
        <div class="form-group"><label>Created By</label><div class="value">${part.created_by_name}</div></div>
        <div class="form-group"><label>Created</label><div class="value">${formatDate(part.created_at)}</div></div>
        <div class="form-group"><label>Last Updated</label><div class="value">${formatDate(part.updated_at)}</div></div>
        <div class="form-group"><label>Status</label><div class="value">${statusChip(part.release_status)}</div></div>
      </div>`;

    loadAttributes(part);
    loadRevisions(part.id);
    loadPartDocs(part.id);
  }

  // ── Attributes ─────────────────────────────────────────────────────────────
  async function loadAttributes(part) {
    const attrs = part.attributes || [];
    const canWrite = currentUser.can_write && !part.is_locked;
    let html = `<table class="attr-table">
      <thead><tr><th>Attribute</th><th>Value</th>${canWrite ? '<th></th>' : ''}</tr></thead><tbody>`;
    attrs.forEach(a => {
      html += `<tr>
        <td>${a.attr_key}</td>
        <td>${canWrite
          ? `<input type="text" value="${a.attr_value || ''}" onblur="PartsPanel.saveAttr('${a.attr_key}', this.value, ${a.attr_order})">`
          : (a.attr_value || '—')}
        </td>
        ${canWrite ? `<td><button class="attr-del" onclick="PartsPanel.delAttr('${a.attr_key}')">✕</button></td>` : ''}
      </tr>`;
    });
    html += '</tbody></table>';
    if (canWrite) {
      html += `<div style="margin-top:12px;display:flex;gap:8px">
        <input id="new-attr-key" placeholder="Attribute name" style="flex:1">
        <input id="new-attr-val" placeholder="Value" style="flex:2">
        <button class="btn btn-secondary btn-sm" onclick="PartsPanel.addAttr()">+ Add</button>
      </div>`;
    }
    document.getElementById('detail-tab-attrs').innerHTML = html;
  }

  async function saveAttr(key, value, order) {
    try {
      await api.put(`/api/parts/${currentPartId}/attributes`, { key, value, order });
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function delAttr(key) {
    try {
      await api.delete(`/api/parts/${currentPartId}/attributes/${encodeURIComponent(key)}`);
      await selectPart(currentPartId);
      showToast('Attribute removed', 'info');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function addAttr() {
    const key = document.getElementById('new-attr-key').value.trim();
    const val = document.getElementById('new-attr-val').value.trim();
    if (!key) return showToast('Enter an attribute name', 'error');
    try {
      await api.put(`/api/parts/${currentPartId}/attributes`, { key, value: val, order: 0 });
      await selectPart(currentPartId);
      showToast('Attribute saved', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Revisions ─────────────────────────────────────────────────────────────
  async function loadRevisions(partId) {
    try {
      const revs = await api.get(`/api/parts/${partId}/revisions`);
      let html = revs.length ? '' : '<p style="color:var(--muted)">No revision history</p>';
      revs.forEach(r => {
        html += `<div class="revision-item">
          <div class="revision-badge">${r.revision_label}</div>
          <div class="revision-info">
            <div class="revision-label">Revision ${r.revision_label}</div>
            <div class="revision-meta">${r.changed_by_name} · ${formatDate(r.changed_at)}</div>
            ${r.description ? `<div class="revision-desc">${r.description}</div>` : ''}
          </div>
        </div>`;
      });
      document.getElementById('detail-tab-revisions').innerHTML = html;
    } catch (e) { /* skip */ }
  }

  // ── Part docs ─────────────────────────────────────────────────────────────
  async function loadPartDocs(partId) {
    try {
      const docs = await api.get(`/api/parts/${partId}/documents`);
      let html = '';
      if (!docs.length) html = '<p style="color:var(--muted)">No documents attached</p>';
      docs.forEach(d => {
        html += `<div class="doc-item">
          <div class="doc-icon">${fileIcon(d.file_type)}</div>
          <div class="doc-info">
            <div class="doc-name">${d.filename}</div>
            <div class="doc-meta">${d.uploaded_by_name} · ${formatDate(d.uploaded_at)}</div>
          </div>
          <div class="doc-actions">
            <a class="btn btn-secondary btn-sm" href="/api/documents/${d.id}/download" download>⬇</a>
            ${currentUser.can_write ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.detachDoc(${d.id})">✕</button>` : ''}
          </div>
        </div>`;
      });
      if (currentUser.can_upload) {
        html += `<div style="margin-top:12px">
          <label class="btn btn-secondary btn-sm" style="cursor:pointer">
            📎 Attach file
            <input type="file" style="display:none" onchange="PartsPanel.uploadDoc(this)">
          </label>
        </div>`;
      }
      document.getElementById('detail-tab-docs').innerHTML = html;
    } catch (e) { /* skip */ }
  }

  async function uploadDoc(input) {
    const file = input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    if (currentPartId) fd.append('part_id', currentPartId);
    try {
      await api.upload('/api/documents', fd);
      showToast('File uploaded', 'success');
      loadPartDocs(currentPartId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function detachDoc(docId) {
    try {
      await api.delete(`/api/parts/${currentPartId}/documents/${docId}`);
      showToast('Document detached', 'info');
      loadPartDocs(currentPartId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  function showNewPartModal() {
    createModal('modal-new-part', 'New Part', `
      <div class="form-grid">
        <div class="form-group"><label>Part Number *</label><input id="np-pn" placeholder="e.g. PN-00001"></div>
        <div class="form-group"><label>Revision</label><input id="np-rev" value="A"></div>
        <div class="form-group" style="grid-column:1/-1"><label>Part Name *</label><input id="np-name"></div>
        <div class="form-group"><label>Part Level</label>
          <select id="np-level"><option value="">—</option><option>System</option><option>Subsystem</option><option>Assembly</option><option>Component</option><option>Raw Material</option></select>
        </div>
        <div class="form-group" style="grid-column:1/-1"><label>Description</label><textarea id="np-desc"></textarea></div>
      </div>`, createPart);
  }

  async function createPart() {
    const body = {
      part_number: document.getElementById('np-pn').value.trim(),
      part_name: document.getElementById('np-name').value.trim(),
      part_revision: document.getElementById('np-rev').value.trim() || 'A',
      part_level: document.getElementById('np-level').value,
      description: document.getElementById('np-desc').value.trim(),
    };
    if (!body.part_number || !body.part_name) return showToast('Part Number and Name are required', 'error');
    try {
      await api.post('/api/parts', body);
      closeModal('modal-new-part');
      showToast(`Part ${body.part_number} created`, 'success');
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  function editPart() {
    api.get(`/api/parts/${currentPartId}`).then(part => {
      createModal('modal-edit-part', 'Edit Part', `
        <div class="form-grid">
          <div class="form-group" style="grid-column:1/-1"><label>Part Name *</label><input id="ep-name" value="${part.part_name}"></div>
          <div class="form-group"><label>Part Level</label>
            <select id="ep-level">
              <option value="">—</option>
              ${['System','Subsystem','Assembly','Component','Raw Material'].map(l => `<option${part.part_level===l?' selected':''}>${l}</option>`).join('')}
            </select>
          </div>
          <div class="form-group" style="grid-column:1/-1"><label>Description</label><textarea id="ep-desc">${part.description || ''}</textarea></div>
        </div>`, updatePart);
    });
  }

  async function updatePart() {
    const body = {
      part_name: document.getElementById('ep-name').value.trim(),
      part_level: document.getElementById('ep-level').value,
      description: document.getElementById('ep-desc').value.trim(),
    };
    if (!body.part_name) return showToast('Part Name is required', 'error');
    try {
      await api.put(`/api/parts/${currentPartId}`, body);
      closeModal('modal-edit-part');
      showToast('Part updated', 'success');
      await selectPart(currentPartId);
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkoutPart() {
    try {
      const station = navigator.userAgent.substring(0, 40);
      await api.post(`/api/parts/${currentPartId}/checkout`, { station });
      showToast('Part checked out', 'success');
      await selectPart(currentPartId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkinPart() {
    try {
      await api.post(`/api/parts/${currentPartId}/checkin`, {});
      showToast('Part checked in', 'success');
      await selectPart(currentPartId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function releasePart() {
    if (!confirm('Release this part? It will be locked from editing.')) return;
    try {
      await api.post(`/api/parts/${currentPartId}/release`, {});
      showToast('Part released', 'success');
      await selectPart(currentPartId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function unreleasePart() {
    if (!confirm('Revert to Prototype? This unlocks the part for editing.')) return;
    try {
      await api.post(`/api/parts/${currentPartId}/unreleased`, {});
      showToast('Part set back to Prototype', 'info');
      await selectPart(currentPartId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function bumpRevision() {
    createModal('modal-bump-rev', 'New Revision', `
      <div class="form-group"><label>Reason / Change Description</label><textarea id="rev-desc"></textarea></div>
    `, async () => {
      const desc = document.getElementById('rev-desc').value.trim();
      try {
        const result = await api.post(`/api/parts/${currentPartId}/revise`, { description: desc });
        closeModal('modal-bump-rev');
        showToast(result.message, 'success');
        await selectPart(currentPartId); await load();
      } catch (e) { showToast(e.message, 'error'); }
    });
  }

  async function deletePart() {
    if (!confirm('Permanently delete this part?')) return;
    try {
      await api.delete(`/api/parts/${currentPartId}`);
      showToast('Part deleted', 'info');
      currentPartId = null;
      document.getElementById('parts-detail-empty').style.display = '';
      document.getElementById('parts-detail').style.display = 'none';
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  return { init, load, selectPart, editPart, createPart, checkoutPart, checkinPart,
           releasePart, unreleasePart, bumpRevision, deletePart,
           saveAttr, delAttr, addAttr, uploadDoc, detachDoc };
})();

window.PartsPanel = PartsPanel;
