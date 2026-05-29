/**
 * Tariffs — tenant-scoped Reference Datasets that act as PPA / retail
 * tariff templates (Sprint 30).
 *
 * Read-only filtered view of `scope=tenant` Reference Datasets. Editing
 * rows still happens via the existing admin pages — this page is the
 * billing-side surface for operators to see which templates are available
 * and click through to manage rows.
 *
 * Ref: ROADMAP.md § Sprint 30 — "Tariffs" nav item
 */
import { useAuth } from '../../context/AuthContext';
import { useReferenceDatasets } from '../../hooks/useFeeds';
import styles from '../admin/AdminPage.module.css';

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function Tariffs() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  const { data: datasets = [], isLoading, isError } = useReferenceDatasets();
  const tenantDatasets = datasets.filter((d) => d.scope === 'tenant');

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Tariffs</h1>
      </div>

      <section className={styles.section}>
        <p style={{ fontSize: '0.875rem', color: '#374151', marginTop: 0 }}>
          PPA generation, consumption-from-solar, feed-in, and retail tariff datasets
          (<code>scope=tenant</code>). Operators add rows for each plan; the billing engine
          (Sprint 31) resolves the rate at run time using each
          BillingAccountTariffAssignment&apos;s dimension filter and version pin.
          {isAdmin && (
            <>
              {' '}Manage rows via{' '}
              <em>That Place Admin → Reference Datasets</em>.
            </>
          )}
        </p>

        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load tariff datasets.</p>}
        {!isLoading && !isError && tenantDatasets.length === 0 && (
          <p className={styles.empty}>
            No tenant-scope tariff datasets configured yet. Ask a platform
            administrator to seed the PPA tariff templates.
          </p>
        )}
        {!isLoading && tenantDatasets.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Slug</th>
                <th>Dimensions</th>
                <th>Values</th>
                <th>TOU</th>
                <th>Versioned</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {tenantDatasets.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td className={styles.mono}>{d.slug}</td>
                  <td className={styles.mono} style={{ fontSize: '0.8125rem' }}>
                    {Object.keys(d.dimension_schema || {}).join(', ') || '—'}
                  </td>
                  <td className={styles.mono} style={{ fontSize: '0.8125rem' }}>
                    {Object.keys(d.value_schema || {}).join(', ') || '—'}
                  </td>
                  <td>{d.has_time_of_use ? 'Yes' : 'No'}</td>
                  <td>{d.has_version ? 'Yes' : 'No'}</td>
                  <td>{formatDate(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default Tariffs;
