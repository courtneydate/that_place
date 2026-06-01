/**
 * Sprint 29a — historical backfill panel for a 3rd-party DataSource.
 *
 * Renders inside the DataSources page when the Tenant Admin clicks "Backfill"
 * on a row whose provider has `supports_history=true`. Surfaces a date range
 * form and a recent-jobs table. While any job is queued or running the jobs
 * query refetches every 5s (see useBackfillJobs).
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import {
  useBackfillJobs,
  useStartBackfillJob,
} from '../hooks/useIntegrations';
import styles from '../pages/admin/AdminPage.module.css';

const JOB_ACTIVE = new Set(['queued', 'running']);

const BACKFILL_STATUS_LABEL = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
};

const BACKFILL_STATUS_COLOR = {
  queued: 'var(--text-muted)',
  running: 'var(--info, #0284c7)',
  completed: 'var(--success)',
  failed: 'var(--danger)',
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function BackfillPanel({ ds }) {
  const { data: jobs = [], isLoading } = useBackfillJobs(ds.id);
  const startJob = useStartBackfillJob(ds.id);
  const [dateFrom, setDateFrom] = useState(daysAgoIso(7));
  const [dateTo, setDateTo] = useState(todayIso());
  const [error, setError] = useState('');

  const activeJob = jobs.find((j) => JOB_ACTIVE.has(j.status));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await startJob.mutateAsync({ dateFrom, dateTo });
    } catch (err) {
      setError(
        err.response?.data?.error?.message
        || err.response?.data?.error?.details?.date_to?.[0]
        || 'Failed to start backfill.',
      );
    }
  };

  return (
    <div
      style={{
        padding: '1rem',
        background: 'var(--surface-raised, #f9f9f9)',
        borderTop: '1px solid var(--border)',
      }}
    >
      <h3 style={{ marginTop: 0 }}>Historical backfill</h3>
      <p style={{ color: 'var(--text-muted)', marginTop: 0 }}>
        Fetch historical readings from {ds.provider_name} for a date range.
        Maximum window: 365 days. Backfill and live polling never run on the
        same device at the same time.
      </p>

      <form
        onSubmit={handleSubmit}
        style={{
          display: 'flex', gap: '1rem', alignItems: 'flex-end',
          flexWrap: 'wrap', marginBottom: '1rem',
        }}
      >
        <label style={{ display: 'flex', flexDirection: 'column' }}>
          From
          <input
            type="date"
            value={dateFrom}
            max={dateTo}
            onChange={(e) => setDateFrom(e.target.value)}
            disabled={!!activeJob || startJob.isPending}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column' }}>
          To
          <input
            type="date"
            value={dateTo}
            min={dateFrom}
            max={todayIso()}
            onChange={(e) => setDateTo(e.target.value)}
            disabled={!!activeJob || startJob.isPending}
          />
        </label>
        <button
          type="submit"
          className={styles.primaryButton}
          disabled={!!activeJob || startJob.isPending}
        >
          {activeJob
            ? `Backfill ${BACKFILL_STATUS_LABEL[activeJob.status].toLowerCase()}…`
            : 'Start backfill'}
        </button>
      </form>

      {error && <p className={styles.error}>{error}</p>}

      <h4>Recent jobs</h4>
      {isLoading && <p className={styles.loading}>Loading…</p>}
      {!isLoading && jobs.length === 0 && (
        <p className={styles.empty}>No backfill jobs yet.</p>
      )}
      {!isLoading && jobs.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Window</th>
              <th>Status</th>
              <th>Rows stored</th>
              <th>Requested by</th>
              <th>Finished</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>{job.date_from} → {job.date_to}</td>
                <td>
                  <span style={{ color: BACKFILL_STATUS_COLOR[job.status] }}>
                    {BACKFILL_STATUS_LABEL[job.status]}
                  </span>
                  {job.status === 'failed' && job.error_detail && (
                    <div
                      style={{
                        color: 'var(--danger)',
                        fontSize: '0.8rem',
                        marginTop: '0.25rem',
                      }}
                    >
                      {job.error_detail}
                    </div>
                  )}
                </td>
                <td>
                  {job.rows_stored}
                  {job.rows_fetched ? ` / ${job.rows_fetched} fetched` : ''}
                </td>
                <td>{job.created_by_email || '—'}</td>
                <td>
                  {job.finished_at ? new Date(job.finished_at).toLocaleString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

BackfillPanel.propTypes = {
  ds: PropTypes.shape({
    id: PropTypes.number.isRequired,
    provider_name: PropTypes.string,
  }).isRequired,
};

export default BackfillPanel;
