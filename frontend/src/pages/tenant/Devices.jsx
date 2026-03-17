/**
 * Devices — tenant device list and registration form.
 *
 * All tenant users can see the device list with status badges.
 * Tenant Admins can register new devices and delete existing ones.
 * Ref: SPEC.md § Feature: Device Registration & Approval
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDevices, useCreateDevice, useDeleteDevice } from '../../hooks/useDevices';
import { useDeviceTypes } from '../../hooks/useDeviceTypes';
import { useSites } from '../../hooks/useSites';
import styles from '../admin/AdminPage.module.css';

const STATUS_LABELS = {
  pending: 'Pending',
  active: 'Active',
  rejected: 'Rejected',
  deactivated: 'Deactivated',
};

const STATUS_COLORS = {
  pending: 'var(--warning)',
  active: 'var(--success)',
  rejected: 'var(--danger)',
  deactivated: 'var(--text-muted)',
};

function StatusBadge({ status }) {
  return (
    <span style={{ color: STATUS_COLORS[status] || 'inherit', fontWeight: 600 }}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

StatusBadge.propTypes = {
  status: PropTypes.string.isRequired,
};

const ACTIVITY_COLORS = {
  normal: '#22C55E',
  degraded: '#F59E0B',
  critical: '#EF4444',
};

function ActivityBadge({ level, isOnline }) {
  if (!isOnline) {
    return <span style={{ color: '#6B7280', fontWeight: 600 }}>Offline</span>;
  }
  if (!level) {
    return <span style={{ color: '#9CA3AF' }}>—</span>;
  }
  const color = ACTIVITY_COLORS[level] || '#9CA3AF';
  const label = level.charAt(0).toUpperCase() + level.slice(1);
  return <span style={{ color, fontWeight: 600 }}>{label}</span>;
}

ActivityBadge.propTypes = {
  level: PropTypes.string,
  isOnline: PropTypes.bool,
};

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

// ---------------------------------------------------------------------------
// Registration form
// ---------------------------------------------------------------------------

function RegisterDeviceForm({ onDone }) {
  const createDevice = useCreateDevice();
  const { data: sites = [] } = useSites();
  const { data: deviceTypes = [] } = useDeviceTypes();

  const [name, setName] = useState('');
  const [serialNumber, setSerialNumber] = useState('');
  const [siteId, setSiteId] = useState('');
  const [deviceTypeId, setDeviceTypeId] = useState('');
  const [thresholdOverride, setThresholdOverride] = useState('');
  const [error, setError] = useState('');

  const activeDeviceTypes = deviceTypes.filter((dt) => dt.is_active);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) { setError('Device name is required.'); return; }
    if (!serialNumber.trim()) { setError('Serial number is required.'); return; }
    if (!siteId) { setError('Please select a site.'); return; }
    if (!deviceTypeId) { setError('Please select a device type.'); return; }
    try {
      const payload = {
        name: name.trim(),
        serial_number: serialNumber.trim(),
        site: parseInt(siteId, 10),
        device_type: parseInt(deviceTypeId, 10),
      };
      if (thresholdOverride !== '') {
        payload.offline_threshold_override_minutes = parseInt(thresholdOverride, 10);
      }
      await createDevice.mutateAsync(payload);
      onDone();
    } catch (err) {
      const data = err.response?.data;
      const msg =
        data?.serial_number?.[0] ||
        data?.error?.message ||
        'Failed to register device.';
      setError(msg);
    }
  };

  return (
    <section className={styles.section}>
      <h2>Register new device</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <div className={styles.inlineFields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-name">Device name *</label>
            <input
              id="reg-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={styles.input}
              placeholder="e.g. Pump Station Scout 1"
              disabled={createDevice.isPending}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-serial">Serial number *</label>
            <input
              id="reg-serial"
              type="text"
              value={serialNumber}
              onChange={(e) => setSerialNumber(e.target.value)}
              className={styles.input}
              placeholder="e.g. PSS-00123"
              disabled={createDevice.isPending}
            />
          </div>
        </div>
        <div className={styles.inlineFields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-site">Site *</label>
            <select
              id="reg-site"
              value={siteId}
              onChange={(e) => setSiteId(e.target.value)}
              className={styles.input}
              disabled={createDevice.isPending}
            >
              <option value="">— Select site —</option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>{site.name}</option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-type">Device type *</label>
            <select
              id="reg-type"
              value={deviceTypeId}
              onChange={(e) => setDeviceTypeId(e.target.value)}
              className={styles.input}
              disabled={createDevice.isPending}
            >
              <option value="">— Select device type —</option>
              {activeDeviceTypes.map((dt) => (
                <option key={dt.id} value={dt.id}>{dt.name}</option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-threshold">
              Offline threshold override (min)
            </label>
            <input
              id="reg-threshold"
              type="number"
              min="1"
              value={thresholdOverride}
              onChange={(e) => setThresholdOverride(e.target.value)}
              className={styles.input}
              placeholder="Optional — uses device type default"
              disabled={createDevice.isPending}
            />
          </div>
        </div>
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={createDevice.isPending}
          >
            {createDevice.isPending ? 'Registering…' : 'Register device'}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onDone}
            disabled={createDevice.isPending}
          >
            Cancel
          </button>
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </section>
  );
}

RegisterDeviceForm.propTypes = {
  onDone: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function Devices() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  const { data: devices = [], isLoading, isError } = useDevices();
  const deleteDevice = useDeleteDevice();

  const [showRegisterForm, setShowRegisterForm] = useState(false);

  const handleDelete = async (deviceId, deviceName) => {
    if (!window.confirm(`Delete device "${deviceName}"? This cannot be undone.`)) return;
    try {
      await deleteDevice.mutateAsync(deviceId);
    } catch (err) {
      alert(err.response?.data?.error?.message || 'Failed to delete device.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Devices</h1>
        {isAdmin && (
          <button
            className={styles.primaryButton}
            onClick={() => setShowRegisterForm((v) => !v)}
          >
            {showRegisterForm ? 'Cancel' : '+ Register device'}
          </button>
        )}
      </div>

      {isAdmin && showRegisterForm && (
        <RegisterDeviceForm onDone={() => setShowRegisterForm(false)} />
      )}

      <section className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load devices.</p>}
        {!isLoading && !isError && devices.length === 0 && (
          <p className={styles.empty}>No devices registered yet.</p>
        )}
        {!isLoading && !isError && devices.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Serial number</th>
                <th>Site</th>
                <th>Device type</th>
                <th>Status</th>
                <th>Health</th>
                <th>Registered</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr key={device.id}>
                  <td>
                    <Link to={`/app/devices/${device.id}`} className={styles.link}>
                      {device.name}
                    </Link>
                  </td>
                  <td>{device.serial_number}</td>
                  <td>{device.site_name || '—'}</td>
                  <td>{device.device_type_name || '—'}</td>
                  <td><StatusBadge status={device.status} /></td>
                  <td>
                    <ActivityBadge
                      level={device.health?.activity_level}
                      isOnline={device.health?.is_online}
                    />
                  </td>
                  <td>{formatDate(device.created_at)}</td>
                  {isAdmin && (
                    <td>
                      <button
                        className={styles.dangerButton}
                        onClick={() => handleDelete(device.id, device.name)}
                        disabled={deleteDevice.isPending}
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
      </section>
    </div>
  );
}

export default Devices;
