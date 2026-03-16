/**
 * UserManagement — list, invite, change role, and remove users in the tenant.
 *
 * Admin controls (invite, role change, remove) are shown only to Tenant Admins.
 * Ref: SPEC.md § Feature: Tenant User & Role Management
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import { useAuth } from '../../context/AuthContext';
import { useUsers, useInviteUser, useUpdateUserRole, useRemoveUser } from '../../hooks/useUsers';
import styles from '../admin/AdminPage.module.css';

const ROLE_LABELS = { admin: 'Admin', operator: 'Operator', viewer: 'View-Only' };
const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'operator', label: 'Operator' },
  { value: 'viewer', label: 'View-Only' },
];

function UserManagement() {
  const { user: me } = useAuth();
  const isAdmin = me?.tenant_role === 'admin';

  const { data: users = [], isLoading, isError } = useUsers();
  const inviteUser = useInviteUser();
  const removeUser = useRemoveUser();

  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('operator');
  const [inviteError, setInviteError] = useState('');
  const [inviteSuccess, setInviteSuccess] = useState('');

  const handleInvite = async (e) => {
    e.preventDefault();
    setInviteError('');
    setInviteSuccess('');
    if (!inviteEmail.trim()) { setInviteError('Email is required.'); return; }
    try {
      await inviteUser.mutateAsync({ email: inviteEmail, role: inviteRole });
      setInviteSuccess(`Invite sent to ${inviteEmail}.`);
      setInviteEmail('');
    } catch (err) {
      setInviteError(
        err.response?.data?.error?.message || 'Failed to send invite.'
      );
    }
  };

  const handleRemove = async (tenantUserId, email) => {
    if (!window.confirm(`Remove ${email} from the organisation?`)) return;
    try {
      await removeUser.mutateAsync(tenantUserId);
    } catch (err) {
      alert(err.response?.data?.error?.message || 'Failed to remove user.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Users</h1>
      </div>

      {/* Invite form — Tenant Admin only */}
      {isAdmin && (
        <section className={styles.section}>
          <h2>Invite a user</h2>
          <form onSubmit={handleInvite} className={styles.form} noValidate>
            <div className={styles.inlineFields}>
              <div className={styles.field}>
                <label className={styles.label}>Email address</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  className={styles.input}
                  placeholder="user@example.com"
                  disabled={inviteUser.isPending}
                />
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className={styles.input}
                  disabled={inviteUser.isPending}
                >
                  {ROLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                className={styles.primaryButton}
                disabled={inviteUser.isPending}
                style={{ alignSelf: 'flex-end' }}
              >
                {inviteUser.isPending ? 'Sending…' : 'Send invite'}
              </button>
            </div>
            {inviteError && <p className={styles.error}>{inviteError}</p>}
            {inviteSuccess && <p className={styles.success}>{inviteSuccess}</p>}
          </form>
        </section>
      )}

      {/* User list */}
      <section className={styles.section}>
        <h2>Team members</h2>
        {isLoading && <p>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load users.</p>}
        {!isLoading && !isError && users.length === 0 && (
          <p>No users yet.</p>
        )}
        {!isLoading && !isError && users.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <UserRow
                  key={u.id}
                  tenantUser={u}
                  isMe={u.email === me?.email}
                  isAdmin={isAdmin}
                  onRemove={handleRemove}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function UserRow({ tenantUser, isMe, isAdmin, onRemove }) {
  const updateRole = useUpdateUserRole(tenantUser.id);
  const [roleError, setRoleError] = useState('');

  const handleRoleChange = async (newRole) => {
    setRoleError('');
    try {
      await updateRole.mutateAsync({ role: newRole });
    } catch (err) {
      setRoleError(err.response?.data?.error?.message || 'Failed to update role.');
    }
  };

  const fullName = [tenantUser.first_name, tenantUser.last_name].filter(Boolean).join(' ') || '—';

  return (
    <tr>
      <td>{fullName}{isMe && <span className={styles.badgeActive}> (you)</span>}</td>
      <td>{tenantUser.email}</td>
      <td>
        {isAdmin && !isMe ? (
          <div>
            <select
              value={tenantUser.role}
              onChange={(e) => handleRoleChange(e.target.value)}
              className={styles.input}
              disabled={updateRole.isPending}
              style={{ width: 'auto' }}
            >
              {ROLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            {roleError && <div className={styles.error}>{roleError}</div>}
          </div>
        ) : (
          <span>{ROLE_LABELS[tenantUser.role] || tenantUser.role}</span>
        )}
      </td>
      {isAdmin && (
        <td>
          {!isMe && (
            <button
              className={styles.dangerButton}
              onClick={() => onRemove(tenantUser.id, tenantUser.email)}
            >
              Remove
            </button>
          )}
        </td>
      )}
    </tr>
  );
}

UserRow.propTypes = {
  tenantUser: PropTypes.shape({
    id: PropTypes.number.isRequired,
    email: PropTypes.string.isRequired,
    first_name: PropTypes.string,
    last_name: PropTypes.string,
    role: PropTypes.string.isRequired,
  }).isRequired,
  isMe: PropTypes.bool.isRequired,
  isAdmin: PropTypes.bool.isRequired,
  onRemove: PropTypes.func.isRequired,
};

export default UserManagement;
