/**
 * Reporting page — CSV Data Export.
 *
 * Route: /app/reporting
 * Admin and Operator can configure and download a CSV export.
 * Export history tab is Admin-only.
 *
 * Ref: SPEC.md § Feature: Data Export (CSV)
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useDevices } from '../../hooks/useDevices';
import { useExportDownload, useExportHistory } from '../../hooks/useExports';
import { useDeviceStreams } from '../../hooks/useStreams';
import pageStyles from '../admin/AdminPage.module.css';
import tabStyles from './DeviceDetail.module.css';
import styles from './Reporting.module.css';

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

// ---------------------------------------------------------------------------
// Device row with lazily-loaded stream checkboxes
// ---------------------------------------------------------------------------

function DeviceRow({ device, expanded, onExpand, selectedIds, onToggle }) {
  /**
   * Renders a collapsible device header with stream checkboxes beneath.
   * Streams are fetched only when the device is expanded.
   */
  const { data: streams = [], isLoading } = useDeviceStreams(expanded ? device.id : null);

  const allSelected = streams.length > 0 && streams.every((s) => selectedIds.has(s.id));
  const someSelected = !allSelected && streams.some((s) => selectedIds.has(s.id));

  const handleDeviceToggle = () => {
    if (allSelected) {
      streams.forEach((s) => onToggle(s.id, false));
    } else {
      streams.forEach((s) => onToggle(s.id, true));
    }
  };

  return (
    <div className={styles.deviceBlock}>
      <div className={styles.deviceHeader}>
        <button
          className={styles.expandBtn}
          onClick={onExpand}
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse streams' : 'Expand streams'}
        >
          {expanded ? '▾' : '▸'}
        </button>
        <label className={styles.deviceLabel}>
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => { if (el) el.indeterminate = someSelected; }}
            onChange={handleDeviceToggle}
            disabled={!expanded || streams.length === 0}
          />
          <span className={styles.deviceName}>{device.name}</span>
          <span className={styles.deviceSerial}>{device.serial_number}</span>
          {device.site_name && <span className={styles.siteName}>{device.site_name}</span>}
        </label>
      </div>

      {expanded && (
        <div className={styles.streamList}>
          {isLoading && <p className={pageStyles.loading} style={{ padding: '0.5rem 1rem' }}>Loading…</p>}
          {!isLoading && streams.length === 0 && (
            <p className={pageStyles.empty} style={{ padding: '0.5rem 1rem' }}>No streams on this device.</p>
          )}
          {streams.map((stream) => (
            <label key={stream.id} className={styles.streamRow}>
              <input
                type="checkbox"
                checked={selectedIds.has(stream.id)}
                onChange={(e) => onToggle(stream.id, e.target.checked)}
              />
              <span className={styles.streamLabel}>{stream.label || stream.key}</span>
              {stream.unit && <span className={styles.streamUnit}>{stream.unit}</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

DeviceRow.propTypes = {
  device: PropTypes.object.isRequired,
  expanded: PropTypes.bool.isRequired,
  onExpand: PropTypes.func.isRequired,
  selectedIds: PropTypes.instanceOf(Set).isRequired,
  onToggle: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Cross-device stream picker
// ---------------------------------------------------------------------------

function StreamPicker({ selectedIds, onToggle }) {
  const { data: devices = [], isLoading } = useDevices({ status: 'active' });
  const [expandedDevice, setExpandedDevice] = useState(null);

  if (isLoading) return <p className={pageStyles.loading}>Loading devices…</p>;
  if (devices.length === 0) return <p className={pageStyles.empty}>No active devices found.</p>;

  return (
    <div className={styles.streamPicker}>
      {devices.map((device) => (
        <DeviceRow
          key={device.id}
          device={device}
          expanded={expandedDevice === device.id}
          onExpand={() => setExpandedDevice(expandedDevice === device.id ? null : device.id)}
          selectedIds={selectedIds}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

StreamPicker.propTypes = {
  selectedIds: PropTypes.instanceOf(Set).isRequired,
  onToggle: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Export form tab
// ---------------------------------------------------------------------------

function ExportForm() {
  const download = useExportDownload();
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleToggle = (streamId, checked) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(streamId);
      else next.delete(streamId);
      return next;
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg('');

    if (selectedIds.size === 0) {
      setErrorMsg('Select at least one stream.');
      return;
    }
    if (!dateFrom || !dateTo) {
      setErrorMsg('Both date/time fields are required.');
      return;
    }
    if (new Date(dateFrom) >= new Date(dateTo)) {
      setErrorMsg('"From" must be earlier than "To".');
      return;
    }

    setLoading(true);
    try {
      await download({
        streamIds: [...selectedIds],
        dateFrom: new Date(dateFrom).toISOString(),
        dateTo: new Date(dateTo).toISOString(),
      });
    } catch (err) {
      const raw = err?.response?.data?.error?.message;
      setErrorMsg(
        typeof raw === 'string' ? raw : 'Export failed. Please try again.',
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={pageStyles.section}>
      <h2 className={pageStyles.sectionTitle}>Configure Export</h2>
      <p className={pageStyles.sectionDesc}>
        Select one or more streams and a date/time window. The file downloads immediately — no email or scheduled delivery.
      </p>

      <form onSubmit={handleSubmit}>
        <div className={styles.dateRow}>
          <div className={pageStyles.field}>
            <label className={pageStyles.label} htmlFor="date-from">From (exclusive)</label>
            <input
              id="date-from"
              type="datetime-local"
              className={pageStyles.input}
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              required
            />
          </div>
          <div className={pageStyles.field}>
            <label className={pageStyles.label} htmlFor="date-to">To (inclusive)</label>
            <input
              id="date-to"
              type="datetime-local"
              className={pageStyles.input}
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              required
            />
          </div>
        </div>

        <div className={pageStyles.field} style={{ marginTop: '1.25rem' }}>
          <span className={pageStyles.label}>
            Streams
            {selectedIds.size > 0 && (
              <span className={styles.selectedCount}> ({selectedIds.size} selected)</span>
            )}
          </span>
          <StreamPicker selectedIds={selectedIds} onToggle={handleToggle} />
        </div>

        {errorMsg && <p className={pageStyles.error} style={{ marginTop: '0.75rem' }}>{errorMsg}</p>}

        <div className={pageStyles.actions} style={{ marginTop: '1.25rem' }}>
          <button
            type="submit"
            className={pageStyles.primaryButton}
            disabled={loading}
          >
            {loading ? 'Preparing download…' : 'Download CSV'}
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export history tab (Admin only)
// ---------------------------------------------------------------------------

function ExportHistory() {
  const { data: exports = [], isLoading, isError } = useExportHistory();

  if (isLoading) return <p className={pageStyles.loading}>Loading export history…</p>;
  if (isError) return <p className={pageStyles.error}>Failed to load export history.</p>;

  return (
    <div className={pageStyles.section}>
      <h2 className={pageStyles.sectionTitle}>Export History</h2>
      <p className={pageStyles.sectionDesc}>
        Each row represents a download that was initiated. To re-download, repeat the export configuration on the Export tab.
      </p>
      {exports.length === 0 ? (
        <p className={pageStyles.empty}>No exports yet.</p>
      ) : (
        <table className={pageStyles.table}>
          <thead>
            <tr>
              <th>Exported at</th>
              <th>By</th>
              <th>Streams</th>
              <th>From</th>
              <th>To</th>
            </tr>
          </thead>
          <tbody>
            {exports.map((exp) => (
              <tr key={exp.id}>
                <td>{formatDateTime(exp.exported_at)}</td>
                <td>{exp.exported_by_email || '—'}</td>
                <td className={pageStyles.mono}>
                  {exp.stream_ids.length} stream{exp.stream_ids.length !== 1 ? 's' : ''}
                </td>
                <td>{formatDateTime(exp.date_from)}</td>
                <td>{formatDateTime(exp.date_to)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page root
// ---------------------------------------------------------------------------

function Reporting() {
  /**
   * Reporting page — Export tab for all roles (Admin + Operator),
   * History tab for Admins only.
   */
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [activeTab, setActiveTab] = useState('Export');

  const tabs = isAdmin ? ['Export', 'History'] : ['Export'];

  return (
    <div>
      <div className={pageStyles.pageHeader}>
        <h1 className={pageStyles.pageTitle}>Reporting</h1>
      </div>

      <div className={tabStyles.tabBar}>
        {tabs.map((tab) => (
          <button
            key={tab}
            className={`${tabStyles.tab} ${activeTab === tab ? tabStyles.tabActive : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Export' && <ExportForm />}
      {activeTab === 'History' && isAdmin && <ExportHistory />}
    </div>
  );
}

export default Reporting;
