/**
 * Alerts page — Active feed and History tabs.
 *
 * Route: /app/alerts
 * All tenant users can view. Admins and Operators can acknowledge and resolve
 * from the detail page.
 * Ref: SPEC.md § Feature: Alerts, § Key Screens — Alert Feed
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAlerts } from '../../hooks/useAlerts';
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
// Tab bar
// ---------------------------------------------------------------------------

function TabBar({ active, onChange }) {
  return (
    <div className={detailStyles.tabBar}>
      {['Active', 'History'].map((tab) => (
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
// Alert table
// ---------------------------------------------------------------------------

function AlertTable({ alerts, navigate }) {
  /**
   * Shared table layout for active and history tabs.
   * Clicking a row navigates to the alert detail page.
   */
  if (alerts.length === 0) {
    return <p className={styles.empty}>No alerts found.</p>;
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Rule</th>
          <th>Site</th>
          <th>Device</th>
          <th>Triggered</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {alerts.map((alert) => (
          <tr
            key={alert.id}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate(`/app/alerts/${alert.id}`)}
          >
            <td style={{ fontWeight: 600 }}>{alert.rule_name}</td>
            <td>{alert.site_names?.join(', ') || '—'}</td>
            <td>{alert.device_names?.join(', ') || '—'}</td>
            <td>{formatDateTime(alert.triggered_at)}</td>
            <td><StatusBadge status={alert.status} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

AlertTable.propTypes = {
  alerts: PropTypes.array.isRequired,
  navigate: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// History filters
// ---------------------------------------------------------------------------

function HistoryFilters({ filters, onChange }) {
  return (
    <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', alignItems: 'center' }}>
      <select
        value={filters.status || ''}
        onChange={(e) => onChange({ ...filters, status: e.target.value || undefined })}
        style={{ padding: '0.375rem 0.5rem', fontSize: '0.875rem', borderRadius: 4, border: '1px solid #D1D5DB' }}
      >
        <option value="">All statuses</option>
        <option value="active">Active</option>
        <option value="acknowledged">Acknowledged</option>
        <option value="resolved">Resolved</option>
      </select>
    </div>
  );
}

HistoryFilters.propTypes = {
  filters: PropTypes.object.isRequired,
  onChange: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function Alerts() {
  /**
   * Two-tab layout: Active (status=active) and History (all statuses, filterable).
   * Ref: SPEC.md § Feature: Alerts
   */
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('Active');
  const [historyFilters, setHistoryFilters] = useState({});

  const { data: activeAlerts = [], isLoading: loadingActive, isError: errorActive } =
    useAlerts({ status: 'active' });

  const { data: historyAlerts = [], isLoading: loadingHistory, isError: errorHistory } =
    useAlerts(historyFilters);

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Alerts</h1>
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} />

      <section>
        {activeTab === 'Active' && (
          <>
            {loadingActive && <p className={styles.loading}>Loading alerts…</p>}
            {errorActive && <p className={styles.error}>Failed to load alerts.</p>}
            {!loadingActive && !errorActive && (
              <AlertTable alerts={activeAlerts} navigate={navigate} />
            )}
          </>
        )}

        {activeTab === 'History' && (
          <>
            <HistoryFilters filters={historyFilters} onChange={setHistoryFilters} />
            {loadingHistory && <p className={styles.loading}>Loading history…</p>}
            {errorHistory && <p className={styles.error}>Failed to load alert history.</p>}
            {!loadingHistory && !errorHistory && (
              <AlertTable alerts={historyAlerts} navigate={navigate} />
            )}
          </>
        )}
      </section>
    </div>
  );
}

export default Alerts;
