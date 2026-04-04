/**
 * PLM Lite v2.2 — Admin panel (users + roles + audit log + settings)
 */

const AdminPanel = (() => {
  let currentUser = null;

  const ALL_PERMS = [
    "parts.create","parts.edit","parts.delete",
    "datasets.upload","datasets.checkout","datasets.checkin_own",
    "datasets.checkin_any","revisions.create","revisions.lock",
    "revisions.release","bom.edit","users.manage",
  ];

  async function init(user) {
    currentUser = user;
    _setupTabs();
    document.getElementById('btn-create-user').addEventListener('click', showCreateUserModal);

    const roleBtn = document.getElementById('btn-create-role');
    if (roleBtn) {
      roleBtn.style.display = 'none';
      roleBtn.addEventListener('click', showCreateRoleModal);
    }

    await Promise.all([loadUsers(), loadAudit()]);
  }

  // ── Tab setup ─────────────────────────────────────────────────────────────
  function _setupTabs() {
    const tabBar = document.getElementById('admin-tabs');
    if (!tabBar) return;

    // Add Roles and Settings tabs if not present
    if (!tabBar.querySelector('[data-tab="roles"]')) {
      tabBar.innerHTML += `
        <div class="inner-tab" data-tab="roles"  style="border-top:none">Roles</div>
        <div class="inner-tab" data-tab="settings" style="border-top:none">Settings</div>`;
    }

    // Add panels to DOM if not present
    const mainContent = document.getElementById('panel-admin');
    if (mainContent && !document.getElementById('admin-panel-roles')) {
      mainContent.insertAdjacentHTML('beforeend', `
        <div id="admin-panel-roles" class="admin-tab-panel" style="flex:1;overflow-y:auto;display:none;padding:12px 16px"></div>
        <div id="admin-panel-settings" class="admin-tab-panel" style="flex:1;overflow-y:auto;display:none;padding:16px 20px;max-width:480px"></div>
      `);
    }

    tabBar.addEventListener('click', e => {
      const tab = e.target.closest('[data-tab]');
      if (!tab) return;
      tabBar.querySelectorAll('.inner-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.admin-tab-panel').forEach(p => { p.style.display = 'none'; p.classList.remove('active'); });
      const panel = document.getElementById(`admin-panel-${tab.dataset.tab}`);
      if (panel) { panel.style.display = ''; panel.classList.add('active'); }

      const roleBtn = document.getElementById('btn-create-role');
      const createBtn = document.getElementById('btn-create-user');
      if (tab.dataset.tab === 'roles') {
        if (roleBtn) roleBtn.style.display = '';
        if (createBtn) createBtn.style.display = 'none';
        loadRoles();
      } else if (tab.dataset.tab === 'settings') {
        if (roleBtn) roleBtn.style.display = 'none';
        if (createBtn) createBtn.style.display = 'none';
        renderSettings();
      } else if (tab.dataset.tab === 'users') {
        if (roleBtn) roleBtn.style.display = 'none';
        if (createBtn) createBtn.style.display = '';
        loadUsers();
      } else {
        if (roleBtn) roleBtn.style.display = 'none';
        if (createBtn) createBtn.style.display = 'none';
        if (tab.dataset.tab === 'audit') loadAudit();
      }
    });

    // Remove the old static listener added in app.html by replacing the element
    // (app.html sets up its own listener which handles audit/users; ours covers roles/settings)
  }

  // ── Users ─────────────────────────────────────────────────────────────────
  async function loadUsers() {
    const tbody = document.getElementById('users-tbody');
    if (!tbody) return;
    try {
      const users = await api.get('/api/users');
      const isAdmin = currentUser && currentUser.permissions && currentUser.permissions.includes('users.manage');
      if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px">No users</td></tr>';
        return;
      }
      tbody.innerHTML = users.map(u => `
        <tr>
          <td><strong>${escapeHtml(u.username)}</strong></td>
          <td>
            ${isAdmin ? `
              <select onchange="AdminPanel.changeRole(${u.id}, this.value)">
                ${['admin','user','readonly'].map(r =>
                  `<option value="${r}" ${u.role === r ? 'selected' : ''}>${r}</option>`
                ).join('')}
              </select>` : `<span>${u.role}</span>`}
          </td>
          <td style="font-size:11px;color:var(--muted)">${formatDate(u.created_at)}</td>
          <td style="font-size:11px;color:var(--muted)">${u.last_seen ? formatDate(u.last_seen) : '—'}</td>
          <td style="display:flex;gap:4px;flex-wrap:wrap">
            ${isAdmin ? `
              <button class="btn btn-secondary btn-sm" onclick="AdminPanel.showSetPasswordModal(${u.id}, '${escapeHtml(u.username)}')">🔑 Set Password</button>
              <button class="btn btn-danger btn-sm" onclick="AdminPanel.forceCheckin(${u.id}, '${escapeHtml(u.username)}')">Force Check-In</button>
            ` : ''}
          </td>
        </tr>`).join('');

      // Update thead
      const thead = tbody.closest('table').querySelector('thead tr');
      if (thead && thead.children.length < 5) {
        thead.innerHTML = '<th>Username</th><th>Role</th><th>Created</th><th>Last Seen</th><th>Actions</th>';
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">${e.message}</td></tr>`;
    }
  }

  async function changeRole(userId, role) {
    try {
      await api.put(`/api/users/${userId}`, { role });
      showToast('Role updated', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  function showCreateUserModal() {
    createModal('modal-create-user', 'Add User', `
      <div class="form-group"><label>Username *</label><input id="cu-username" placeholder="e.g. alice"></div>
      <div class="form-group"><label>Password *</label><input id="cu-password" type="password" placeholder="Initial password"></div>
      <div class="form-group"><label>Role</label>
        <select id="cu-role">
          <option value="user">user</option>
          <option value="admin">admin</option>
          <option value="readonly">readonly</option>
        </select>
      </div>`, createUser);
  }

  async function createUser() {
    const body = {
      username: document.getElementById('cu-username').value.trim(),
      password: document.getElementById('cu-password').value,
      role:     document.getElementById('cu-role').value,
    };
    if (!body.username) return showToast('Username is required', 'error');
    if (!body.password) return showToast('Password is required', 'error');
    try {
      await api.post('/api/users', body);
      closeModal('modal-create-user');
      showToast(`User ${body.username} created`, 'success');
      await loadUsers();
    } catch (e) { showToast(e.message, 'error'); }
  }

  function showSetPasswordModal(userId, username) {
    createModal('modal-set-pw', `Set Password — ${username}`, `
      <div class="form-group"><label>New Password *</label><input id="sp-password" type="password" placeholder="New password"></div>
      <div class="form-group"><label>Confirm Password *</label><input id="sp-confirm" type="password" placeholder="Confirm password"></div>`,
      () => setUserPassword(userId));
  }

  async function setUserPassword(userId) {
    const pw  = document.getElementById('sp-password').value;
    const cfm = document.getElementById('sp-confirm').value;
    if (!pw) return showToast('Password is required', 'error');
    if (pw !== cfm) return showToast('Passwords do not match', 'error');
    try {
      await api.post(`/api/users/${userId}/password`, { password: pw });
      closeModal('modal-set-pw');
      showToast('Password set', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function forceCheckin(userId, username) {
    if (!confirm(`Force check-in ALL files checked out by ${username}?`)) return;
    try {
      const r = await api.post(`/api/users/${userId}/force-checkin`, {});
      showToast(r.message, 'success');
      await loadUsers();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Roles ─────────────────────────────────────────────────────────────────
  async function loadRoles() {
    const panel = document.getElementById('admin-panel-roles');
    if (!panel) return;
    panel.innerHTML = '<div class="spinner"></div>';
    try {
      const roles = await api.get('/api/roles');
      const isAdmin = currentUser && currentUser.permissions && currentUser.permissions.includes('users.manage');

      let html = `<table class="data-table"><thead><tr><th>Permission</th>`;
      roles.forEach(r => { html += `<th style="text-align:center">${escapeHtml(r.name)}</th>`; });
      html += `</tr></thead><tbody>`;

      ALL_PERMS.forEach(perm => {
        html += `<tr><td><code style="font-size:11px">${perm}</code></td>`;
        roles.forEach(r => {
          const checked = r.permissions.includes(perm);
          if (r.builtin) {
            html += `<td style="text-align:center"><input type="checkbox" ${checked ? 'checked' : ''} disabled title="Built-in role — read only"></td>`;
          } else if (isAdmin) {
            html += `<td style="text-align:center"><input type="checkbox" class="ability-toggle" ${checked ? 'checked' : ''}
              onchange="AdminPanel.toggleRolePerm('${escapeHtml(r.name)}', '${perm}', this.checked)"></td>`;
          } else {
            html += `<td style="text-align:center"><input type="checkbox" ${checked ? 'checked' : ''} disabled></td>`;
          }
        });
        html += `</tr>`;
      });
      html += `</tbody></table>`;
      panel.innerHTML = html;
    } catch (e) {
      panel.innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
    }
  }

  async function toggleRolePerm(roleName, perm, enabled) {
    try {
      const role = await api.get('/api/roles').then(rs => rs.find(r => r.name === roleName));
      if (!role) return;
      const perms = role.permissions.filter(p => p !== perm);
      if (enabled) perms.push(perm);
      await api.put(`/api/roles/${encodeURIComponent(roleName)}`, { permissions: perms });
    } catch (e) { showToast(e.message, 'error'); loadRoles(); }
  }

  function showCreateRoleModal() {
    createModal('modal-create-role', 'New Custom Role', `
      <div class="form-group"><label>Role Name *</label><input id="cr-name" placeholder="e.g. engineer, viewer"></div>`,
      createRole);
  }

  async function createRole() {
    const name = document.getElementById('cr-name').value.trim();
    if (!name) return showToast('Role name is required', 'error');
    try {
      await api.post('/api/roles', { name });
      closeModal('modal-create-role');
      showToast(`Role "${name}" created`, 'success');
      loadRoles();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Settings (change own password) ────────────────────────────────────────
  function renderSettings() {
    const panel = document.getElementById('admin-panel-settings');
    if (!panel) return;
    panel.innerHTML = `
      <h3 style="margin-bottom:12px;font-size:13px;color:var(--tc-navy-dark)">Change My Password</h3>
      <div class="form-grid one-col" style="max-width:340px">
        <div class="form-group"><label>Current Password</label><input id="chpw-current" type="password"></div>
        <div class="form-group"><label>New Password</label><input id="chpw-new" type="password"></div>
        <div class="form-group"><label>Confirm New Password</label><input id="chpw-confirm" type="password"></div>
        <div><button class="btn btn-primary" onclick="AdminPanel.changeOwnPassword()">💾 Update Password</button></div>
      </div>`;
  }

  async function changeOwnPassword() {
    const current = document.getElementById('chpw-current').value;
    const newPw   = document.getElementById('chpw-new').value;
    const confirm = document.getElementById('chpw-confirm').value;
    if (!current || !newPw) return showToast('All fields are required', 'error');
    if (newPw !== confirm) return showToast('New passwords do not match', 'error');
    try {
      await api.post('/api/me/password', { current_password: current, new_password: newPw });
      showToast('Password updated', 'success');
      document.getElementById('chpw-current').value = '';
      document.getElementById('chpw-new').value = '';
      document.getElementById('chpw-confirm').value = '';
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Audit log ─────────────────────────────────────────────────────────────
  async function loadAudit() {
    const tbody = document.getElementById('audit-tbody');
    if (!tbody) return;
    try {
      const entries = await api.get('/api/audit');
      if (!entries.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px">No audit entries</td></tr>';
        return;
      }
      tbody.innerHTML = entries.slice(0, 500).map(e => `
        <tr>
          <td style="font-size:11px;color:var(--muted);white-space:nowrap">${formatDate(e.performed_at)}</td>
          <td>${e.who || '—'}</td>
          <td><code style="font-size:11px">${e.action}</code></td>
          <td>${e.entity_type} ${e.entity_id || ''}</td>
          <td style="font-size:11px;color:var(--muted);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.detail || ''}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">${e.message}</td></tr>`;
    }
  }

  return {
    init, loadUsers, loadAudit, changeRole, createUser,
    showSetPasswordModal, setUserPassword, forceCheckin,
    loadRoles, toggleRolePerm, showCreateRoleModal, createRole,
    changeOwnPassword,
  };
})();

window.AdminPanel = AdminPanel;
