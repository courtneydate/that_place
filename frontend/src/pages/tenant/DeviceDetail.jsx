/**
 * Device detail page — Info, Health, Streams, and Commands tabs.
 *
 * Accessible to all tenant roles. Stream editing and command sending
 * are restricted to Admin and Operator roles.
 * Ref: SPEC.md § Feature: Device Health Monitoring
 * Ref: SPEC.md § Feature: Stream Discovery & Configuration
 * Ref: SPEC.md § Feature: Device Control
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDeviceHealth, useDevices, useUpdateDevice } from '../../hooks/useDevices';
import { useCommandHistory, useSendCommand } from '../../hooks/useDeviceCommands';
import { useDeviceStreams, useUpdateStream } from '../../hooks/useStreams';
import styles from '../admin/AdminPage.module.css';
import detailStyles from './DeviceDetail.module.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ACTIVITY_COLORS = {
  normal: '#22C55E',
  degraded: '#F59E0B',
  critical: '#EF4444',
};

function ActivityBadge({ level }) {
  const color = ACTIVITY_COLORS[level] || '#9CA3AF';
  const label = level ? level.charAt(0).toUpperCase() + level.slice(1) : 'Unknown';
  return <span style={{ color, fontWeight: 600 }}>{label}</span>;
}

ActivityBadge.propTypes = { level: PropTypes.string };

function OnlineBadge({ isOnline }) {
  return (
    <span style={{ color: isOnline ? '#22C55E' : '#6B7280', fontWeight: 600 }}>
      {isOnline ? 'Online' : 'Offline'}
    </span>
  );
}

OnlineBadge.propTypes = { isOnline: PropTypes.bool };

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatValue(value, dataType) {
  if (value === null || value === undefined) return '—';
  if (dataType === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

function TabBar({ active, onChange, canControl }) {
  const tabs = canControl
    ? ['Info', 'Health', 'Streams', 'Commands']
    : ['Info', 'Health', 'Streams'];
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
  canControl: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Info tab
// ---------------------------------------------------------------------------

function InfoTab({ device, canEdit }) {
  const updateDevice = useUpdateDevice();
  const [name, setName] = useState(device.name);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) { setError('Name cannot be blank.'); return; }
    setSaving(true);
    setError('');
    try {
      await updateDevice.mutateAsync({ deviceId: device.id, data: { name: trimmed } });
      setEditing(false);
    } catch {
      setError('Failed to save name.');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setName(device.name);
    setEditing(false);
    setError('');
  };

  return (
    <div className={detailStyles.infoGrid}>
      <div className={detailStyles.infoItem}>
        <span className={detailStyles.infoLabel}>Device name</span>
        {canEdit && editing ? (
          <span className={detailStyles.infoValue} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={styles.input}
              style={{ padding: '0.2rem 0.4rem', fontSize: '0.9rem', width: '16rem' }}
              disabled={saving}
              autoFocus
            />
            <button className={styles.primaryButton} onClick={handleSave} disabled={saving}
              style={{ fontSize: '0.8rem', padding: '0.2rem 0.6rem' }}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button className={styles.secondaryButton} onClick={handleCancel} disabled={saving}
              style={{ fontSize: '0.8rem', padding: '0.2rem 0.6rem' }}>
              Cancel
            </button>
            {error && <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>{error}</span>}
          </span>
        ) : (
          <span className={detailStyles.infoValue} style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            {device.name}
            {canEdit && (
              <button className={styles.secondaryButton} onClick={() => setEditing(true)}
                style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem' }}>
                Rename
              </button>
            )}
          </span>
        )}
      </div>
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
      <div className={detailStyles.infoItem}>
        <span className={detailStyles.infoLabel}>Topic format</span>
        <span className={`${detailStyles.infoValue} ${styles.mono}`}>{device.topic_format}</span>
      </div>
    </div>
  );
}

InfoTab.propTypes = {
  device: PropTypes.object.isRequired,
  canEdit: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Health tab
// ---------------------------------------------------------------------------

function HealthTab({ deviceId }) {
  const { data: health, isLoading, isError } = useDeviceHealth(deviceId);

  if (isLoading) return <p className={styles.loading}>Loading health data…</p>;
  if (isError) return (
    <p className={styles.empty}>No health data received yet — this device has not sent any telemetry.</p>
  );

  return (
    <div className={detailStyles.healthGrid}>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Status</span>
        <span className={detailStyles.healthValue}><OnlineBadge isOnline={health.is_online} /></span>
      </div>
      <div className={detailStyles.healthItem}>
        <span className={detailStyles.healthLabel}>Activity level</span>
        <span className={detailStyles.healthValue}><ActivityBadge level={health.activity_level} /></span>
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

HealthTab.propTypes = { deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired };

// ---------------------------------------------------------------------------
// Stream row — inline editing
// ---------------------------------------------------------------------------

function StreamRow({ stream, canEdit, deviceId }) {
  const updateStream = useUpdateStream(deviceId);
  const [label, setLabel] = useState(stream.label);
  const [unit, setUnit] = useState(stream.unit);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleLabelChange = (e) => { setLabel(e.target.value); setDirty(true); };
  const handleUnitChange = (e) => { setUnit(e.target.value); setDirty(true); };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await updateStream.mutateAsync({
        streamId: stream.id,
        data: { label, unit, display_enabled: stream.display_enabled },
      });
      setDirty(false);
    } catch {
      setError('Save failed.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleDisplay = async () => {
    setSaving(true);
    setError('');
    try {
      await updateStream.mutateAsync({
        streamId: stream.id,
        data: { label, unit, display_enabled: !stream.display_enabled },
      });
    } catch {
      setError('Save failed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className={!stream.display_enabled ? detailStyles.rowDisabled : ''}>
      <td className={styles.mono}>{stream.key}</td>
      <td>
        {canEdit ? (
          <input
            type="text"
            value={label}
            onChange={handleLabelChange}
            className={detailStyles.inlineInput}
            disabled={saving}
          />
        ) : (
          stream.label || <span style={{ color: '#9CA3AF' }}>—</span>
        )}
      </td>
      <td>
        {canEdit ? (
          <input
            type="text"
            value={unit}
            onChange={handleUnitChange}
            className={`${detailStyles.inlineInput} ${detailStyles.unitInput}`}
            placeholder="e.g. °C"
            disabled={saving}
          />
        ) : (
          stream.unit || <span style={{ color: '#9CA3AF' }}>—</span>
        )}
      </td>
      <td>{stream.data_type}</td>
      <td className={styles.mono}>
        {formatValue(stream.latest_value, stream.data_type)}
        {stream.latest_timestamp && (
          <span className={detailStyles.latestTs}>
            {' '}@ {formatDateTime(stream.latest_timestamp)}
          </span>
        )}
      </td>
      <td>
        {canEdit ? (
          <button
            onClick={handleToggleDisplay}
            className={stream.display_enabled ? detailStyles.toggleOn : detailStyles.toggleOff}
            disabled={saving}
            title={stream.display_enabled ? 'Shown on dashboards' : 'Hidden from dashboards'}
          >
            {stream.display_enabled ? 'Enabled' : 'Disabled'}
          </button>
        ) : (
          <span style={{ color: stream.display_enabled ? '#22C55E' : '#6B7280' }}>
            {stream.display_enabled ? 'Enabled' : 'Disabled'}
          </span>
        )}
      </td>
      {canEdit && (
        <td>
          {dirty && (
            <button
              onClick={handleSave}
              className={styles.primaryButton}
              disabled={saving}
              style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          )}
          {error && <span className={styles.error}>{error}</span>}
        </td>
      )}
    </tr>
  );
}

StreamRow.propTypes = {
  stream: PropTypes.object.isRequired,
  canEdit: PropTypes.bool.isRequired,
  deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

// ---------------------------------------------------------------------------
// Streams tab
// ---------------------------------------------------------------------------

function StreamsTab({ deviceId, canEdit }) {
  const { data: streams = [], isLoading, isError } = useDeviceStreams(deviceId);

  if (isLoading) return <p className={styles.loading}>Loading streams…</p>;
  if (isError) return <p className={styles.error}>Failed to load streams.</p>;
  if (streams.length === 0) return (
    <p className={styles.empty}>No streams discovered yet — send telemetry to auto-discover streams.</p>
  );

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Key</th>
          <th>Label</th>
          <th>Unit</th>
          <th>Type</th>
          <th>Latest value</th>
          <th>Dashboard</th>
          {canEdit && <th></th>}
        </tr>
      </thead>
      <tbody>
        {streams.map((stream) => (
          <StreamRow
            key={stream.id}
            stream={stream}
            canEdit={canEdit}
            deviceId={deviceId}
          />
        ))}
      </tbody>
    </table>
  );
}

StreamsTab.propTypes = {
  deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  canEdit: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Commands tab
// ---------------------------------------------------------------------------

const STATUS_COLORS = { sent: '#F59E0B', acknowledged: '#22C55E', timed_out: '#EF4444' };

function CommandStatus({ status: s }) {
  return <span style={{ color: STATUS_COLORS[s] || '#9CA3AF', fontWeight: 600 }}>{s}</span>;
}
CommandStatus.propTypes = { status: PropTypes.string.isRequired };

/**
 * Auto-generates a form from a command's param schema.
 * Renders number/bool/string inputs per param type.
 */
