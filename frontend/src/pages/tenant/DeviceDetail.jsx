/**
 * Device detail page — health tab and device info.
 *
 * Shows the health status (activity level, online/offline, last seen,
 * first active, signal strength, battery level) for a single device.
 * Accessible to all tenant roles (View-Only and above).
 * Ref: SPEC.md § Feature: Device Health Monitoring
 */
import { Link, useParams } from 'react-router-dom';
import { useDevices, useDeviceHealth } from '../../hooks/useDevices';
import styles from '../admin/AdminPage.module.css';
import detailStyles from './DeviceDetail.module.css';

const ACTIVITY_COLORS = {
  normal: '#22C55E',
  degraded: '#F59E0B',
  critical: '#EF4444',
};

const ACTIVITY_LABELS = {
  normal: 'Normal',
  degraded: 'Degraded',
  critical: 'Critical',
};

function ActivityBadge({ level }) {
  const color = ACTIVITY_COLORS[level] || '#9CA3AF';
  const label = ACTIVITY_LABELS[level] || level || 'Unknown';
  return (
    <span style={{ color, fontWeight: 600 }}>{label}</span>
  );
}

function OnlineBadge({ isOnline }) {
  return (
    <span style={{ color: isOnline ? '#22C55E' : '#6B7280', fontWeight: 600 }}>
      {isOnline ? 'Online' : 'Offline'}
    </span>
  );
}

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function HealthCard({ health }) {
  return (
    <div className={detailStyles.healthGrid}>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Status</span>
        <span className={detailStyles.healthValue}>
          <OnlineBadge isOnline={health.is_online} />
        </span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Activity level</span>
        <span className={detailStyles.healthValue}>
          <ActivityBadge level={health.activity_level} />
        </span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Last seen</span>
        <span className={detailStyles.healthValue}>{formatDateTime(health.last_seen_at)}</span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>First active</span>
        <span className={detailStyles.healthValue}>{formatDateTime(health.first_active_at)}</span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Signal strength</span>
        <span className={detailStyles.healthValue}>
          {health.signal_strength != null ? `${health.signal_strength} dBm` : '—'}
        </span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Battery level</span>
        <span className={detailStyles.healthValue}>
          {health.battery_level != null ? `${health.battery_level}%` : '—'}
        </span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Updated</span>
        <span className={detailStyles.healthValue}>{formatDateTime(health.updated_at)}</span>
      </div>
    </div>
  );
}

function DeviceDetail() {
  const { id } = useParams();
  const { data: devices = [], isLoading: devicesLoading } = useDevices();
  const { data: health, isLoading: healthLoading, isError: healthError } = useDeviceHealth(id);

  const device = devices.find((d) => String(d.id) === String(id));

  return (
    <div>
      <div className={styles.pageHeader}>
        <Link to="/app/devices" className={styles.link}>← Devices</Link>
        <h1 style={{ margin: '0 0 0 1rem', fontSize: '1.5rem', fontWeight: 700, color: '#111827' }}>
          {devicesLoading ? 'Loading…' : (device?.name || `Device #${id}`)}
        </h1>
      </div>

      {device && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Device info</h2>
          <div className={detailStyles.infoGrid}>
            <div className={detailStyles.infoItem}>
              <span className={detailStyles.infoLabel}>Serial number</span>
              <span className={`${detailStyles.infoValue} ${styles.mono}`}>{device.serial_number}</span>
            </div>
            <div className={detailStyles.infoItem}>
              <span className={detailStyles.infoLabel}>Device type</span>
              <span className={detailStyles.infoValue}>{device.device_type_name || '—'}</span>
            </div>
            <div className={detailStyles.infoItem}>
              <span className={detailStyles.infoLabel}>Site</span>
              <span className={detailStyles.infoValue}>{device.site_name || '—'}</span>
            </div>
            <div className={detailStyles.infoItem}>
              <span className={detailStyles.infoLabel}>Approval status</span>
              <span className={detailStyles.infoValue}>{device.status}</span>
            </div>
          </div>
        </section>
      )}

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Health</h2>
        {healthLoading && <p className={styles.loading}>Loading health data…</p>}
        {!healthLoading && healthError && (
          <p className={styles.empty}>No health data received yet — this device has not sent any telemetry.</p>
        )}
        {!healthLoading && !healthError && health && <HealthCard health={health} />}
      </section>
    </div>
  );
}

export default DeviceDetail;
