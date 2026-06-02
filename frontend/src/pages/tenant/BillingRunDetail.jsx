/**
 * Billing Run detail page (Sprint 32).
 *
 * Route: /app/billing-runs/:id
 * Tabs: Overview | Line Items | Invoices | Snapshot
 * Action buttons (role/status gated): Retry, Recompute, Finalize, Void.
 *
 * Ref: SPEC.md § Feature: Billing Runs & Invoicing
 *      ROADMAP.md § Sprint 32
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  useBillingInvoices,
  useBillingRun,
  useBillingRunLineItems,
  useBillingRunSnapshot,
  useFinalizeBillingRun,
  useRecomputeBillingRun,
  useRetryBillingRun,
  useVoidBillingRun,
} from '../../hooks/useBillingRuns';
import api from '../../services/api';
import styles from '../admin/AdminPage.module.css';
import detailStyles from './DeviceDetail.module.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function fmtCents(cents) {
  if (cents == null) return '—';
  return `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

const RUN_STATUS_BADGE = {
  queued:    styles.badgeInactive,
  computing: styles.badgeWarning,
  draft:     styles.badgeWarning,
  review:    styles.badgeWarning,
  finalized: styles.badgeActive,
  voided:    styles.badgeInactive,
  failed:    styles.badgeDanger,
};

function RunStatusBadge({ status }) {
  return (
    <span className={RUN_STATUS_BADGE[status] || styles.badgeInactive}>
      {status}
    </span>
  );
}
RunStatusBadge.propTypes = { status: PropTypes.string.isRequired };

const DELIVERY_BADGE = {
  pending:   styles.badgeWarning,
  sent:      styles.badgeActive,
  delivered: styles.badgeActive,
  failed:    styles.badgeDanger,
};

const INVOICE_STATUS_BADGE = {
  draft:     styles.badgeWarning,
  delivered: styles.badgeActive,
  void:      styles.badgeInactive,
};

// ---------------------------------------------------------------------------
// Void modal
// ---------------------------------------------------------------------------

function VoidModal({ runId, onDone }) {
  const voidRun = useVoidBillingRun(runId);
  const [reason, setReason] = useState('');
  const [silentVoid, setSilentVoid] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await voidRun.mutateAsync({ reason, silentVoid });
      onDone();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Void failed.');
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#fff', borderRadius: 8, padding: '2rem',
        width: 480, boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
      }}>
        <h2 style={{ margin: '0 0 1rem', fontSize: '1.125rem', fontWeight: 700 }}>
          Void billing run
        </h2>
        <p style={{ margin: '0 0 1rem', fontSize: '0.875rem', color: '#6B7280' }}>
          Voiding is permanent. All invoices will be marked void. Delivered invoices
          will receive a void-notification email unless you suppress it below.
        </p>
        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label className={styles.label}>Reason (optional)</label>
            <input
              className={styles.input}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Correcting meter read"
            />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem' }}>
            <input
              type="checkbox"
              checked={silentVoid}
              onChange={(e) => setSilentVoid(e.target.checked)}
            />
            Suppress void-notification emails (silent void)
          </label>
          {error && <p className={styles.error}>{error}</p>}
          <div className={styles.actions}>
            <button
              type="submit"
              className={styles.dangerButton}
              disabled={voidRun.isPending}
            >
              {voidRun.isPending ? 'Voiding…' : 'Confirm void'}
            </button>
            <button type="button" className={styles.secondaryButton} onClick={onDone}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
VoidModal.propTypes = { runId: PropTypes.number.isRequired, onDone: PropTypes.func.isRequired };

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

const TABS = ['Overview', 'Line Items', 'Invoices', 'Snapshot'];

// ---------------------------------------------------------------------------
// Tab content — Overview
// ---------------------------------------------------------------------------

function OverviewTab({ run }) {
  const pairs = [
    ['Period', `${fmtDate(run.period_start)} – ${fmtDate(run.period_end)}`],
    ['Site', run.site_name || run.site],
    ['Timezone', run.timezone_snapshot],
    ['Aggregate period', run.aggregate_period],
    ['Status', <RunStatusBadge key="s" status={run.status} />],
    ['Created', fmt(run.created_at)],
    ['Computed', fmt(run.computed_at)],
    ['Finalized', fmt(run.finalized_at)],
    ['Finalized by', run.finalized_by_email || '—'],
    ['Voided', fmt(run.voided_at)],
    ['Void reason', run.void_reason || '—'],
  ];
  return (
    <div className={styles.section}>
      <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '0.75rem', columnGap: '1rem' }}>
        {pairs.map(([label, val]) => (
          <div key={label} style={{ display: 'contents' }}>
            <dt style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#6B7280', alignSelf: 'center' }}>
              {label}
            </dt>
            <dd style={{ fontSize: '0.875rem', color: '#111827', margin: 0 }}>{val}</dd>
          </div>
        ))}
      </dl>
      {run.failure_detail && (
        <div style={{
          marginTop: '1.25rem', padding: '0.75rem 1rem',
          background: '#FEF2F2', borderRadius: 6,
          fontSize: '0.875rem', color: '#991B1B',
        }}>
          <strong>Failure detail:</strong> {run.failure_detail}
        </div>
      )}
    </div>
  );
}
OverviewTab.propTypes = { run: PropTypes.object.isRequired };

// ---------------------------------------------------------------------------
// Tab content — Line Items
// ---------------------------------------------------------------------------

function LineItemsTab({ runId }) {
  const { data: items = [], isLoading } = useBillingRunLineItems(runId);

  const downloadCsv = () => {
    api.get(`/api/v1/billing-runs/${runId}/line-items-csv/`, { responseType: 'blob' })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        const a = document.createElement('a');
        a.href = url;
        a.download = `billing-run-${runId}-line-items.csv`;
        a.click();
        URL.revokeObjectURL(url);
      });
  };

  if (isLoading) return <p className={styles.loading}>Loading…</p>;

  return (
    <div className={styles.section}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
        <button className={styles.secondaryButton} onClick={downloadCsv}>
          Download CSV
        </button>
      </div>
      {items.length === 0 ? (
        <p className={styles.empty}>No line items yet.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Account</th>
              <th>Kind</th>
              <th>Period</th>
              <th>kWh</th>
              <th>Rate (c/kWh)</th>
              <th>Amount</th>
              <th>GST</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.billing_account_name || item.billing_account}</td>
                <td className={styles.mono}>{item.line_kind}</td>
                <td>{item.period_name || '—'}</td>
                <td className={styles.mono}>{item.kwh != null ? Number(item.kwh).toFixed(3) : '—'}</td>
                <td className={styles.mono}>{item.rate_cents_per_kwh != null ? Number(item.rate_cents_per_kwh).toFixed(4) : '—'}</td>
                <td className={styles.mono}>{fmtCents(item.amount_cents)}</td>
                <td className={styles.mono}>{fmtCents(item.gst_cents)}</td>
                <td className={styles.mono}>{fmtCents(item.amount_cents + item.gst_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
LineItemsTab.propTypes = { runId: PropTypes.number.isRequired };

// ---------------------------------------------------------------------------
// Tab content — Invoices
// ---------------------------------------------------------------------------

function InvoicesTab({ runId }) {
  const { data: invoices = [], isLoading } = useBillingInvoices({ run: runId });

  if (isLoading) return <p className={styles.loading}>Loading…</p>;

  return (
    <div className={styles.section}>
      {invoices.length === 0 ? (
        <p className={styles.empty}>No invoices yet — finalize the run to generate them.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Invoice #</th>
              <th>Account</th>
              <th>Subtotal</th>
              <th>GST</th>
              <th>Total</th>
              <th>Status</th>
              <th>Delivery</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id}>
                <td className={styles.mono}>{inv.invoice_number}</td>
                <td>{inv.billing_account_name || inv.billing_account}</td>
                <td className={styles.mono}>{fmtCents(inv.subtotal_cents)}</td>
                <td className={styles.mono}>{fmtCents(inv.gst_cents)}</td>
                <td className={styles.mono}>{fmtCents(inv.total_cents)}</td>
                <td>
                  <span className={INVOICE_STATUS_BADGE[inv.status] || styles.badgeInactive}>
                    {inv.status}
                  </span>
                </td>
                <td>
                  <span className={DELIVERY_BADGE[inv.delivery_status] || styles.badgeInactive}>
                    {inv.delivery_status}
                  </span>
                </td>
                <td>
                  <Link className={styles.link} to={`/app/invoices/${inv.id}`}>
                    View →
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
InvoicesTab.propTypes = { runId: PropTypes.number.isRequired };

// ---------------------------------------------------------------------------
// Tab content — Snapshot
// ---------------------------------------------------------------------------

function SnapshotTab({ runId }) {
  const { data: snaps = [], isLoading } = useBillingRunSnapshot(runId);

  if (isLoading) return <p className={styles.loading}>Loading…</p>;

  return (
    <div className={styles.section}>
      {snaps.length === 0 ? (
        <p className={styles.empty}>No snapshot data yet.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Account</th>
              <th>Stream</th>
              <th>Computed kWh</th>
              <th>Quality summary</th>
            </tr>
          </thead>
          <tbody>
            {snaps.map((snap) => (
              <tr key={snap.id}>
                <td>{snap.billing_account_name || snap.billing_account}</td>
                <td className={styles.mono}>{snap.stream_label || snap.stream}</td>
                <td className={styles.mono}>{Number(snap.computed_kwh).toFixed(3)}</td>
                <td className={styles.mono} style={{ fontSize: '0.8125rem' }}>
                  {JSON.stringify(snap.quality_summary)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
SnapshotTab.propTypes = { runId: PropTypes.number.isRequired };

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BillingRunDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [tab, setTab] = useState('Overview');
  const [showVoidModal, setShowVoidModal] = useState(false);
  const [actionError, setActionError] = useState('');

  const { data: run, isLoading, isError } = useBillingRun(id);
  const retry = useRetryBillingRun(id);
  const recompute = useRecomputeBillingRun(id);
  const finalize = useFinalizeBillingRun(id);

  if (isLoading) return <p className={styles.loading}>Loading…</p>;
  if (isError || !run) return <p className={styles.error}>Billing run not found.</p>;

  const canRetry = isAdmin && run.status === 'failed';
  const canRecompute = isAdmin && (run.status === 'draft' || run.status === 'review');
  const canFinalize = isAdmin && (run.status === 'draft' || run.status === 'review');
  const canVoid = isAdmin && run.status === 'finalized';

  const doAction = async (fn) => {
    setActionError('');
    try {
      await fn();
    } catch (err) {
      setActionError(err.response?.data?.error?.message || 'Action failed.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <div>
          <Link to="/app/billing-runs" className={styles.link} style={{ fontSize: '0.875rem' }}>
            ← Billing Runs
          </Link>
          <h1 className={styles.pageTitle} style={{ marginTop: '0.25rem' }}>
            Billing Run — {fmtDate(run.period_start)} to {fmtDate(run.period_end)}
          </h1>
        </div>

        {isAdmin && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {canRetry && (
              <button
                className={styles.secondaryButton}
                disabled={retry.isPending}
                onClick={() => doAction(() => retry.mutateAsync())}
              >
                {retry.isPending ? 'Retrying…' : 'Retry'}
              </button>
            )}
            {canRecompute && (
              <button
                className={styles.secondaryButton}
                disabled={recompute.isPending}
                onClick={() => doAction(() => recompute.mutateAsync())}
              >
                {recompute.isPending ? 'Recomputing…' : 'Recompute'}
              </button>
            )}
            {canFinalize && (
              <button
                className={styles.primaryButton}
                disabled={finalize.isPending}
                onClick={() => doAction(() => finalize.mutateAsync())}
              >
                {finalize.isPending ? 'Finalizing…' : 'Finalize'}
              </button>
            )}
            {canVoid && (
              <button
                className={styles.dangerButton}
                onClick={() => setShowVoidModal(true)}
              >
                Void
              </button>
            )}
          </div>
        )}
      </div>

      {actionError && <p className={styles.error} style={{ marginBottom: '1rem' }}>{actionError}</p>}

      <div className={detailStyles.tabBar}>
        {TABS.map((t) => (
          <button
            key={t}
            className={`${detailStyles.tab} ${tab === t ? detailStyles.tabActive : ''}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Overview' && <OverviewTab run={run} />}
      {tab === 'Line Items' && <LineItemsTab runId={Number(id)} />}
      {tab === 'Invoices' && <InvoicesTab runId={Number(id)} />}
      {tab === 'Snapshot' && <SnapshotTab runId={Number(id)} />}

      {showVoidModal && (
        <VoidModal runId={Number(id)} onDone={() => setShowVoidModal(false)} />
      )}
    </div>
  );
}
