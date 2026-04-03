/**
 * PLM Lite v2.2 — My Files panel
 *
 * Shows all temp files for the current user:
 *   - Checked-out files (writable) with Modified badge if unsaved
 *   - Read-only child copies
 * Allows: Check In, Disk Save, Clean Up all temp files.
 */

const TempPanel = (() => {
  let _user = null;

  async function init(user) {
    _user = user;
    document.getElementById('btn-cleanup-temp').addEventListener('click', cleanupTemp);
    await load();
  }

  async function load() {
    const container = document.getElementById('temp-list');
    container.innerHTML = '<div class="spinner"></div>';
    try {
      const files = await api.get('/api/me/temp');
      renderList(files);
    } catch (e) {
      container.innerHTML = `<p style="color:var(--danger);padding:20px">${e.message}</p>`;
    }
  }

  function renderList(files) {
    const container = document.getElementById('temp-list');
    if (!files.length) {
      container.innerHTML = '<p class="empty-hint">No temp files — nothing is checked out.</p>';
      return;
    }

    const checkedOut = files.filter(f => f.is_checked_out);
    const readOnly   = files.filter(f => !f.is_checked_out);

    let html = '';

    if (checkedOut.length) {
      html += `<div class="section-label" style="padding:8px 0 4px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Checked Out (writable)</div>`;
      checkedOut.forEach(f => {
        const modBadge = f.modified
          ? `<span class="chip" style="background:var(--warning);color:#000;font-size:10px;padding:1px 5px">● Unsaved</span>`
          : `<span class="chip" style="background:var(--success);color:#fff;font-size:10px;padding:1px 5px">✔ Saved</span>`;
        html += `<div class="doc-item">
          <div class="doc-icon">${fileIcon(f.file_type || '')}</div>
          <div class="doc-info">
            <div class="doc-name">${escapeHtml(f.filename)} ${modBadge}</div>
            <div class="doc-meta">${escapeHtml(f.item_id || '')} · Rev ${escapeHtml(f.revision || '')} · ${escapeHtml(f.item_name || '')}</div>
            <div class="doc-meta" style="color:var(--muted);font-size:10px">${escapeHtml(f.temp_path || '')}</div>
          </div>
          <div class="doc-actions">
            <button class="btn btn-secondary btn-sm" onclick="TempPanel.diskSave(${f.dataset_id})" title="Save to vault (keep checkout)">💾 Save</button>
            <button class="btn btn-secondary btn-sm" onclick="TempPanel.checkin(${f.dataset_id})" title="Check in">🔓 Check In</button>
          </div>
        </div>`;
      });
    }

    if (readOnly.length) {
      html += `<div class="section-label" style="padding:12px 0 4px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Child Files (read-only copies)</div>`;
      readOnly.forEach(f => {
        html += `<div class="doc-item" style="opacity:.75">
          <div class="doc-icon">${fileIcon(f.file_type || '')}</div>
          <div class="doc-info">
            <div class="doc-name">${escapeHtml(f.filename)}</div>
            <div class="doc-meta">${escapeHtml(f.item_id || '')} · Rev ${escapeHtml(f.revision || '')} · ${escapeHtml(f.item_name || '')}</div>
          </div>
          <div class="doc-actions"><span style="font-size:10px;color:var(--muted)">read-only</span></div>
        </div>`;
      });
    }

    container.innerHTML = html;
  }

  async function diskSave(dsId) {
    try {
      await api.post(`/api/datasets/${dsId}/disk-save`, {});
      showToast('Saved to vault (checkout retained)', 'success');
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function checkin(dsId) {
    try {
      await api.post(`/api/datasets/${dsId}/checkin`, {});
      showToast('Checked in', 'success');
      await load();
      if (PartsPanel && PartsPanel.load) PartsPanel.load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cleanupTemp() {
    // First try without force to detect unsaved files
    try {
      const result = await api.delete('/api/me/temp');
      if (result.has_unsaved) {
        const names = result.checked_out_files.join(', ');
        if (!confirm(`The following files have unsaved changes:\n\n${names}\n\nDiscard and clean up anyway?`)) return;
        await api.delete('/api/me/temp?force=true');
      }
      showToast('Temp files cleaned up', 'success');
      await load();
      if (PartsPanel && PartsPanel.load) PartsPanel.load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  return { init, load, diskSave, checkin, cleanupTemp };
})();

window.TempPanel = TempPanel;
