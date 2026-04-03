/**
 * PLM Lite v2.1 — BOM / Relationships panel
 */

const RelPanel = (() => {
  let allItems    = [];
  let currentUser = null;

  async function init(user) {
    currentUser = user;
    document.getElementById('bom-part-search').addEventListener('input', debounce(searchItems, 300));
    document.getElementById('btn-where-used').addEventListener('click', showWhereUsed);
    document.getElementById('btn-add-rel').addEventListener('click', showAddRelModal);

    const data = await api.get('/api/items?per_page=500');
    allItems = data.items || [];
    buildDatalist();
  }

  function buildDatalist() {
    let dl = document.getElementById('bom-items-list');
    if (!dl) {
      dl = document.createElement('datalist');
      dl.id = 'bom-items-list';
      document.body.appendChild(dl);
    }
    dl.innerHTML = allItems.map(p =>
      `<option value="${p.item_id}">${p.item_id} — ${p.name}</option>`
    ).join('');
    document.getElementById('bom-part-search').setAttribute('list', 'bom-items-list');
  }

  async function searchItems() {
    const val  = document.getElementById('bom-part-search').value.trim();
    const item = allItems.find(p => p.item_id === val);
    if (item) await loadTree(item.item_id, item.id);
  }

  async function loadTree(itemId, itemPk) {
    document.getElementById('bom-tree-container').innerHTML = '<div class="spinner"></div>';
    document.getElementById('bom-selected-pn').textContent = '';
    try {
      const tree = await api.get(`/api/items/${itemId}/bom`);
      document.getElementById('bom-selected-pn').textContent = `${tree.item_id} — ${tree.name}`;
      document.getElementById('btn-where-used').dataset.itemId = itemId;
      document.getElementById('bom-tree-container').innerHTML =
        `<div class="bom-tree">${renderTreeNode(tree, true)}</div>`;
    } catch (e) {
      document.getElementById('bom-tree-container').innerHTML =
        `<p style="color:var(--danger)">${e.message}</p>`;
    }
  }

  function renderTreeNode(node, isRoot = false) {
    const chip  = statusChip(node.status);
    const label = `<span class="bom-pn">${node.item_id}</span> — ${node.name} ${chip}`;
    if (!node.children || node.children.length === 0) {
      return `<ul><li style="padding:3px 8px">${label}</li></ul>`;
    }
    const childHtml = node.children.map(c => {
      const qtySpan = c.quantity && c.quantity !== 1
        ? ` <span class="bom-qty">(${c.quantity}×)</span>` : '';
      return `<details>
        <summary>${renderTreeNode(c)}${qtySpan}</summary>
      </details>`;
    }).join('');
    if (isRoot) {
      return `<details open><summary>${label}</summary><ul>${childHtml}</ul></details>`;
    }
    return `<ul>${childHtml}</ul>`;
  }

  async function showWhereUsed() {
    const itemId = document.getElementById('btn-where-used').dataset.itemId;
    if (!itemId) return showToast('Select an item first', 'error');
    try {
      const parents = await api.get(`/api/items/${itemId}/where-used`);
      const pn = document.getElementById('bom-selected-pn').textContent.split(' — ')[0];
      let html = parents.length
        ? parents.map(p =>
            `<tr>
              <td><strong>${p.item_id}</strong></td>
              <td>${p.name}</td>
              <td>${statusChip(p.status)}</td>
            </tr>`).join('')
        : '<tr><td colspan="3" style="color:var(--muted);text-align:center;padding:20px">Not used in any assembly</td></tr>';
      createModal('modal-where-used', `Where Used: ${pn}`,
        `<table class="data-table"><thead><tr><th>Item ID</th><th>Name</th><th>Status</th></tr></thead>
         <tbody>${html}</tbody></table>`,
        () => closeModal('modal-where-used'), 'Close', 'btn-secondary');
    } catch (e) { showToast(e.message, 'error'); }
  }

  function showAddRelModal() {
    if (!allItems.length) return showToast('No items found — create items first', 'error');
    const opts = allItems.map(p =>
      `<option value="${p.id}">${p.item_id} — ${p.name}</option>`).join('');
    createModal('modal-add-rel', 'Add BOM Relationship', `
      <div class="form-group"><label>Parent Item *</label><select id="rel-parent">${opts}</select></div>
      <div class="form-group"><label>Child Item *</label><select id="rel-child">${opts}</select></div>
      <div class="form-group"><label>Quantity</label>
        <input id="rel-qty" type="number" value="1" min="1" step="1">
      </div>`, addRelationship);
  }

  async function addRelationship() {
    const body = {
      parent_item_id: +document.getElementById('rel-parent').value,
      child_item_id:  +document.getElementById('rel-child').value,
      quantity:       +document.getElementById('rel-qty').value || 1,
    };
    if (body.parent_item_id === body.child_item_id)
      return showToast('Parent and child cannot be the same', 'error');
    try {
      await api.post('/api/relationships', body);
      closeModal('modal-add-rel');
      showToast('Relationship added', 'success');
      // Refresh local list
      const data = await api.get('/api/items?per_page=500');
      allItems = data.items || [];
      buildDatalist();
    } catch (e) { showToast(e.message, 'error'); }
  }

  function refreshItems(items) {
    allItems = items;
    buildDatalist();
  }

  return { init, loadTree, showWhereUsed, showAddRelModal, refreshItems };
})();

window.RelPanel = RelPanel;
