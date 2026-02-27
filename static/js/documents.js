/**
 * PLM Lite V1.0 — Documents library panel
 */

const DocsPanel = (() => {
  let currentUser = null;

  async function init(user) {
    currentUser = user;
    document.getElementById('docs-search').addEventListener('input', debounce(load, 300));
    if (user.can_upload) {
      document.getElementById('btn-upload-doc').style.display = '';
      document.getElementById('doc-file-input').addEventListener('change', uploadFile);
    }
    await load();
  }

  async function load() {
    const search = document.getElementById('docs-search').value.toLowerCase();
    const container = document.getElementById('docs-list');
    container.innerHTML = '<div class="spinner"></div>';
    try {
      let docs = await api.get('/api/documents');
      if (search) docs = docs.filter(d => d.filename.toLowerCase().includes(search) || (d.description || '').toLowerCase().includes(search));
      renderDocs(docs);
    } catch (e) {
      container.innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
    }
  }

  function renderDocs(docs) {
    const container = document.getElementById('docs-list');
    if (!docs.length) {
      container.innerHTML = '<p class="empty-hint">No documents uploaded yet</p>';
      return;
    }
    // Group by file_type
    const grouped = {};
    docs.forEach(d => {
      const g = (d.file_type || 'other').toUpperCase();
      if (!grouped[g]) grouped[g] = [];
      grouped[g].push(d);
    });

    let html = '';
    Object.keys(grouped).sort().forEach(group => {
      html += `<div style="margin-bottom:16px">
        <div style="font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;padding:0 0 6px;border-bottom:1px solid var(--border);margin-bottom:8px">${group}</div>`;
      grouped[group].forEach(d => {
        html += `<div class="doc-item">
          <div class="doc-icon">${fileIcon(d.file_type)}</div>
          <div class="doc-info">
            <div class="doc-name">${d.filename}</div>
            <div class="doc-meta">${d.uploaded_by_name || ''} · ${formatDate(d.uploaded_at)}${d.description ? ' · ' + d.description : ''}</div>
          </div>
          <div class="doc-actions">
            <a class="btn btn-secondary btn-sm" href="/api/documents/${d.id}/download" download title="Download">⬇</a>
            <button class="btn btn-secondary btn-sm" onclick="DocsPanel.showVersions(${d.id}, '${d.filename}')" title="Version history">🕐</button>
            ${currentUser.can_write ? `<button class="btn btn-danger btn-sm" onclick="DocsPanel.deleteDoc(${d.id})" title="Delete">🗑</button>` : ''}
          </div>
        </div>`;
      });
      html += '</div>';
    });
    container.innerHTML = html;
  }

  async function uploadFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      await api.upload('/api/documents', fd);
      showToast(`${file.name} uploaded`, 'success');
      e.target.value = '';
      await load();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function deleteDoc(docId) {
    if (!confirm('Delete this document?')) return;
    try {
      await api.delete(`/api/documents/${docId}`);
      showToast('Document deleted', 'info');
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function showVersions(docId, filename) {
    try {
      const versions = await api.get(`/api/documents/${docId}/versions`);
      let html = versions.length
        ? `<table class="data-table"><thead><tr><th>Version</th><th>Saved</th><th>Size</th><th></th></tr></thead><tbody>` +
          versions.map(v => `<tr>
            <td>${v.version_label}</td>
            <td>${formatDate(v.saved_at)}</td>
            <td>${v.file_size ? Math.round(v.file_size / 1024) + ' KB' : '—'}</td>
            <td>${currentUser.can_write ? `<button class="btn btn-sm btn-secondary" onclick="DocsPanel.restoreVersion(${docId}, ${v.id})">Restore</button>` : ''}</td>
          </tr>`).join('') + '</tbody></table>'
        : '<p style="color:var(--muted)">No backup versions</p>';
      createModal(`modal-versions-${docId}`, `Version History: ${filename}`, html,
        () => closeModal(`modal-versions-${docId}`), 'Close', 'btn-secondary');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function restoreVersion(docId, versionId) {
    if (!confirm('Restore this version? Current file will be moved to Temp/.')) return;
    try {
      await api.post(`/api/documents/${docId}/restore/${versionId}`, {});
      showToast('Version restored', 'success');
      closeModal(`modal-versions-${docId}`);
      await load();
    } catch (e) { showToast(e.message, 'error'); }
  }

  return { init, load, deleteDoc, showVersions, restoreVersion };
})();

window.DocsPanel = DocsPanel;
