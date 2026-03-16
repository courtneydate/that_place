/**
 * Tenant list page — Fieldmouse Admin.
 * Shows all tenants with status badges and a link to each tenant's detail page.
 */
import { Link } from 'react-router-dom';
import { useTenants } from '../../hooks/useTenants';
import styles from './AdminPage.module.css';

function TenantList() {
  const { data, isLoading, isError } = useTenants();

  if (isLoading) return <p className={styles.loading}>Loading tenants…</p>;
  if (isError) return <p className={styles.error}>Failed to load tenants.</p>;

  const tenants = data?.results ?? data ?? [];

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Tenants</h1>
        <Link to="/admin/tenants/new" className={styles.primaryButton}>
          + New Tenant
        </Link>
      </div>

      {tenants.length === 0 ? (
        <p className={styles.empty}>No tenants yet. Create the first one.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Timezone</th>
              <th>Users</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tenants.map((tenant) => (
              <tr key={tenant.id}>
                <td>{tenant.name}</td>
                <td className={styles.mono}>{tenant.slug}</td>
                <td>{tenant.timezone}</td>
                <td>{tenant.user_count}</td>
                <td>
                  <span className={tenant.is_active ? styles.badgeActive : styles.badgeInactive}>
                    {tenant.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td>
                  <Link to={`/admin/tenants/${tenant.id}`} className={styles.link}>
                    Manage →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default TenantList;
