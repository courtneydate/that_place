/**
 * Pending Devices — That Place Admin approval queue.
 *
 * Shows all devices with status=pending across all tenants.
 * FM Admin can approve or reject each device.
 * Ref: SPEC.md § Feature: Device Registration & Approval
 */
import { useDevices, useApproveDevice, useRejectDevice } from '../../hooks/useDevices';
import styles from './AdminPage.module.css';

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function PendingDevices() {
  const { data: devices = [], isLoading, isError } = useDevices({ status: 'pending' });
  const approveDevice = useApproveDevice();
  const rejectDevice = useRejectDevice();

  const handleApprove = async (deviceId, deviceName) => {
    if (!window.confirm(`Approve device "${deviceName}"?`)) return;
    try {
      await approveDevice.mutateAsync(deviceId);
    } catch (err) {
      alert(err.response?.data?.error?.message || 'Failed to approve device.');
    }
  };

  const handleReject = async (deviceId, deviceName) => {
    if (!window.confirm(`Reject device "${deviceName}"? This cannot be undone.`)) return;
    try {
      await rejectDevice.mutateAsync(deviceId);
    } catch (err) {
      alert(err.response?.data?.error?.message || 'Failed to reject device.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Pending Device Approvals</h1>
      </div>

      <section className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load pending devices.</p>}
        {!isLoading && !isError && devices.length === 0 && (
          <p className={styles.empty}>No devices awaiting approval.</p>
        )}
        {!isLoading && !isError && devices.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Serial number</th>
                <th>Tenant</th>
                <th>Site</th>
                <th>Device type</th>
                <th>Registered</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr key={device.id}>
                  <td>{device.name}</td>
                  <td>{device.serial_number}</td>
                  <td>{device.tenant_name || '—'}</td>
                  <td>{device.site_name || '—'}</td>
                  <td>{device.device_type_name || '—'}</td>
                  <td>{formatDate(device.created_at)}</td>
                  <td>
                    <div className={styles.actions} style={{ marginTop: 0 }}>
                      <button
                        className={styles.primaryButton}
                        onClick={() => handleApprove(device.id, device.name)}
                        disabled={approveDevice.isPending || rejectDevice.isPending}
                      >
                        Approve
                      </button>
                      <button
                        className={styles.dangerButton}
                        onClick={() => handleReject(device.id, device.name)}
                        disabled={approveDevice.isPending || rejectDevice.isPending}
                      >
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default PendingDevices;