function CommandParamForm({ params: paramDefs, values, onChange }) {
  if (!paramDefs || paramDefs.length === 0) {
    return <p style={{ color: '#6B7280', fontSize: '0.875rem' }}>No parameters required.</p>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {paramDefs.map((p) => {
        const key = p.key;
        const value = key in values ? values[key] : (p.default ?? '');
        if (p.type === 'bool') {
          return (
            <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
              <input
                type="checkbox"
                checked={!!value}
                onChange={(e) => onChange(key, e.target.checked)}
              />
              {p.label || key}
            </label>
          );
        }
        return (
          <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.9rem' }}>
            <span>{p.label || key}{!('default' in p) ? ' *' : ''}</span>
            <input
              type={p.type === 'int' || p.type === 'float' ? 'number' : 'text'}
              value={value}
              min={p.min}
              max={p.max}
              step={p.type === 'float' ? 'any' : undefined}
              onChange={(e) =>
                onChange(key, p.type === 'int' ? parseInt(e.target.value, 10) : p.type === 'float' ? parseFloat(e.target.value) : e.target.value)
              }
              className={styles.input}
              style={{ width: '14rem', padding: '0.3rem 0.5rem', fontSize: '0.875rem' }}
            />
            {p.unit && <span style={{ color: '#6B7280', fontSize: '0.8rem' }}>Unit: {p.unit}</span>}
          </label>
        );
      })}
    </div>
  );
}
CommandParamForm.propTypes = {
  params: PropTypes.array,
  values: PropTypes.object.isRequired,
  onChange: PropTypes.func.isRequired,
};

