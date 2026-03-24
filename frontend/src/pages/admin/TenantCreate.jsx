/**
 * Create tenant form — That Place Admin.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateTenant } from '../../hooks/useTenants';
import styles from './AdminPage.module.css';

const TIMEZONES = [
  'Australia/Sydney',
  'Australia/Melbourne',
  'Australia/Brisbane',
  'Australia/Adelaide',
  'Australia/Perth',
  'Australia/Darwin',
  'Australia/Hobart',
  'Pacific/Auckland',
  'UTC',
];

function TenantCreate() {
  const navigate = useNavigate();
  const { mutateAsync: createTenant, isPending } = useCreateTenant();

  const [name, setName] = useState('');
  const [timezone, setTimezone] = useState('Australia/Sydney');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) { setError('Name is required.'); return; }
    try {
      const tenant = await createTenant({ name, timezone });
      navigate(`/admin/tenants/${tenant.id}`);
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Failed to create tenant.');
    }
  };

  return (
    <div>
      <h1 className={styles.pageTitle}>New Tenant</h1>
      <form onSubmit={handleSubmit} className={styles.form}>
        <div className={styles.field}>
          <label className={styles.label}>Organisation name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={styles.input}
            disabled={isPending}
            placeholder="e.g. Riverdale City Council"
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Timezone</label>
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className={styles.input}
            disabled={isPending}
          >
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </div>
        {error && <p className={styles.error}>{error}</p>}
        <div className={styles.actions}>
          <button type="button" onClick={() => navigate(-1)} className={styles.secondaryButton} disabled={isPending}>
            Cancel
          </button>
          <button type="submit" className={styles.primaryButton} disabled={isPending}>
            {isPending ? 'Creating…' : 'Create tenant'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default TenantCreate;
