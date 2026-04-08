/**
 * Rule detail page — Overview and Audit Trail tabs.
 *
 * Route: /app/rules/:id
 * All tenant admins can view. Only Tenant Admins can edit.
 * Ref: SPEC.md § Feature: Rules Engine, § Feature: Rule Versioning & Audit Trail
 */
import PropTypes from 'prop-types';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useRule } from '../../hooks/useRules';
import { useState } from 'react';
import styles from '../admin/AdminPage.module.css';
import detailStyles from './DeviceDetail.module.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatTime(t) {
  if (!t) return '—';
  return String(t).slice(0, 5); // "HH:MM:SS" → "HH:MM"
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

function TabBar({ active, onChange }) {
  const tabs = ['Overview', 'Audit Trail'];
  return (
    <div className={detailStyles.tabBar}>
      {tabs.map((tab) => (
        <button
          key={tab}
          className={`${detailStyles.tab} ${active === tab ? detailStyles.tabActive : ''}`}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

TabBar.propTypes = {
  active: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

function InfoRow({ label, value }) {
  return (
    <div className={detailStyles.infoItem}>
      <span className={detailStyles.infoLabel}>{label}</span>
      <span className={detailStyles.infoValue}>{value ?? '—'}</span>
    </div>
  );
}

InfoRow.propTypes = { label: PropTypes.string.isRequired, value: PropTypes.any };

function OverviewTab({ rule }) {
  /**
   * Formatted read-only view of all rule configuration.
   */
  const dayNames = rule.active_days?.length > 0
    ? rule.active_days.map((d) => DAY_LABELS[d]).join(', ')
    : 'All days (no gate)';

  const channelLabel = (ch) =>
    ({ in_app: 'In-app', email: 'Email', sms: 'SMS', push: 'Push' }[ch] || ch);

  return (
    <div>
      {/* General info */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>General</h2>
        <div className={detailStyles.infoGrid}>
          <InfoRow label="Status" value={rule.is_active ? 'Active' : 'Inactive'} />
          <InfoRow label="Current state" value={rule.current_state ? 'Triggered' : 'Not triggered'} />
          <InfoRow label="Last fired" value={formatDateTime(rule.last_fired_at)} />
          <InfoRow label="Cooldown" value={rule.cooldown_minutes ? `${rule.cooldown_minutes} min` : 'None'} />
          {rule.description && <InfoRow label="Description" value={rule.description} />}
        </div>
      </div>

      {/* Schedule gate */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Schedule gate</h2>
        <div className={detailStyles.infoGrid}>
          <InfoRow label="Active days" value={dayNames} />
          {rule.active_days?.length > 0 && (
            <InfoRow
              label="Time window"
              value={
                rule.active_from
                  ? `${formatTime(rule.active_from)} – ${formatTime(rule.active_to)}`
                  : 'All day'
              }
            />
          )}
        </div>
      </div>

      {/* Conditions */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>
          Conditions — groups combined with {rule.condition_group_operator}
        </h2>
        {rule.condition_groups?.map((g, gi) => (
          <div key={g.id || gi} style={{ marginBottom: '1rem' }}>
            <p style={{ fontSize: '0.8125rem', fontWeight: 600, margin: '0 0 0.5rem', color: '#374151' }}>
              Group {gi + 1} — {g.logical_operator} between conditions
            </p>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Stream</th>
                  <th>Operator</th>
                  <th>Value / Threshold</th>
                </tr>
              </thead>
              <tbody>
                {g.conditions?.map((c, ci) => (
                  <tr key={c.id || ci}>
                    <td>{c.condition_type}</td>
                    <td className={styles.mono}>#{c.stream}</td>
                    <td>{c.condition_type === 'stream' ? c.operator : '—'}</td>
                    <td>
                      {c.condition_type === 'stream'
                        ? c.threshold_value
                        : `${c.staleness_minutes} min`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Actions</h2>
        {rule.actions?.map((a, ai) => (
          <div key={a.id || ai} style={{ marginBottom: '1rem' }}>
            <p style={{ fontSize: '0.8125rem', fontWeight: 600, margin: '0 0 0.5rem', color: '#374151' }}>
              Action {ai + 1} — {a.action_type === 'notify' ? 'Notification' : 'Device command'}
            </p>
            {a.action_type === 'notify' && (
              <div className={detailStyles.infoGrid}>
                <InfoRow label="Channels" value={a.notification_channels?.map(channelLabel).join(', ')} />
                {a.group_ids?.length > 0 && <InfoRow label="Groups" value={a.group_ids.join(', ')} />}
                {a.user_ids?.length > 0 && <InfoRow label="Users" value={a.user_ids.join(', ')} />}
                <InfoRow label="Message template" value={a.message_template} />
              </div>
            )}
            {a.action_type === 'command' && (
              <div className={detailStyles.infoGrid}>
                <InfoRow label="Target device" value={`#${a.target_device}`} />
                <InfoRow label="Command" value={a.command?.name} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

OverviewTab.propTypes = { rule: PropTypes.object.isRequired };

// ---------------------------------------------------------------------------
// Audit trail tab
// ---------------------------------------------------------------------------

function renderFieldValue(val) {
  if (val === null || val === undefined) return <em style={{ color: '#9CA3AF' }}>null</em>;
  if (typeof val === 'object') return <pre style={{ margin: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>{JSON.stringify(val, null, 2)}</pre>;
  return String(val);
}

function AuditTrailTab({ auditLogs }) {
  /**
   * Append-only table of all changes to the rule, with before/after values.
   * Ref: SPEC.md § Feature: Rule Versioning & Audit Trail
   */
  if (!auditLogs || auditLogs.length === 0) {
    return <p className={styles.empty}>No audit log entries yet.</p>;
  }

  return (
    <div>
      {auditLogs.map((entry) => (
        <div key={entry.id} className={styles.section} style={{ marginBottom: '1rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <p style={{ margin: 0, fontSize: '0.875rem', fontWeight: 600, color: '#111827' }}>
              {entry.changed_by_email || 'System'}
            </p>
            <span style={{ fontSize: '0.8125rem', color: '#6B7280' }}>
              {formatDateTime(entry.changed_at)}
            </span>
          </div>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Field</th>
                <th>Before</th>
                <th>After</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(entry.changed_fields || {}).map(([field, diff]) => (
                <tr key={field}>
                  <td className={styles.mono}>{field}</td>
                  <td style={{ color: '#EF4444' }}>{renderFieldValue(diff.before)}</td>
                  <td style={{ color: '#166534' }}>{renderFieldValue(diff.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

AuditTrailTab.propTypes = { auditLogs: PropTypes.array };

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function RuleDetail() {
  /**
   * Rule detail with Overview and Audit Trail tabs.
   */
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.tenant_role === 'admin';

  const { data: rule, isLoading, isError } = useRule(id);
  const [activeTab, setActiveTab] = useState('Overview');

  if (isLoading) return <p className={styles.loading}>Loading rule…</p>;
  if (isError || !rule) return <p className={styles.error}>Rule not found.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <Link to="/app/rules" className={styles.link}>← Rules</Link>
        <h1 style={{ margin: '0 0 0 1rem', fontSize: '1.5rem', fontWeight: 700, color: '#111827' }}>
          {rule.name}
        </h1>
        <span
          className={rule.is_active ? styles.badgeActive : styles.badgeInactive}
          style={{ marginLeft: '0.75rem' }}
        >
          {rule.is_active ? 'Active' : 'Inactive'}
        </span>
        {isAdmin && (
          <button
            className={styles.secondaryButton}
            style={{ marginLeft: 'auto' }}
            onClick={() => navigate(`/app/rules/${id}/edit`)}
          >
            Edit rule
          </button>
        )}
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} />

      <section>
        {activeTab === 'Overview' && <OverviewTab rule={rule} />}
        {activeTab === 'Audit Trail' && <AuditTrailTab auditLogs={rule.audit_logs} />}
      </section>
    </div>
  );
}

export default RuleDetail;
