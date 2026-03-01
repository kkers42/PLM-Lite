/**
 * PLM Lite V1.0 — Documents library panel
 */

const DocsPanel = (() => {
  let currentUser = null;
  let openInplace = false;

  async function init(user) {
    currentUser = user;
    document.getElementById('docs-search').addEventListener('input', debounce(load, 300));
    if (user.can_upload) {
      document.getElementById('btn-upload-doc').style.display = '';
      document.getElementById('doc-file-input').addEventListener('change', uploadFile);
    }
    // Check if open-in-place is configured on the server
    try {
      const f = await api.get('/api/features');
      openInplace = !!f.open_inplace;
      if (openInplace) {
        document.getElementById('btn-install-handler').style.display = '';
      }
    } catch (_) {}
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
        const isCAD = isCadFile(d.file_type);
        const openBtn = (openInplace && isCAD)
          ? `<button class="btn btn-primary btn-sm" onclick="DocsPanel.openInPlace(${d.id})" title="Open in CAD software from network share">Open</button>`
          : '';
        const isStl = (d.file_type || '').toLowerCase() === 'stl';
        const viewBtn = isStl
          ? `<button class="btn btn-secondary btn-sm" onclick="DocsPanel.viewStl(${d.id}, '${d.filename.replace(/'/g, "\\'")}')" title="View 3D model">👁 View</button>`
          : '';
        html += `<div class="doc-item">
          <div class="doc-icon">${fileIcon(d.file_type)}</div>
          <div class="doc-info">
            <div class="doc-name">${d.filename}</div>
            <div class="doc-meta">${d.uploaded_by_name || ''} · ${formatDate(d.uploaded_at)}${d.description ? ' · ' + d.description : ''}</div>
          </div>
          <div class="doc-actions">
            ${viewBtn}
            ${openBtn}
            <a class="btn btn-secondary btn-sm" href="/api/documents/${d.id}/download" download title="Download copy">⬇</a>
            <button class="btn btn-secondary btn-sm" onclick="DocsPanel.showVersions(${d.id}, '${d.filename}')" title="Version history">🕐</button>
            ${currentUser.can_write ? `<button class="btn btn-danger btn-sm" onclick="DocsPanel.deleteDoc(${d.id})" title="Delete">🗑</button>` : ''}
          </div>
        </div>`;
      });
      html += '</div>';
    });
    container.innerHTML = html;
  }

  // CAD extensions that support open-in-place
  const CAD_EXTS = new Set(['prt','asm','drw','stl','3mf','obj','step','stp','sldprt','sldasm','ipt','iam']);
  function isCadFile(file_type) {
    return CAD_EXTS.has((file_type || '').toLowerCase());
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

  function viewStl(docId, filename) {
    const modalId = `modal-stl-${docId}`;
    const canvasId = `stl-canvas-${docId}`;
    const url = BASE_PATH + `/api/documents/${docId}/download`;

    createModal(modalId, `3D View — ${filename}`,
      `<div id="${canvasId}" style="width:100%;height:480px;background:#1a1a2e;border-radius:4px;position:relative">
         <div id="${canvasId}-loading" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#aaa;font-size:13px">Loading…</div>
       </div>
       <p style="font-size:11px;color:var(--muted);margin-top:6px">Left-drag: rotate &nbsp;·&nbsp; Right-drag: pan &nbsp;·&nbsp; Scroll: zoom</p>`,
      () => closeModal(modalId), 'Close', 'btn-secondary'
    );

    // Give DOM time to render before starting Three.js
    setTimeout(() => {
      const container = document.getElementById(canvasId);
      if (!container || !window.THREE) return;

      const w = container.clientWidth, h = container.clientHeight;
      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(w, h);
      renderer.setPixelRatio(window.devicePixelRatio);
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x1a1a2e);
      scene.add(new THREE.AmbientLight(0xffffff, 0.6));
      const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
      dirLight.position.set(1, 2, 3);
      scene.add(dirLight);

      const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 10000);
      const controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;

      const loader = new THREE.STLLoader();
      loader.load(url, geometry => {
        document.getElementById(`${canvasId}-loading`).style.display = 'none';
        geometry.computeBoundingBox();
        const center = new THREE.Vector3();
        geometry.boundingBox.getCenter(center);
        geometry.translate(-center.x, -center.y, -center.z);

        const size = new THREE.Vector3();
        geometry.boundingBox.getSize(size);
        const maxDim = Math.max(size.x, size.y, size.z);
        camera.position.set(0, 0, maxDim * 2);
        controls.update();

        const material = new THREE.MeshPhongMaterial({ color: 0x1a73e8, specular: 0x444444, shininess: 60 });
        scene.add(new THREE.Mesh(geometry, material));
      }, undefined, () => {
        document.getElementById(`${canvasId}-loading`).textContent = 'Failed to load STL';
      });

      let animId;
      function animate() { animId = requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
      animate();

      // Clean up when modal closes
      const observer = new MutationObserver(() => {
        if (!document.getElementById(modalId)) {
          cancelAnimationFrame(animId);
          renderer.dispose();
          observer.disconnect();
        }
      });
      observer.observe(document.body, { childList: true, subtree: false });
    }, 50);
  }

  async function openInPlace(docId) {
    try {
      const data = await api.get(`/api/documents/${docId}/open`);
      // Fire the plmopen:// URI — the registered handler strips the scheme
      // and passes the bare network path to Windows' start command,
      // which opens it in NX (or whatever app owns the file extension).
      window.location.href = data.uri;
    } catch (e) {
      showToast('Open failed: ' + e.message, 'error');
    }
  }

  return { init, load, deleteDoc, showVersions, restoreVersion, openInPlace, viewStl };
})();

window.DocsPanel = DocsPanel;
