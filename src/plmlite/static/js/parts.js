/**
 * PLM Lite v2.1 — Parts / Items panel
 *
 * API mapping vs v1.0 web PLM:
 *   part_number       → item.item_id
 *   part_name         → item.name
 *   part_revision     → item.latest_rev
 *   release_status    → item.status
 *   checked_out_by_name → item.checked_out_by
 */

const PartsPanel = (() => {
  let currentUser   = null;
  let currentItemId = null;  // string like "ITM-00001"
  let currentPage   = 1;

  // ── Init ──────────────────────────────────────────────────────────────────
  async function init(user) {
    currentUser = user;
    document.getElementById('parts-search').addEventListener('input', debounce(load, 350));
    document.getElementById('parts-status-filter').addEventListener('change', load);
    document.getElementById('parts-checkout-filter').addEventListener('change', load);
    const newPartBtn = document.getElementById('btn-new-part');
    const canCreate  = (user.permissions || []).includes('parts.create');
    if (canCreate) {
      newPartBtn.addEventListener('click', showNewItemModal);
    } else {
      newPartBtn.style.display = 'none';
    }
    await load();
  }

  // ── Load list ─────────────────────────────────────────────────────────────
  async function load() {
    const search  = document.getElementById('parts-search').value;
    const status  = document.getElementById('parts-status-filter').value;
    const coOnly  = document.getElementById('parts-checkout-filter').checked;
    const tbody   = document.getElementById('parts-tbody');
    tbody.innerHTML = '<tr class="loading-row"><td colspan="6"><div class="spinner"></div></td></tr>';

    try {
      const params = new URLSearchParams({ search, status, checked_out_only: coOnly,
                                           page: currentPage, per_page: 50 });
      const data = await api.get(`/api/items?${params}`);
      renderList(data.items);
      document.getElementById('parts-pagination').innerHTML =
        paginationHtml(data.total, data.page, data.per_page);
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger);padding:20px">${e.message}</td></tr>`;
    }
  }

  window.changePage = (p) => { currentPage = p; load(); };

  function renderList(items) {
    const tbody = document.getElementById('parts-tbody');
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:40px">No items found</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(p => `
      <tr data-id="${p.item_id}" onclick="PartsPanel.selectItem('${p.item_id}')">
        <td><strong>${p.item_id}</strong></td>
        <td>${p.name}</td>
        <td>${p.latest_rev}</td>
        <td>${statusChip(p.status)}</td>
        <td>${checkoutChip(p.checked_out_by)}</td>
        <td style="color:var(--muted);font-size:12px">${formatDateShort(p.created_at)}</td>
      </tr>`).join('');
  }

  // ── Select item ───────────────────────────────────────────────────────────
  async function selectItem(itemId) {
    currentItemId = itemId;
    document.querySelectorAll('#parts-tbody tr').forEach(r =>
      r.classList.toggle('selected', r.dataset.id === itemId));
    document.getElementById('parts-detail-empty').style.display = 'none';
    document.getElementById('parts-detail').style.display = 'flex';

    try {
      const item = await api.get(`/api/items/${itemId}`);
      renderDetail(item);
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

  function renderDetail(item) {
    const perms        = (currentUser && currentUser.permissions) || [];
    const isLocked     = item.status === 'released' || item.status === 'locked';
    const isCheckedOut = item.checked_out_by !== null;
    const isMine       = item.checked_out_by === currentUser.username;
    const canAdmin     = perms.includes('users.manage');
    const canWrite     = perms.includes('parts.edit') || perms.includes('parts.create');
    const canCreate    = perms.includes('parts.create');
    const canEdit      = perms.includes('parts.edit');
    const canDelete    = perms.includes('parts.delete');
    const canCheckout  = perms.includes('datasets.checkout');
    const canCheckinOwn = perms.includes('datasets.checkin_own');
    const canCheckinAny = perms.includes('datasets.checkin_any');
    const canUpload    = perms.includes('datasets.upload');
    const canNewRev    = perms.includes('revisions.create');
    const canRelease   = perms.includes('revisions.release');

    document.getElementById('detail-pn').textContent          = item.item_id;
    document.getElementById('detail-rev-chip').innerHTML      =
      `<span class="chip" style="background:var(--surface2)">${item.latest_rev}</span>`;
    document.getElementById('detail-status-chip').innerHTML   = statusChip(item.status);
    document.getElementById('detail-checkout-chip').innerHTML = checkoutChip(item.checked_out_by);

    // Action bar
    const actBar = document.getElementById('detail-actions');
    actBar.innerHTML = `
      ${canEdit && !isLocked ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.editItem()">✏ Edit</button>` : ''}
      ${canCheckout && !isCheckedOut ? `<button class="btn btn-primary btn-sm" onclick="PartsPanel.checkoutItem()">🔒 Checkout</button>` : ''}
      ${isCheckedOut && (isMine && canCheckinOwn || canCheckinAny) ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkinItem()">🔓 Check In</button>` : ''}
      ${canRelease && !isLocked ? `<button class="btn btn-success btn-sm" onclick="PartsPanel.releaseItem()">✔ Release</button>` : ''}
      ${canNewRev ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.newRevision()">📌 New Revision</button>` : ''}
      ${canDelete ? `<button class="btn btn-danger btn-sm" onclick="PartsPanel.deleteItem()">🗑 Delete</button>` : ''}
    `;

    // Details tab — show all fields, with Edit button inline
    document.getElementById('detail-tab-details').innerHTML = `
  <form id="item-edit-form" class="form-grid" onsubmit="return false">
    <div class="form-group"><label>Item ID</label><input id="ei-item-id" value="${escapeHtml(item.item_id)}" ${isLocked || !canEdit ? 'disabled' : ''}></div>
    <div class="form-group"><label>Revision</label><div class="value">${item.latest_rev}</div></div>
    <div class="form-group" style="grid-column:1/-1"><label>Name</label><input id="ei-name" value="${item.name.replace(/"/g,'&quot;')}" ${isLocked || !canEdit ? 'disabled' : ''}></div>
    <div class="form-group"><label>Type</label>
      <select id="ei-type" ${isLocked || !canEdit ? 'disabled' : ''}>
        ${['Mechanical Part','Assembly','Prototype','Document'].map(t =>
          `<option${item.type_name===t?' selected':''}>${t}</option>`).join('')}
      </select>
    </div>
    <div class="form-group"><label>Status</label><div class="value">${statusChip(item.status)}</div></div>
    <div class="form-group" style="grid-column:1/-1"><label>Description</label>
      <textarea id="ei-desc" ${isLocked || !canEdit ? 'disabled' : ''}>${escapeHtml(item.description || '')}</textarea>
    </div>
    <div class="form-group"><label>Created By</label><div class="value">${item.creator}</div></div>
    <div class="form-group"><label>Created</label><div class="value">${formatDate(item.created_at)}</div></div>
    ${canEdit && !isLocked ? `<div style="grid-column:1/-1;display:flex;gap:6px;margin-top:4px">
      <button class="btn btn-primary btn-sm" onclick="PartsPanel.saveItemEdits()">💾 Save</button>
    </div>` : ''}
  </form>
  <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <strong style="font-size:12px">Custom Fields</strong>
      ${canEdit ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.addAttribute('${escapeHtml(item.item_id)}')">+ Add Field</button>` : ''}
    </div>
    <div id="attrs-list"><div class="spinner"></div></div>
  </div>`;

    // Load custom attributes
    loadAttributes(item.item_id);

    loadRevisions(item.item_id);
    loadDatasets(item.item_id);
    loadAudit(item.item_id);
  }

  // ── Inline edit save ──────────────────────────────────────────────────────
  async function saveItemEdits() {
    const body = {
      item_id:     document.getElementById('ei-item-id').value.trim(),
      name:        document.getElementById('ei-name').value.trim(),
      item_type:   document.getElementById('ei-type').value,
      description: document.getElementById('ei-desc').value.trim(),
    };
    if (!body.name) return showToast('Name is required', 'error');
    try {
      await api.patch(`/api/items/${currentItemId}`, body);
      showToast('Saved', 'success');
      // If item_id changed, update currentItemId
      if (body.item_id && body.item_id !== currentItemId) currentItemId = body.item_id;
      await selectItem(currentItemId);
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Custom attributes ─────────────────────────────────────────────────────
  async function loadAttributes(itemId) {
    const container = document.getElementById('attrs-list');
    if (!container) return;
    try {
      const attrs = await api.get(`/api/items/${itemId}/attributes`);
      const canWrite = (currentUser && currentUser.permissions || []).includes('parts.edit');
      if (!attrs.length) {
        container.innerHTML = '<p style="color:var(--muted);font-size:12px">No custom fields</p>';
        return;
      }
      container.innerHTML = attrs.map(a => `
        <div class="form-group" style="display:flex;gap:6px;align-items:flex-end;margin-bottom:4px">
          <div style="flex:0 0 140px"><label style="font-size:11px">${escapeHtml(a.attr_key)}</label>
            <input value="${escapeHtml(a.attr_value)}" id="attr-val-${a.id}"
              onchange="PartsPanel.updateAttributeValue('${escapeHtml(itemId)}','${escapeHtml(a.attr_key)}',this.value)">
          </div>
          ${canWrite ? `<button class="btn btn-danger btn-sm" style="margin-bottom:2px"
            onclick="PartsPanel.deleteAttribute('${escapeHtml(itemId)}','${escapeHtml(a.attr_key)}')">✕</button>` : ''}
        </div>`).join('');
    } catch (_) {}
  }

  async function addAttribute(itemId) {
    const key = prompt('Field name:');
    if (!key) return;
    const value = prompt(`Value for "${key}":`, '');
    if (value === null) return;
    try {
      await api.post(`/api/items/${itemId}/attributes`, { key, value });
      loadAttributes(itemId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function updateAttributeValue(itemId, key, value) {
    try {
      await api.post(`/api/items/${itemId}/attributes`, { key, value });
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function deleteAttribute(itemId, key) {
    try {
      await api.delete(`/api/items/${itemId}/attributes/${encodeURIComponent(key)}`);
      loadAttributes(itemId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Revisions tab ─────────────────────────────────────────────────────────
  async function loadRevisions(itemId) {
    try {
      const revs = await api.get(`/api/items/${itemId}/revisions`);
      const canWrite = (currentUser && currentUser.permissions || []).includes('revisions.create');
      let html = revs.length ? '' : '<p style="color:var(--muted)">No revision history</p>';
      revs.forEach(r => {
        html += `<div class="revision-item" style="flex-direction:column;align-items:flex-start;gap:6px">
          <div style="display:flex;align-items:center;gap:8px;width:100%">
            <div class="revision-badge">${r.revision}</div>
            <div class="revision-info" style="flex:1">
              <div class="revision-label">Revision ${r.revision} &nbsp;${statusChip(r.status)}</div>
              <div class="revision-meta">${r.creator} · ${formatDate(r.created_at)}</div>
              ${r.releaser ? `<div class="revision-meta">Released by ${r.releaser} · ${formatDate(r.released_at)}</div>` : ''}
            </div>
          </div>
          <div style="width:100%;padding-left:36px">
            <label style="font-size:11px;color:var(--muted)">Change Description</label>
            <textarea id="rev-desc-${r.id}" style="width:100%;min-height:80px;font-size:12px;resize:vertical"
              ${!canWrite ? 'readonly' : ''}
              onblur="PartsPanel.saveRevisionDesc('${escapeHtml(itemId)}',${r.id},this.value)"
            >${escapeHtml(r.change_description || '')}</textarea>
          </div>
        </div>`;
      });
      document.getElementById('detail-tab-revisions').innerHTML = html;
    } catch (_) {}
  }

  async function saveRevisionDesc(itemId, revId, desc) {
    try {
      await api.patch(`/api/items/${itemId}/revisions/${revId}`, { change_description: desc });
    } catch (_) {}
  }

  // ── Datasets (Documents) tab ───────────────────────────────────────────────
  async function loadDatasets(itemId) {
    try {
      const datasets = await api.get(`/api/items/${itemId}/datasets`);
      const perms     = (currentUser && currentUser.permissions) || [];
      const canWrite  = perms.includes('parts.edit') || perms.includes('datasets.upload');
      const canUpload = perms.includes('datasets.upload');
      const canCheckout = perms.includes('datasets.checkout');
      const canCheckinOwn = perms.includes('datasets.checkin_own');
      const canCheckinAny = perms.includes('datasets.checkin_any');
      let filesHtml = '';

      if (!datasets.length) {
        filesHtml = '<p style="color:var(--muted);margin:8px 0">No files attached — drag files here or use Attach File.</p>';
      } else {
        datasets.forEach(d => {
          const isMineOut  = currentUser && d.checked_out_by === currentUser.username;
          const canCheckinThis = isMineOut ? canCheckinOwn : canCheckinAny;
          const openBtn    = `<button class="btn btn-primary btn-sm" onclick="PartsPanel.openDataset('${itemId}', ${d.id})" title="Open in application">Open</button>`;
          const coBtn = !d.checked_out_by && canCheckout
            ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkoutDataset(${d.id},'${itemId}')" title="Checkout">🔒</button>`
            : (d.checked_out_by && canCheckinThis)
            ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkinDataset(${d.id},'${itemId}')" title="Check In">🔓</button>`
            : '';
          const diskSaveBtn = isMineOut && canCheckinOwn
            ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.diskSaveDataset(${d.id},'${itemId}')" title="Save to vault (keep checkout)">💾 Save</button>`
            : '';
          const newRevBtn = isMineOut && canCheckinOwn
            ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.saveAsNewRevDataset(${d.id},'${itemId}')" title="Save as new revision">📌 New Rev</button>`
            : '';
          const modBadge = d.modified
            ? `<span class="chip" style="background:var(--warning);color:#000;font-size:10px;padding:1px 5px">● Modified</span>`
            : '';
          filesHtml += `<div class="doc-item" ondblclick="PartsPanel.openDataset('${itemId}', ${d.id})" style="cursor:pointer" title="Double-click to open">
            <div class="doc-icon">${fileIcon(d.file_type)}</div>
            <div class="doc-info">
              <div class="doc-name">${escapeHtml(d.filename)} ${modBadge}</div>
              <div class="doc-meta">${d.adder || ''} · ${formatDate(d.added_at)}
                ${d.file_size ? ' · ' + Math.round(d.file_size / 1024) + ' KB' : ''}
              </div>
              ${d.checked_out_by ? `<div class="doc-meta" style="color:var(--warning)">${checkoutChip(d.checked_out_by)}</div>` : ''}
            </div>
            <div class="doc-actions">${openBtn}${coBtn}${diskSaveBtn}${newRevBtn}</div>
          </div>`;
        });
      }

      const attachBtn = canUpload
        ? `<label class="btn btn-secondary btn-sm" style="cursor:pointer">
             📎 Attach File
             <input type="file" multiple style="display:none" onchange="PartsPanel.attachFiles('${itemId}', this)">
           </label>`
        : '';

      const dropZone = canUpload ? `
        <div id="drop-zone-${itemId}" style="
          border:2px dashed var(--border);border-radius:6px;padding:16px;
          text-align:center;color:var(--muted);font-size:12px;margin-bottom:10px;
          transition:border-color .2s,background .2s"
          ondragover="PartsPanel.onDragOver(event,'${itemId}')"
          ondragleave="PartsPanel.onDragLeave(event,'${itemId}')"
          ondrop="PartsPanel.onDrop(event,'${itemId}')">
          Drop files here &nbsp;·&nbsp; ${attachBtn}
        </div>` : '';

      document.getElementById('detail-tab-docs').innerHTML = dropZone + filesHtml;
    } catch (e) {
      document.getElementById('detail-tab-docs').innerHTML =
        `<p style="color:var(--danger)">Error loading files: ${e.message}</p>`;
    }
  }

  async function _uploadFile(itemId, file) {
    const form = new FormData();
    form.append('file', file);
    const r = await fetch(`/api/items/${itemId}/datasets`, { method: 'POST', body: form });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Upload failed');
    return data.message;
  }

  async function attachFiles(itemId, input) {
    const files = [...input.files];
    if (!files.length) return;
    let ok = 0, errors = [];
    for (const f of files) {
      try { await _uploadFile(itemId, f); ok++; }
      catch (e) { errors.push(`${f.name}: ${e.message}`); }
    }
    if (ok)     showToast(`${ok} file(s) attached`, 'success');
    if (errors.length) errors.forEach(m => showToast(m, 'error'));
    input.value = '';
    loadDatasets(itemId);
  }

  function onDragOver(e, itemId) {
    e.preventDefault();
    const z = document.getElementById(`drop-zone-${itemId}`);
    if (z) { z.style.borderColor = 'var(--accent)'; z.style.background = 'rgba(233,84,32,.07)'; }
  }

  function onDragLeave(e, itemId) {
    const z = document.getElementById(`drop-zone-${itemId}`);
    if (z) { z.style.borderColor = 'var(--border)'; z.style.background = ''; }
  }

  async function onDrop(e, itemId) {
    e.preventDefault();
    onDragLeave(e, itemId);
    const files = [...e.dataTransfer.files];
    if (!files.length) return;
    let ok = 0, errors = [];
    for (const f of files) {
      try { await _uploadFile(itemId, f); ok++; }
      catch (err) { errors.push(`${f.name}: ${err.message}`); }
    }
    if (ok)     showToast(`${ok} file(s) attached`, 'success');
    if (errors.length) errors.forEach(m => showToast(m, 'error'));
    loadDatasets(itemId);
  }

  async function openDataset(itemId, dsId) {
    try {
      const r = await api.get(`/api/items/${itemId}/datasets/${dsId}/open`);
      showToast(r.message, 'info');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkoutDataset(dsId, itemId) {
    try {
      const r = await api.post(`/api/datasets/${dsId}/checkout`, {});
      showToast(r.message || 'Checked out', 'success');
      if (TempPanel && TempPanel.load) TempPanel.load();
      await selectItem(itemId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkinDataset(dsId, itemId) {
    try {
      await api.post(`/api/datasets/${dsId}/checkin`, {});
      showToast('Checked in', 'success');
      if (TempPanel && TempPanel.load) TempPanel.load();
      await selectItem(itemId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function diskSaveDataset(dsId, itemId) {
    try {
      await api.post(`/api/datasets/${dsId}/disk-save`, {});
      showToast('Saved to vault (checkout retained)', 'success');
      await selectItem(itemId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function saveAsNewRevDataset(dsId, itemId) {
    const desc = prompt('Change description (optional):', '');
    if (desc === null) return;  // cancelled
    try {
      const r = await api.post(`/api/datasets/${dsId}/save-as-new-revision`, { change_description: desc });
      showToast(`Saved as revision ${r.revision}`, 'success');
      if (TempPanel && TempPanel.load) TempPanel.load();
      await selectItem(itemId);
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Audit tab ─────────────────────────────────────────────────────────────
  async function loadAudit(itemId) {
    try {
      const entries = await api.get(`/api/audit?item_id=${itemId}`);
      let html = '';
      if (!entries.length) {
        html = '<p style="color:var(--muted)">No audit entries</p>';
      } else {
        html = '<table class="data-table"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr></thead><tbody>';
        entries.slice().reverse().forEach(e => {
          html += `<tr>
            <td style="font-size:11px;color:var(--muted);white-space:nowrap">${formatDate(e.performed_at)}</td>
            <td>${e.who || '—'}</td>
            <td><code style="font-size:11px">${e.action}</code></td>
            <td style="font-size:11px;color:var(--muted)">${e.detail || ''}</td>
          </tr>`;
        });
        html += '</tbody></table>';
      }
      document.getElementById('detail-tab-attrs').innerHTML = html;
    } catch (_) {}
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  function showNewItemModal() {
    const types = ['Mechanical Part', 'Assembly', 'Prototype', 'Document'];
    createModal('modal-new-item', 'New Item', `
      <div class="form-grid">
        <div class="form-group" style="grid-column:1/-1"><label>Name *</label><input id="ni-name" placeholder="e.g. Bracket, Shaft, Housing…"></div>
        <div class="form-group"><label>Item Type</label>
          <select id="ni-type">${types.map(t => `<option>${t}</option>`).join('')}</select>
        </div>
        <div class="form-group" style="grid-column:1/-1"><label>Description</label><textarea id="ni-desc"></textarea></div>
      </div>`, createItem);
  }

  async function createItem() {
    const body = {
      name:        document.getElementById('ni-name').value.trim(),
      description: document.getElementById('ni-desc').value.trim(),
      item_type:   document.getElementById('ni-type').value,
    };
    if (!body.name) return showToast('Name is required', 'error');
    try {
      const r = await api.post('/api/items', body);
      closeModal('modal-new-item');
      showToast(r.message, 'success');
      await load();
      await selectItem(r.item_id);
    } catch (e) { showToast(e.message, 'error'); }
  }

  function editItem() {
    api.get(`/api/items/${currentItemId}`).then(item => {
      createModal('modal-edit-item', 'Edit Item', `
        <div class="form-grid">
          <div class="form-group" style="grid-column:1/-1"><label>Name *</label><input id="ei-name" value="${item.name.replace(/"/g, '&quot;')}"></div>
          <div class="form-group" style="grid-column:1/-1"><label>Description</label><textarea id="ei-desc">${item.description || ''}</textarea></div>
        </div>`, updateItem);
    });
  }

  async function updateItem() {
    const body = {
      name:        document.getElementById('ei-name').value.trim(),
      description: document.getElementById('ei-desc').value.trim(),
    };
    if (!body.name) return showToast('Name is required', 'error');
    try {
      await api.put(`/api/items/${currentItemId}`, body);
      closeModal('modal-edit-item');
      showToast('Item updated', 'success');
      await selectItem(currentItemId);
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkoutItem() {
    try {
      await api.post(`/api/items/${currentItemId}/checkout`, {});
      showToast('Checked out', 'success');
      await selectItem(currentItemId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkinItem() {
    try {
      await api.post(`/api/items/${currentItemId}/checkin`, {});
      showToast('Checked in', 'success');
      await selectItem(currentItemId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function releaseItem() {
    if (!confirm('Release this item? The current revision will be marked Released.')) return;
    try {
      await api.post(`/api/items/${currentItemId}/release`, {});
      showToast('Item released', 'success');
      await selectItem(currentItemId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function newRevision() {
    if (!confirm(`Create a new revision for ${currentItemId}?`)) return;
    try {
      const r = await api.post(`/api/items/${currentItemId}/revisions`, {});
      showToast(`Revision ${r.revision} created`, 'success');
      await selectItem(currentItemId); await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function deleteItem() {
    if (!confirm(`Permanently delete ${currentItemId}?`)) return;
    try {
      await api.delete(`/api/items/${currentItemId}`);
      showToast('Item deleted', 'info');
      currentItemId = null;
      document.getElementById('parts-detail-empty').style.display = '';
      document.getElementById('parts-detail').style.display = 'none';
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  return {
    init, load, selectItem,
    editItem, saveItemEdits, createItem, checkoutItem, checkinItem, releaseItem, newRevision, deleteItem,
    attachFiles, onDragOver, onDragLeave, onDrop,
    openDataset, checkoutDataset, checkinDataset, diskSaveDataset, saveAsNewRevDataset,
    loadAttributes, addAttribute, updateAttributeValue, deleteAttribute,
    saveRevisionDesc,
  };
})();

window.PartsPanel = PartsPanel;
