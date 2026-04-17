/**
 * Alert detail page — status, context, and acknowledge/resolve actions.
 *
 * Route: /app/alerts/:id
 * All tenant users can view. Admins and Operators see the action buttons.
 * Ref: SPEC.md § Feature: Alerts
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useAcknowledgeAlert, useAlert, useResolveAlert } from '../../hooks/useAlerts';
import styles from '../admin/AdminPage.module.css';
import detailStyles from './DeviceDetail.module.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function InfoRow({ label, value }) {
  return (
    <div className={detailStyles.infoItem}>
      <span className={detailStyles.infoLabel}>{label}</span>
      <span className={detailStyles.infoValue}>{value ?? '—'}</span>
    </div>
  );
}

InfoRow.propTypes = { label: PropTypes.string.isRequired, value: PropTypes.any };

function StatusBadge({ status }) {
  const map = {
    active: { label: 'Active', className: styles.badgeDanger },
    acknowledged: { label: 'Acknowledged', className: styles.badgeWarning },
    resolved: { label: 'Resolved', className: styles.badgeActive },
  };
  const { label, className } = map[status] || { label: status, className: styles.badgeInactive };
  return <span className={className}>{label}</span>;
}

StatusBadge.propTypes = { status: PropTypes.string.isRequired };

// ---------------------------------------------------------------------------
// Acknowledge form
// ---------------------------------------------------------------------------

function AcknowledgeForm({ alertId, onDone }) {
  /**
   * Inline form shown when the user clicks "Acknowledge".
   * The troubleshooting note is optional.
   */
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const acknowledge = useAcknowledgeAlert();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await acknowledge.mutateAsync({ alertId, note });
      onDone();
    } catch {
      setError('Failed to acknowledge alert. Please try again.');
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ marginTop: '1rem' }}>
      <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.5rem' }}>
        Troubleshooting note (optional)
      </label>
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={3}
        placeholder="What did you find? What action was taken?"
        style={{
          width: '100%', padding: '0.5rem', fontSize: '0.875rem',
          border: '1px solid #D1D5DB', borderRadius: 4, resize: 'vertical',
          boxSizing: 'border-box',
        }}
      />
      {error && <p className={styles.error} style={{ marginTop: '0.5rem' }}>{error}</p>}
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
        <button
          type="submit"
          disabled={acknowledge.isPending}
          className={styles.primaryButton}
        >
          {acknowledge.isPending ? 'Acknowledging…' : 'Confirm acknowledge'}
        </button>
        <button type="button" className={styles.secondaryButton} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

AcknowledgeForm.propTypes = {
  alertId: PropTypes.number.isRequired,
  onDone: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function AlertDetail() {
  /**
   * Alert detail with status summary, context (rule, site, device), and
   * acknowledge/resolve actions for Operators and Admins.
   * Ref: SPEC.md § Feature: Alerts
   */
  const { id } = useParams();
  const { user } = useAuth();
  const canAct = user?.tenant_role === 'admin' || user?.tenant_role === 'operator';

  const { data: alert, isLoading, isError } = useAlert(id);
  const [showAckForm, setShowAckForm] = useState(false);
  const [actionError, setActionError] = useState('');
  const resolve = useResolveAlert();

  if (isLoading) return <p className={styles.loading}>Loading alert…</p>;
  if (isError || !alert) return <p className={styles.error}>Alert not found.</p>;

  const handleResolve = async () => {
    setActionError('');
    try {
      await resolve.mutateAsync(alert.id);
    } catch {
      setActionError('Failed to resolve alert. Please try again.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <Link to="/app/alerts" className={styles.link}>← Alerts</Link>
        <h1 style={{ margin: '0 0 0 1rem', fontSize: '1.5rem', fontWeight: 700, color: '#111827' }}>
          {alert.rule_name}
        </h1>
        <span style={{ marginLeft: '0.75rem' }}>
          <StatusBadge status={alert.status} />
        </span>
      </div>

      {/* Alert context */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Alert details</h2>
        <div className={detailStyles.infoGrid}>
          <InfoRow label="Rule" value={alert.rule_name} />
          <InfoRow label="Triggered at" value={formatDateTime(alert.triggered_at)} />
          <InfoRow label="Status" value={<StatusBadge status={alert.status} />} />
          <InfoRow label="Site(s)" value={alert.site_names?.join(', ') || '—'} />
          <InfoRow label="Device(s)" value={alert.device_names?.join(', ') || '—'} />
        </div>
      </div>

      {/* Acknowledgement info */}
      {alert.status !== 'active' && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Acknowledgement</h2>
          <div className={detailStyles.infoGrid}>
            <InfoRow label="Acknowledged by" value={alert.acknowledged_by_email} />
            <InfoRow label="Acknowledged at" value={formatDateTime(alert.acknowledged_at)} />
            {alert.acknowledged_note && (
              <InfoRow label="Note" value={alert.acknowledged_note} />
            )}
          </div>
        </div>
      )}

      {/* Resolution info */}
      {alert.status === 'resolved' && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Resolution</h2>
          <div className={detailStyles.infoGrid}>
            <InfoRow label="Resolved by" value={alert.resolved_by_email} />
            <InfoRow label="Resolved at" value={formatDateTime(alert.resolved_at)} />
          </div>
        </div>
      )}

      {/* Actions */}
      {canAct && alert.status !== 'resolved' && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Actions</h2>
          {actionError && <p className={styles.error} style={{ marginBottom: '1rem' }}>{actionError}</p>}

          {alert.status === 'active' && !showAckForm && (
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <button
                className={styles.primaryButton}
                onClick={() => setShowAckForm(true)}
              >
                Acknowledge
              </button>
              <button
                className={styles.secondaryButton}
                onClick={handleResolve}
                disabled={resolve.isPending}
              >
                {resolve.isPending ? 'Resolving…' : 'Resolve'}
              </button>
            </div>
          )}

          {alert.status === 'active' && showAckForm && (
            <AcknowledgeForm
              alertId={alert.id}
              onDone={() => setShowAckForm(false)}
            />
          )}

          {alert.status === 'acknowledged' && (
            <button
              className={styles.primaryButton}
              onClick={handleResolve}
              disabled={resolve.isPending}
            >
              {resolve.isPending ? 'Resolving…' : 'Mark resolved'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default AlertDetail;
