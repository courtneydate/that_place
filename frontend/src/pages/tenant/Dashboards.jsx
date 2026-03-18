/**
 * Dashboards list page — shows all dashboards for the tenant.
 * Operators and Admins can create and delete dashboards.
 * View-Only users can navigate to any dashboard.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDashboards, useCreateDashboard, useDeleteDashboard } from '../../hooks/useDashboards';
import styles from '../admin/AdminPage.module.css';

const COLUMN_OPTIONS = [1, 2, 3];

function Dashboards() {
  const { user } = useAuth();
  const canEdit = user?.tenant_role === 'admin' || user?.tenant_role === 'operator';

  const { data: dashboards = [], isLoading, error } = useDashboards();
  const createDashboard = useCreateDashboard();
  const deleteDashboard = useDeleteDashboard();

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [columns, setColumns] = useState(2);
  const [formError, setFormError] = useState('');

  const handleCreate = async (e) => {
    e.preventDefault();
    setFormError('');
    if (!name.trim()) {
      setFormError('Name is required.');
      return;
    }
    try {
      await createDashboard.mutateAsync({ name: name.trim(), columns });
      setName('');
      setColumns(2);
      setShowForm(false);
    } catch (err) {
      setFormError(err.response?.data?.error?.message || 'Failed to create dashboard.');
    }
  };

  const handleDelete = async (id, dashName) => {
    if (!window.confirm(`Delete dashboard "${dashName}"? This will remove all its widgets.`)) return;
    try {
      await deleteDashboard.mutateAsync(id);
    } catch {
      // ignore — dashboard may already be gone
    }
  };

  if (isLoading) return <p className={styles.loading}>Loading dashboards…</p>;
  if (error) return <p className={styles.error}>Failed to load dashboards.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Dashboards</h1>
        {canEdit && (
          <button className={styles.primaryButton} onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Cancel' : '+ New Dashboard'}
          </button>
        )}
      </div>

      {showForm && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>New Dashboard</h2>
          <form onSubmit={handleCreate} className={styles.form}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="dash-name">Name</label>
              <input
                id="dash-name"
                className={styles.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Field Sensors Overview"
                autoFocus
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="dash-cols">Columns</label>
              <select
                id="dash-cols"
                className={styles.input}
                value={columns}
                onChange={(e) => setColumns(Number(e.target.value))}
              >
                {COLUMN_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
            {formError && <p className={styles.error}>{formError}</p>}
            <div className={styles.actions}>
              <button
                type="submit"
                className={styles.primaryButton}
                disabled={createDashboard.isPending}
              >
                {createDashboard.isPending ? 'Creating…' : 'Create Dashboard'}
              </button>
            </div>
          </form>
        </div>
      )}

      {dashboards.length === 0 ? (
        <p className={styles.empty}>
          No dashboards yet.{canEdit ? ' Click "+ New Dashboard" to create one.' : ''}
        </p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Columns</th>
              <th>Widgets</th>
              <th>Created by</th>
              {canEdit && <th></th>}
            </tr>
          </thead>
          <tbody>
            {dashboards.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link to={`/app/dashboards/${d.id}`} className={styles.link}>
                    {d.name}
                  </Link>
                </td>
                <td>{d.columns}</td>
                <td>{d.widgets?.length ?? 0}</td>
                <td className={styles.mono}>{d.created_by_email || '—'}</td>
                {canEdit && (
                  <td>
                    <button
                      className={styles.dangerButton}
                      onClick={() => handleDelete(d.id, d.name)}
                      disabled={deleteDashboard.isPending}
                    >
                      Delete
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default Dashboards;
