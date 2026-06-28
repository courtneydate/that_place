/**
 * Billing Runs list page (Sprint 32).
 *
 * Route: /app/billing-runs
 * Lists all billing runs for the tenant with status badges.
 * Tenant Admin can create a new run. All tenant roles can view.
 *
 * Ref: SPEC.md § Feature: Billing Runs & Invoicing
 *      ROADMAP.md § Sprint 32
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useSites } from '../../hooks/useSites';
import {
  useCreateBillingRun,
  useBillingRuns,
} from '../../hooks/useBillingRuns';
import styles from '../admin/AdminPage.module.css';

const STATUS_BADGE = {
  queued:    { label: 'Queued',    cls: styles.badgeInactive },
  computing: { label: 'Computing', cls: styles.badgeWarning },
  draft:     { label: 'Draft',     cls: styles.badgeWarning },
  review:    { label: 'Review',    cls: styles.badgeWarning },
  finalized: { label: 'Finalized', cls: styles.badgeActive },
  voided:    { label: 'Voided',    cls: styles.badgeInactive },
  failed:    { label: 'Failed',    cls: styles.badgeDanger },
};

import PropTypes from 'prop-types';

function RunStatusBadge({ status }) {
  const { label, cls } = STATUS_BADGE[status] || { label: status, cls: styles.badgeInactive };
  return <span className={cls}>{label}</span>;
}
RunStatusBadge.propTypes = { status: PropTypes.string.isRequired };

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

// ---------------------------------------------------------------------------
// Create run form
// ---------------------------------------------------------------------------

function CreateRunForm({ onDone }) {
  const { data: sites = [] } = useSites();
  const createRun = useCreateBillingRun();

  const [siteId, setSiteId] = useState('');
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [aggregatePeriod, setAggregatePeriod] = useState('30min');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!siteId || !periodStart || !periodEnd) {
      setError('Site, period start, and period end are required.');
      return;
    }
    try {
      await createRun.mutateAsync({
        site: siteId,
        period_start: new Date(periodStart).toISOString(),
        period_end: new Date(periodEnd).toISOString(),
        aggregate_period: aggregatePeriod,
      });
      onDone();
    } catch (err) {
      const msg = err.response?.data?.error?.message || 'Failed to create billing run.';
      setError(msg);
    }
  };

  return (
    <div className={styles.section}>
      <h2 className={styles.sectionTitle}>New Billing Run</h2>
      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.field}>
          <label className={styles.label}>Site</label>
          <select
            className={styles.input}
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            required
          >
            <option value="">Select a site…</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
        <div className={styles.inlineFields}>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label}>Period start</label>
            <input
              type="datetime-local"
              className={styles.input}
              value={periodStart}
              onChange={(e) => setPeriodStart(e.target.value)}
              required
            />
          </div>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label}>Period end</label>
            <input
              type="datetime-local"
              className={styles.input}
              value={periodEnd}
              onChange={(e) => setPeriodEnd(e.target.value)}
              required
            />
          </div>
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Aggregate period</label>
          <select
            className={styles.input}
            value={aggregatePeriod}
            onChange={(e) => setAggregatePeriod(e.target.value)}
          >
            <option value="5min">5 minutes</option>
            <option value="30min">30 minutes</option>
            <option value="1h">1 hour</option>
          </select>
        </div>
        {error && <p className={styles.error}>{error}</p>}
        <div className={styles.actions}>
          <button type="submit" className={styles.primaryButton} disabled={createRun.isPending}>
            {createRun.isPending ? 'Creating…' : 'Create run'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onDone}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

CreateRunForm.propTypes = { onDone: PropTypes.func.isRequired };

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BillingRuns() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';
  const [showForm, setShowForm] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');

  const { data: runs = [], isLoading, isError } = useBillingRuns(
    statusFilter ? { status: statusFilter } : {},
  );

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Billing Runs</h1>
        {isAdmin && !showForm && (
          <button className={styles.primaryButton} onClick={() => setShowForm(true)}>
            New run
          </button>
        )}
      </div>

      {showForm && (
        <CreateRunForm onDone={() => setShowForm(false)} />
      )}

      <div className={styles.section}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <label className={styles.label} style={{ margin: 0 }}>Status</label>
          <select
            className={styles.input}
            style={{ width: 'auto' }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All</option>
            {Object.entries(STATUS_BADGE).map(([val, { label }]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>
        </div>

        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load billing runs.</p>}

        {!isLoading && !isError && runs.length === 0 && (
          <p className={styles.empty}>No billing runs yet.</p>
        )}

        {runs.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Period</th>
                <th>Site</th>
                <th>Status</th>
                <th>Aggregate</th>
                <th>Created</th>
                <th>Finalized</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>
                    {formatDate(run.period_start)} – {formatDate(run.period_end)}
                  </td>
                  <td>{run.site_name || run.site}</td>
                  <td><RunStatusBadge status={run.status} /></td>
                  <td className={styles.mono}>{run.aggregate_period}</td>
                  <td>{formatDate(run.created_at)}</td>
                  <td>{run.finalized_at ? formatDate(run.finalized_at) : '—'}</td>
                  <td>
                    <Link className={styles.link} to={`/app/billing-runs/${run.id}`}>
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
