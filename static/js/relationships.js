/**
 * PLM Lite V1.0 — BOM / Relationships panel
 */

const RelPanel = (() => {
  let allParts = [];
  let currentUser = null;

  async function init(user) {
    currentUser = user;
    document.getElementById('bom-part-search').addEventListener('input', debounce(searchParts, 300));
    document.getElementById('btn-where-used').addEventListener('click', showWhereUsed);
    document.getElementById('btn-export-bom').addEventListener('click', exportBom);
    document.getElementById('btn-add-rel').addEventListener('click', showAddRelModal);

    // Load parts list for dropdowns
    const data = await api.get('/api/parts?per_page=200');
    allParts = data.items || [];
    renderPartsDropdown();
  }

  function renderPartsDropdown() {
    const sel = document.getElementById('bom-part-search');
    // Implemented as text input with datalist
    let dl = document.getElementById('bom-parts-list');
    if (!dl) { dl = document.createElement('datalist'); dl.id = 'bom-parts-list'; document.body.appendChild(dl); }
    dl.innerHTML = allParts.map(p => `<option value="${p.part_number}" data-id="${p.id}">${p.part_number} — ${p.part_name}</option>`).join('');
    sel.setAttribute('list', 'bom-parts-list');
  }

  async function searchParts() {
    const val = document.getElementById('bom-part-search').value.trim();
    const part = allParts.find(p => p.part_number === val);
    if (part) {
      await loadTree(part.id);
    }
  }

  async function loadTree(partId) {
    document.getElementById('bom-tree-container').innerHTML = '<div class="spinner"></div>';
    document.getElementById('bom-selected-pn').textContent = '';
    try {
      const tree = await api.get(`/api/relationships/tree/${partId}`);
      document.getElementById('bom-selected-pn').textContent = `${tree.part_number} — ${tree.part_name}`;
      document.getElementById('btn-where-used').dataset.partId = partId;
      document.getElementById('btn-export-bom').dataset.partId = partId;
      document.getElementById('bom-tree-container').innerHTML = renderTreeNode(tree, true);
    } catch (e) {
      document.getElementById('bom-tree-container').innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
    }
  }

  function renderTreeNode(node, isRoot = false) {
    const chip = statusChip(node.release_status);
    const label = `<span class="bom-pn">${node.part_number}</span> — ${node.part_name} ${chip}`;
    if (!node.children || node.children.length === 0) {
      return `<ul><li style="padding:3px 8px">${label}</li></ul>`;
    }
    const children = node.children.map(c => `
      <details>
        <summary>${label} <span class="bom-qty">(${c.quantity || 1}x)</span></summary>
        ${renderTreeNode(c)}
      </details>`).join('');
    if (isRoot) {
      return `<div class="bom-tree"><details open><summary>${label}</summary><ul>${children}</ul></details></div>`;
    }
    return `<ul>${children}</ul>`;
  }

  async function showWhereUsed() {
    const partId = document.getElementById('btn-where-used').dataset.partId;
    if (!partId) return showToast('Select a part first', 'error');
    try {
      const parents = await api.get(`/api/parts/${partId}/where-used`);
      const pn = document.getElementById('bom-selected-pn').textContent.split(' — ')[0];
      let html = parents.length
        ? parents.map(p => `<tr><td><strong>${p.part_number}</strong></td><td>${p.part_name}</td><td>${p.part_revision}</td><td>${statusChip(p.release_status)}</td></tr>`).join('')
        : '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px">Not used in any assembly</td></tr>';
      createModal('modal-where-used', `Where Used: ${pn}`, `
        <table class="data-table"><thead><tr><th>Part #</th><th>Name</th><th>Rev</th><th>Status</th></tr></thead>
        <tbody>${html}</tbody></table>`, () => closeModal('modal-where-used'), 'Close', 'btn-secondary');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function exportBom() {
    const partId = document.getElementById('btn-export-bom').dataset.partId;
    if (!partId) return showToast('Select a part first', 'error');
    window.location.href = `/api/parts/${partId}/bom/export`;
  }

  function showAddRelModal() {
    const opts = allParts.map(p => `<option value="${p.id}">${p.part_number} — ${p.part_name}</option>`).join('');
    createModal('modal-add-rel', 'Add Relationship', `
      <div class="form-group"><label>Parent Part *</label><select id="rel-parent">${opts}</select></div>
      <div class="form-group"><label>Child Part *</label><select id="rel-child">${opts}</select></div>
      <div class="form-grid">
        <div class="form-group"><label>Quantity</label><input id="rel-qty" type="number" value="1" min="0.001" step="0.001"></div>
        <div class="form-group"><label>Type</label>
          <select id="rel-type">
            <option value="assembly">Assembly</option>
            <option value="reference">Reference</option>
            <option value="drawing">Drawing</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>Notes</label><input id="rel-notes" placeholder="Optional"></div>
    `, addRelationship);
  }

  async function addRelationship() {
    const body = {
      parent_part_id: +document.getElementById('rel-parent').value,
      child_part_id: +document.getElementById('rel-child').value,
      quantity: +document.getElementById('rel-qty').value || 1,
      relationship_type: document.getElementById('rel-type').value,
      notes: document.getElementById('rel-notes').value.trim(),
    };
    if (body.parent_part_id === body.child_part_id) return showToast('Parent and child cannot be the same', 'error');
    try {
      await api.post('/api/relationships', body);
      closeModal('modal-add-rel');
      showToast('Relationship added', 'success');
      // Refresh allParts dropdowns
      const data = await api.get('/api/parts?per_page=200');
      allParts = data.items || [];
    } catch (e) { showToast(e.message, 'error'); }
  }

  return { init, loadTree, showWhereUsed, exportBom, showAddRelModal };
})();

window.RelPanel = RelPanel;
