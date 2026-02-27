/**
 * PLM Lite V1.0 — Admin panel (users, roles, audit)
 */

const AdminPanel = (() => {
  let roles = [];
  let currentUser = null;

  async function init(user) {
    currentUser = user;
    if (!user.can_admin) return;

    document.getElementById('admin-tabs').addEventListener('click', e => {
      const tab = e.target.closest('[data-tab]');
      if (!tab) return;
      document.querySelectorAll('#admin-tabs [data-tab]').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.admin-tab-panel').forEach(p => p.classList.remove('active'));
      document.getElementById(`admin-panel-${tab.dataset.tab}`).classList.add('active');
    });

    document.getElementById('btn-create-user').addEventListener('click', showCreateUserModal);
    document.getElementById('btn-create-role').addEventListener('click', showCreateRoleModal);

    roles = await api.get('/api/admin/roles');
    await Promise.all([loadUsers(), loadRoles(), loadAudit()]);
  }

  // ── Users ─────────────────────────────────────────────────────────────────
  async function loadUsers() {
    const tbody = document.getElementById('users-tbody');
    try {
      const users = await api.get('/api/users');
      if (!users.length) { tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px">No users</td></tr>'; return; }
      tbody.innerHTML = users.map(u => `
        <tr>
          <td><strong>${u.username}</strong></td>
          <td>${u.email || '—'}</td>
          <td>
            <select onchange="AdminPanel.changeRole(${u.id}, this.value)">
              ${roles.map(r => `<option value="${r.id}" ${r.id === u.role_id ? 'selected' : ''}>${r.name}</option>`).join('')}
            </select>
          </td>
          <td><input type="checkbox" class="ability-toggle" ${u.is_active ? 'checked' : ''} onchange="AdminPanel.toggleActive(${u.id}, this.checked)"></td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="AdminPanel.resetPassword(${u.id}, '${u.username}')">Reset PW</button>
          </td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">${e.message}</td></tr>`;
    }
  }

  async function changeRole(userId, roleId) {
    try {
      await api.put(`/api/users/${userId}`, { role_id: +roleId, is_active: 1 });
      showToast('Role updated', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function toggleActive(userId, isActive) {
    try {
      await api.put(`/api/users/${userId}`, { is_active: isActive ? 1 : 0 });
      showToast(isActive ? 'User enabled' : 'User disabled', 'info');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function resetPassword(userId, username) {
    const pw = prompt(`New password for ${username}:`);
    if (!pw) return;
    try {
      await api.post(`/api/users/${userId}/reset-password`, { new_password: pw });
      showToast('Password reset — user must change on login', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  function showCreateUserModal() {
    createModal('modal-create-user', 'Create User', `
      <div class="form-group"><label>Username *</label><input id="cu-username"></div>
      <div class="form-group"><label>Password *</label><input id="cu-password" type="password"></div>
      <div class="form-group"><label>Email</label><input id="cu-email" type="email"></div>
      <div class="form-group"><label>Role</label>
        <select id="cu-role">${roles.map(r => `<option value="${r.id}">${r.name}</option>`).join('')}</select>
      </div>`, createUser);
  }

  async function createUser() {
    const body = {
      username: document.getElementById('cu-username').value.trim(),
      password: document.getElementById('cu-password').value,
      email: document.getElementById('cu-email').value.trim() || null,
      role_id: +document.getElementById('cu-role').value,
    };
    if (!body.username || !body.password) return showToast('Username and password required', 'error');
    try {
      await api.post('/api/users', body);
      closeModal('modal-create-user');
      showToast(`User ${body.username} created`, 'success');
      await loadUsers();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Roles ─────────────────────────────────────────────────────────────────
  async function loadRoles() {
    const container = document.getElementById('roles-container');
    const abilities = ['release', 'view', 'write', 'upload', 'checkout', 'admin'];
    let html = `<table class="data-table">
      <thead><tr>
        <th>Role Name</th>
        ${abilities.map(a => `<th style="text-align:center">${a.charAt(0).toUpperCase()+a.slice(1)}</th>`).join('')}
        <th></th>
      </tr></thead><tbody>`;
    roles.forEach(r => {
      html += `<tr>
        <td><strong>${r.name}</strong></td>
        ${abilities.map(a => `<td style="text-align:center"><input type="checkbox" class="ability-toggle" ${r[`can_${a}`] ? 'checked' : ''} onchange="AdminPanel.updateRoleAbility(${r.id}, '${a}', this.checked)"></td>`).join('')}
        <td>${r.name !== 'Admin' ? `<button class="btn btn-danger btn-sm" onclick="AdminPanel.deleteRole(${r.id}, '${r.name}')">Delete</button>` : ''}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  async function updateRoleAbility(roleId, ability, value) {
    const role = roles.find(r => r.id === roleId);
    if (!role) return;
    const updated = { ...role, [`can_${ability}`]: value ? 1 : 0 };
    try {
      await api.put(`/api/admin/roles/${roleId}`, {
        name: role.name,
        can_release: updated.can_release, can_view: updated.can_view,
        can_write: updated.can_write, can_upload: updated.can_upload,
        can_checkout: updated.can_checkout, can_admin: updated.can_admin,
      });
      role[`can_${ability}`] = value ? 1 : 0;
      showToast('Role updated', 'success');
    } catch (e) { showToast(e.message, 'error'); loadRoles(); }
  }

  async function deleteRole(roleId, name) {
    if (!confirm(`Delete role "${name}"?`)) return;
    try {
      await api.delete(`/api/admin/roles/${roleId}`);
      roles = await api.get('/api/admin/roles');
      showToast('Role deleted', 'info');
      await loadRoles();
    } catch (e) { showToast(e.message, 'error'); }
  }

  function showCreateRoleModal() {
    createModal('modal-create-role', 'Create Role', `
      <div class="form-group"><label>Role Name *</label><input id="cr-name"></div>
      <p style="font-size:13px;color:var(--muted)">New roles default to all abilities enabled. Adjust after creation.</p>
    `, createRole);
  }

  async function createRole() {
    const name = document.getElementById('cr-name').value.trim();
    if (!name) return showToast('Role name required', 'error');
    try {
      await api.post('/api/admin/roles', { name, can_release:1, can_view:1, can_write:1, can_upload:1, can_checkout:1, can_admin:0 });
      closeModal('modal-create-role');
      roles = await api.get('/api/admin/roles');
      showToast(`Role "${name}" created`, 'success');
      await loadRoles();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Audit log ─────────────────────────────────────────────────────────────
  async function loadAudit() {
    const tbody = document.getElementById('audit-tbody');
    try {
      const data = await api.get('/api/admin/audit');
      if (!data.items.length) { tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px">No audit entries</td></tr>'; return; }
      tbody.innerHTML = data.items.map(e => `
        <tr>
          <td style="font-size:12px;color:var(--muted)">${formatDate(e.timestamp)}</td>
          <td>${e.username || '—'}</td>
          <td><code style="font-size:12px">${e.action}</code></td>
          <td>${e.entity_type} #${e.entity_id || '—'}</td>
          <td style="font-size:11px;color:var(--muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.detail_json || ''}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">${e.message}</td></tr>`;
    }
  }

  return { init, loadUsers, loadRoles, loadAudit, changeRole, toggleActive, resetPassword,
           createUser, updateRoleAbility, deleteRole, createRole };
})();

window.AdminPanel = AdminPanel;