function CommandPicker({ commands, deviceId }) {
  const [selected, setSelected] = useState(null);
  const [paramValues, setParamValues] = useState({});
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const sendCommand = useSendCommand(deviceId);

  const handleSelect = (cmd) => {
    setSelected(cmd);
    // Pre-fill defaults
    const defaults = {};
    (cmd.params || []).forEach((p) => {
      if ('default' in p) defaults[p.key] = p.default;
    });
    setParamValues(defaults);
    setError('');
    setSuccess('');
  };

  const handleParamChange = (key, value) => {
    setParamValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSend = async () => {
    setError('');
    setSuccess('');
    try {
      await sendCommand.mutateAsync({ commandName: selected.name, params: paramValues });
      setSuccess(`Command "${selected.label || selected.name}" sent.`);
      setSelected(null);
      setParamValues({});
    } catch (e) {
      const msg = e.response?.data?.error?.message || 'Failed to send command.';
      setError(msg);
    }
  };

  if (!commands || commands.length === 0) {
    return <p className={styles.empty}>No commands defined for this device type.</p>;
  }

  return (
    <div style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div>
        <p style={{ fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.9rem' }}>Select command</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          {commands.map((cmd) => (
            <button
              key={cmd.name}
              onClick={() => handleSelect(cmd)}
              className={selected?.name === cmd.name ? styles.primaryButton : styles.secondaryButton}
              style={{ textAlign: 'left', padding: '0.4rem 0.75rem', fontSize: '0.875rem' }}
            >
              {cmd.label || cmd.name}
              {cmd.description && (
                <span style={{ display: 'block', color: '#6B7280', fontSize: '0.75rem', fontWeight: 400 }}>
                  {cmd.description}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {selected && (
        <div style={{ minWidth: '18rem' }}>
          <p style={{ fontWeight: 600, marginBottom: '0.75rem', fontSize: '0.9rem' }}>
            {selected.label || selected.name}
          </p>
          <CommandParamForm
            params={selected.params}
            values={paramValues}
            onChange={handleParamChange}
          />
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', alignItems: 'center' }}>
            <button
              className={styles.primaryButton}
              onClick={handleSend}
              disabled={sendCommand.isPending}
            >
              {sendCommand.isPending ? 'Sending…' : 'Send Command'}
            </button>
            <button
              className={styles.secondaryButton}
              onClick={() => { setSelected(null); setParamValues({}); setError(''); }}
            >
              Cancel
            </button>
          </div>
          {error && <p className={styles.error} style={{ marginTop: '0.5rem' }}>{error}</p>}
          {success && <p style={{ color: '#22C55E', marginTop: '0.5rem', fontSize: '0.875rem' }}>{success}</p>}
        </div>
      )}
    </div>
  );
}
CommandPicker.propTypes = {
  commands: PropTypes.array,
  deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

function CommandHistoryTable({ deviceId }) {
  const { data: logs = [], isLoading, isError } = useCommandHistory(deviceId);

  if (isLoading) return <p className={styles.loading}>Loading command history…</p>;
  if (isError) return <p className={styles.error}>Failed to load command history.</p>;
  if (logs.length === 0) return <p className={styles.empty}>No commands sent yet.</p>;

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Command</th>
          <th>Params</th>
          <th>Sent</th>
          <th>Sent by</th>
          <th>Ack received</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {logs.map((log) => (
          <tr key={log.id}>
            <td className={styles.mono}>{log.command_name}</td>
            <td className={styles.mono} style={{ fontSize: '0.8rem', color: '#6B7280' }}>
              {JSON.stringify(log.params_sent)}
            </td>
            <td>{formatDateTime(log.sent_at)}</td>
            <td>{log.triggered_by_rule ? <em style={{ color: '#6B7280' }}>Rule #{log.triggered_by_rule}</em> : (log.sent_by_email || '—')}</td>
            <td>{log.ack_received_at ? formatDateTime(log.ack_received_at) : '—'}</td>
            <td><CommandStatus status={log.status} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
CommandHistoryTable.propTypes = {
  deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

function CommandsTab({ device, deviceId }) {
  const isLegacy = device?.topic_format === 'legacy_v1';
  const commands = device?.device_type_commands || [];

  return (
    <div>
      {isLegacy && (
        <div className={styles.warning} style={{ marginBottom: '1rem', padding: '0.75rem 1rem', background: '#FEF3C7', borderRadius: '0.375rem', fontSize: '0.875rem', color: '#92400E' }}>
          Commands are not available for legacy v1 devices. Update firmware to That Place v1 to enable commands.
        </div>
      )}
      {!isLegacy && (
        <>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Send Command</h3>
          <CommandPicker commands={commands} deviceId={deviceId} />
          <hr style={{ margin: '1.5rem 0', borderColor: '#E5E7EB' }} />
        </>
      )}
      <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Command History</h3>
      <CommandHistoryTable deviceId={deviceId} />
    </div>
  );
}
CommandsTab.propTypes = {
  device: PropTypes.object,
  deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function DeviceDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';
  const isOperator = user?.tenant_role === 'operator';
  const canControl = isAdmin || isOperator;

  const { data: devices = [], isLoading: devicesLoading } = useDevices();
  const device = devices.find((d) => String(d.id) === String(id));

  const [activeTab, setActiveTab] = useState('Info');

  // device_type_commands is included in the DeviceSerializer response
  const commands = device?.device_type_commands ?? [];

  return (
    <div>
      <div className={styles.pageHeader}>
        <Link to="/app/devices" className={styles.link}>← Devices</Link>
        <h1 style={{ margin: '0 0 0 1rem', fontSize: '1.5rem', fontWeight: 700, color: '#111827' }}>
          {devicesLoading ? 'Loading…' : (device?.name || `Device #${id}`)}
        </h1>
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} canControl={canControl} />

      <section className={styles.section}>
        {activeTab === 'Info' && device && <InfoTab device={device} canEdit={isAdmin} />}
        {activeTab === 'Info' && !device && !devicesLoading && (
          <p className={styles.empty}>Device not found.</p>
        )}
        {activeTab === 'Health' && <HealthTab deviceId={id} />}
        {activeTab === 'Streams' && <StreamsTab deviceId={id} canEdit={isAdmin} />}
        {activeTab === 'Commands' && canControl && (
          <CommandsTab
            device={device ? { ...device, device_type_commands: commands } : null}
            deviceId={id}
          />
        )}
      </section>
    </div>
  );
}

export default DeviceDetail;
