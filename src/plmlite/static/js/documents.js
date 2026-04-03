/**
 * PLM Lite v2.1 — Document Library panel
 *
 * Shows all datasets tracked in the DB (files auto-discovered by the watcher).
 * Files are opened via the server calling os.startfile() — no download/upload.
 */

const DocsPanel = (() => {
  let currentUser = null;

  async function init(user) {
    currentUser = user;
    document.getElementById('docs-search').addEventListener('input', debounce(load, 300));
    await load();
  }

  async function load() {
    const search    = document.getElementById('docs-search').value;
    const container = document.getElementById('docs-list');
    container.innerHTML = '<div class="spinner"></div>';
    try {
      const params = new URLSearchParams({ search });
      const docs   = await api.get(`/api/datasets?${params}`);
      renderDocs(docs);
    } catch (e) {
      container.innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
    }
  }

  function renderDocs(docs) {
    const container = document.getElementById('docs-list');
    if (!docs.length) {
      container.innerHTML = '<p class="empty-hint">No files tracked yet — save files to the configured watch path and they will appear here automatically.</p>';
      return;
    }

    // Group by item
    const byItem = {};
    docs.forEach(d => {
      const key = d.item_id;
      if (!byItem[key]) byItem[key] = { item_id: d.item_id, item_name: d.item_name, files: [] };
      byItem[key].files.push(d);
    });

    let html = '';
    Object.values(byItem).sort((a, b) => a.item_id.localeCompare(b.item_id)).forEach(grp => {
      html += `<div style="margin-bottom:16px">
        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;
                    letter-spacing:.5px;padding:0 0 6px;border-bottom:1px solid var(--border);margin-bottom:8px">
          ${grp.item_id} — ${grp.item_name}
        </div>`;
      grp.files.forEach(d => {
        const isCAD   = isCadFile(d.file_type);
        const openBtn = isCAD
          ? `<button class="btn btn-primary btn-sm"
               onclick="DocsPanel.openFile('${d.item_id}', ${d.id})"
               title="Open in application">Open</button>`
          : '';
        html += `<div class="doc-item">
          <div class="doc-icon">${fileIcon(d.file_type)}</div>
          <div class="doc-info">
            <div class="doc-name">${d.filename}</div>
            <div class="doc-meta">
              Rev ${d.revision} &nbsp;·&nbsp; ${d.adder} &nbsp;·&nbsp; ${formatDate(d.added_at)}
              ${d.file_size ? ' &nbsp;·&nbsp; ' + Math.round(d.file_size / 1024) + ' KB' : ''}
            </div>
            ${d.checked_out_by ? `<div style="margin-top:2px">${checkoutChip(d.checked_out_by)}</div>` : ''}
          </div>
          <div class="doc-actions">${openBtn}</div>
        </div>`;
      });
      html += '</div>';
    });
    container.innerHTML = html;
  }

  async function openFile(itemId, dsId) {
    try {
      const r = await api.get(`/api/items/${itemId}/datasets/${dsId}/open`);
      showToast(r.message, 'info');
    } catch (e) { showToast(e.message, 'error'); }
  }

  return { init, load, openFile };
})();

window.DocsPanel = DocsPanel;
