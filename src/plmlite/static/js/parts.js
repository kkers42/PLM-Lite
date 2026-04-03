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
    document.getElementById('btn-new-part').addEventListener('click', showNewItemModal);
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
    const isLocked     = item.status === 'released' || item.status === 'locked';
    const isCheckedOut = item.checked_out_by !== null;
    const isMine       = item.checked_out_by === currentUser.username;
    const canAdmin     = currentUser.role === 'admin';
    const canWrite     = currentUser.role !== 'readonly';

    document.getElementById('detail-pn').textContent          = item.item_id;
    document.getElementById('detail-rev-chip').innerHTML      =
      `<span class="chip" style="background:var(--surface2)">${item.latest_rev}</span>`;
    document.getElementById('detail-status-chip').innerHTML   = statusChip(item.status);
    document.getElementById('detail-checkout-chip').innerHTML = checkoutChip(item.checked_out_by);

    // Action bar
    const actBar = document.getElementById('detail-actions');
    actBar.innerHTML = `
      ${canWrite && !isLocked ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.editItem()">✏ Edit</button>` : ''}
      ${canWrite && !isCheckedOut ? `<button class="btn btn-primary btn-sm" onclick="PartsPanel.checkoutItem()">🔒 Checkout</button>` : ''}
      ${canWrite && isCheckedOut && (isMine || canAdmin) ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkinItem()">🔓 Check In</button>` : ''}
      ${canWrite && !isLocked ? `<button class="btn btn-success btn-sm" onclick="PartsPanel.releaseItem()">✔ Release</button>` : ''}
      ${canWrite ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.newRevision()">📌 New Revision</button>` : ''}
      ${canAdmin ? `<button class="btn btn-danger btn-sm" onclick="PartsPanel.deleteItem()">🗑 Delete</button>` : ''}
    `;

    // Details tab
    document.getElementById('detail-tab-details').innerHTML = `
      <div class="form-grid">
        <div class="form-group"><label>Item ID</label><div class="value" style="font-family:'Courier New',monospace;font-weight:700">${item.item_id}</div></div>
        <div class="form-group"><label>Revision</label><div class="value">${item.latest_rev}</div></div>
        <div class="form-group" style="grid-column:1/-1"><label>Name</label><div class="value">${item.name}</div></div>
        <div class="form-group"><label>Type</label><div class="value">${item.type_name || '—'}</div></div>
        <div class="form-group"><label>Status</label><div class="value">${statusChip(item.status)}</div></div>
        <div class="form-group" style="grid-column:1/-1"><label>Description</label><div class="value">${item.description || '—'}</div></div>
        <div class="form-group"><label>Created By</label><div class="value">${item.creator}</div></div>
        <div class="form-group"><label>Created</label><div class="value">${formatDate(item.created_at)}</div></div>
      </div>`;

    loadRevisions(item.item_id);
    loadDatasets(item.item_id);
    loadAudit(item.item_id);
  }

  // ── Revisions tab ─────────────────────────────────────────────────────────
  async function loadRevisions(itemId) {
    try {
      const revs = await api.get(`/api/items/${itemId}/revisions`);
      let html = revs.length ? '' : '<p style="color:var(--muted)">No revision history</p>';
      revs.forEach(r => {
        html += `<div class="revision-item">
          <div class="revision-badge">${r.revision}</div>
          <div class="revision-info">
            <div class="revision-label">Revision ${r.revision} &nbsp;${statusChip(r.status)}</div>
            <div class="revision-meta">${r.creator} · ${formatDate(r.created_at)}</div>
            ${r.releaser ? `<div class="revision-meta">Released by ${r.releaser} · ${formatDate(r.released_at)}</div>` : ''}
          </div>
        </div>`;
      });
      document.getElementById('detail-tab-revisions').innerHTML = html;
    } catch (_) {}
  }

  // ── Datasets (Documents) tab ───────────────────────────────────────────────
  async function loadDatasets(itemId) {
    try {
      const datasets = await api.get(`/api/items/${itemId}/datasets`);
      const canWrite  = currentUser.role !== 'readonly';
      let html = '';
      if (!datasets.length) {
        html = '<p style="color:var(--muted)">No files attached — save files to the watch path to auto-attach them.</p>';
      } else {
        datasets.forEach(d => {
          const isCAD    = isCadFile(d.file_type);
          const openBtn  = isCAD
            ? `<button class="btn btn-primary btn-sm" onclick="PartsPanel.openDataset('${itemId}', ${d.id})" title="Open in application">Open</button>`
            : '';
          const coBtn = !d.checked_out_by && canWrite
            ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkoutDataset('${itemId}', ${d.id})">🔒</button>`
            : (d.checked_out_by === currentUser.username && canWrite)
            ? `<button class="btn btn-secondary btn-sm" onclick="PartsPanel.checkinDataset('${itemId}', ${d.id})">🔓</button>`
            : '';
          html += `<div class="doc-item">
            <div class="doc-icon">${fileIcon(d.file_type)}</div>
            <div class="doc-info">
              <div class="doc-name">${d.filename}</div>
              <div class="doc-meta">${d.adder} · ${formatDate(d.added_at)}
                ${d.file_size ? ' · ' + Math.round(d.file_size / 1024) + ' KB' : ''}
              </div>
              ${d.checked_out_by ? `<div class="doc-meta" style="color:var(--warning)">${checkoutChip(d.checked_out_by)}</div>` : ''}
            </div>
            <div class="doc-actions">${openBtn}${coBtn}</div>
          </div>`;
        });
      }
      document.getElementById('detail-tab-docs').innerHTML = html;
    } catch (_) {}
  }

  async function openDataset(itemId, dsId) {
    try {
      const r = await api.get(`/api/items/${itemId}/datasets/${dsId}/open`);
      showToast(r.message, 'info');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkoutDataset(itemId, dsId) {
    try {
      await api.post(`/api/items/${itemId}/datasets/${dsId}/checkout`, {});
      showToast('Dataset checked out', 'success');
      await selectItem(itemId);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkinDataset(itemId, dsId) {
    try {
      await api.post(`/api/items/${itemId}/datasets/${dsId}/checkin`, {});
      showToast('Dataset checked in', 'success');
      await selectItem(itemId);
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
    editItem, createItem, checkoutItem, checkinItem, releaseItem, newRevision, deleteItem,
    openDataset, checkoutDataset, checkinDataset,
  };
})();

window.PartsPanel = PartsPanel;
