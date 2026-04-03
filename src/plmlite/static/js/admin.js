/**
 * PLM Lite v2.1 — Admin panel (users + audit log)
 *
 * Simplified vs v1.0: no roles table, no role abilities matrix.
 * Roles are the three levels defined in schema: admin / user / readonly.
 */

const AdminPanel = (() => {
  let currentUser = null;

  async function init(user) {
    currentUser = user;
    document.getElementById('btn-create-user').addEventListener('click', showCreateUserModal);
    // Hide unused role button
    const roleBtn = document.getElementById('btn-create-role');
    if (roleBtn) roleBtn.style.display = 'none';

    await Promise.all([loadUsers(), loadAudit()]);
  }

  // ── Users ─────────────────────────────────────────────────────────────────
  async function loadUsers() {
    const tbody = document.getElementById('users-tbody');
    try {
      const users = await api.get('/api/users');
      if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px">No users</td></tr>';
        return;
      }
      tbody.innerHTML = users.map(u => `
        <tr>
          <td><strong>${u.username}</strong></td>
          <td>
            <select onchange="AdminPanel.changeRole(${u.id}, this.value)">
              ${['admin','user','readonly'].map(r =>
                `<option value="${r}" ${u.role === r ? 'selected' : ''}>${r}</option>`
              ).join('')}
            </select>
          </td>
          <td style="font-size:11px;color:var(--muted)">${formatDate(u.created_at)}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" style="color:var(--danger)">${e.message}</td></tr>`;
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
      <div class="form-group"><label>Username *</label><input id="cu-username" placeholder="Windows username"></div>
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
      role:     document.getElementById('cu-role').value,
    };
    if (!body.username) return showToast('Username is required', 'error');
    try {
      await api.post('/api/users', body);
      closeModal('modal-create-user');
      showToast(`User ${body.username} added`, 'success');
      await loadUsers();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ── Audit log ─────────────────────────────────────────────────────────────
  async function loadAudit() {
    const tbody = document.getElementById('audit-tbody');
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

  return { init, loadUsers, loadAudit, changeRole, createUser };
})();

window.AdminPanel = AdminPanel;
