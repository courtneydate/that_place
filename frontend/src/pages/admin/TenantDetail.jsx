/**
 * Tenant detail / edit page — That Place Admin.
 * Allows editing name/timezone, deactivating the tenant, and sending an invite.
 */
import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useTenant, useUpdateTenant, useSendInvite } from '../../hooks/useTenants';
import styles from './AdminPage.module.css';

const TIMEZONES = [
  'Australia/Sydney', 'Australia/Melbourne', 'Australia/Brisbane',
  'Australia/Adelaide', 'Australia/Perth', 'Australia/Darwin',
  'Australia/Hobart', 'Pacific/Auckland', 'UTC',
];

function TenantDetail() {
  const { id } = useParams();
  const { data: tenant, isLoading, isError } = useTenant(id);
  const { mutateAsync: updateTenant, isPending: isSaving } = useUpdateTenant(id);
  const { mutateAsync: sendInvite, isPending: isInviting } = useSendInvite(id);

  const [name, setName] = useState('');
  const [timezone, setTimezone] = useState('Australia/Sydney');
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('admin');
  const [inviteError, setInviteError] = useState('');
  const [inviteSuccess, setInviteSuccess] = useState('');

  useEffect(() => {
    if (tenant) {
      setName(tenant.name);
      setTimezone(tenant.timezone);
    }
  }, [tenant]);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaveError(''); setSaveSuccess(false);
    try {
      await updateTenant({ name, timezone });
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(err.response?.data?.error?.message || 'Failed to save changes.');
    }
  };

  const handleDeactivate = async () => {
    if (!window.confirm('Deactivate this tenant? Their users will not be able to log in.')) return;
    try {
      await updateTenant({ is_active: false });
    } catch (err) {
      setSaveError(err.response?.data?.error?.message || 'Failed to deactivate tenant.');
    }
  };

  const handleReactivate = async () => {
    try {
      await updateTenant({ is_active: true });
    } catch (err) {
      setSaveError(err.response?.data?.error?.message || 'Failed to reactivate tenant.');
    }
  };

  const handleInvite = async (e) => {
    e.preventDefault();
    setInviteError(''); setInviteSuccess('');
    if (!inviteEmail.trim()) { setInviteError('Email is required.'); return; }
    try {
      const result = await sendInvite({ email: inviteEmail, role: inviteRole });
      setInviteSuccess(result.detail);
      setInviteEmail('');
    } catch (err) {
      setInviteError(err.response?.data?.error?.message || 'Failed to send invite.');
    }
  };

  if (isLoading) return <p className={styles.loading}>Loading…</p>;
  if (isError) return <p className={styles.error}>Tenant not found.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>{tenant.name}</h1>
        <span className={tenant.is_active ? styles.badgeActive : styles.badgeInactive}>
          {tenant.is_active ? 'Active' : 'Inactive'}
        </span>
      </div>

      {/* Edit form */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Organisation details</h2>
        <form onSubmit={handleSave} className={styles.form}>
          <div className={styles.field}>
            <label className={styles.label}>Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={styles.input} disabled={isSaving} />
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Timezone</label>
            <select value={timezone} onChange={(e) => setTimezone(e.target.value)} className={styles.input} disabled={isSaving}>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </div>
          {saveError && <p className={styles.error}>{saveError}</p>}
          {saveSuccess && <p className={styles.success}>Changes saved.</p>}
          <div className={styles.actions}>
            <button type="submit" className={styles.primaryButton} disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save changes'}
            </button>
            {tenant.is_active
              ? <button type="button" onClick={handleDeactivate} className={styles.dangerButton} disabled={isSaving}>Deactivate tenant</button>
              : <button type="button" onClick={handleReactivate} className={styles.secondaryButton} disabled={isSaving}>Reactivate tenant</button>
            }
          </div>
        </form>
      </section>

      {/* Invite */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Send invite</h2>
        <form onSubmit={handleInvite} className={styles.form}>
          <div className={styles.inlineFields}>
            <div className={styles.field} style={{ flex: 2 }}>
              <label className={styles.label}>Email address</label>
              <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} className={styles.input} disabled={isInviting} placeholder="user@example.com" />
            </div>
            <div className={styles.field} style={{ flex: 1 }}>
              <label className={styles.label}>Role</label>
              <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)} className={styles.input} disabled={isInviting}>
                <option value="admin">Admin</option>
                <option value="operator">Operator</option>
                <option value="viewer">View-Only</option>
              </select>
            </div>
          </div>
          {inviteError && <p className={styles.error}>{inviteError}</p>}
          {inviteSuccess && <p className={styles.success}>{inviteSuccess}</p>}
          <button type="submit" className={styles.primaryButton} disabled={isInviting}>
            {isInviting ? 'Sending…' : 'Send invite'}
          </button>
        </form>
      </section>
    </div>
  );
}

export default TenantDetail;
