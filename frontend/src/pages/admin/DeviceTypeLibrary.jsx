/**
 * Device Type Library — Fieldmouse Admin page.
 *
 * Lists all device types. FM Admin can create and edit types including
 * stream type definitions and command schemas.
 * Ref: SPEC.md § Feature: Device Type Library
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import { useDeviceTypes, useCreateDeviceType, useUpdateDeviceType } from '../../hooks/useDeviceTypes';
import styles from './AdminPage.module.css';

const CONNECTION_TYPE_LABELS = {
  mqtt: 'MQTT (push)',
  api: '3rd Party API (poll)',
};

const DATA_TYPE_OPTIONS = ['numeric', 'boolean', 'string'];

// ---------------------------------------------------------------------------
// Stream definition sub-form (list of {key, label, data_type, unit})
// ---------------------------------------------------------------------------

function StreamDefinitionsEditor({ value, onChange, disabled }) {
  /**
   * Inline editor for stream_type_definitions array.
   * Each entry: {key, label, data_type, unit}
   */
  const handleChange = (index, field, fieldValue) => {
    const updated = value.map((item, i) =>
      i === index ? { ...item, [field]: fieldValue } : item
    );
    onChange(updated);
  };

  const handleAdd = () => {
    onChange([...value, { key: '', label: '', data_type: 'numeric', unit: '' }]);
  };

  const handleRemove = (index) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <div>
      {value.map((stream, index) => (
        <div key={index} className={styles.inlineFields} style={{ marginBottom: '0.5rem' }}>
          <input
            type="text"
            placeholder="key (e.g. temperature)"
            value={stream.key}
            onChange={(e) => handleChange(index, 'key', e.target.value)}
            className={styles.input}
            disabled={disabled}
          />
          <input
            type="text"
            placeholder="label"
            value={stream.label}
            onChange={(e) => handleChange(index, 'label', e.target.value)}
            className={styles.input}
            disabled={disabled}
          />
          <select
            value={stream.data_type}
            onChange={(e) => handleChange(index, 'data_type', e.target.value)}
            className={styles.input}
            disabled={disabled}
          >
            {DATA_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="unit (e.g. °C)"
            value={stream.unit}
            onChange={(e) => handleChange(index, 'unit', e.target.value)}
            className={styles.input}
            disabled={disabled}
          />
          <button
            type="button"
            className={styles.dangerButton}
            onClick={() => handleRemove(index)}
            disabled={disabled}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={handleAdd}
        disabled={disabled}
      >
        + Add stream type
      </button>
    </div>
  );
}

StreamDefinitionsEditor.propTypes = {
  value: PropTypes.arrayOf(PropTypes.object).isRequired,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Command sub-form (list of {name, label, description})
// ---------------------------------------------------------------------------

function CommandsEditor({ value, onChange, disabled }) {
  /**
   * Inline editor for commands array.
   * Each entry: {name, label, description}
   * Params are entered as JSON for now (complex nested structure).
   */
  const handleChange = (index, field, fieldValue) => {
    const updated = value.map((item, i) =>
      i === index ? { ...item, [field]: fieldValue } : item
    );
    onChange(updated);
  };

  const handleAdd = () => {
    onChange([...value, { name: '', label: '', description: '', params: [] }]);
  };

  const handleRemove = (index) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <div>
      {value.map((cmd, index) => (
        <div key={index} style={{ border: '1px solid var(--border)', borderRadius: 4, padding: '0.75rem', marginBottom: '0.5rem' }}>
          <div className={styles.inlineFields}>
            <input
              type="text"
              placeholder="name (e.g. set_relay)"
              value={cmd.name}
              onChange={(e) => handleChange(index, 'name', e.target.value)}
              className={styles.input}
              disabled={disabled}
            />
            <input
              type="text"
              placeholder="label (e.g. Set Relay)"
              value={cmd.label}
              onChange={(e) => handleChange(index, 'label', e.target.value)}
              className={styles.input}
              disabled={disabled}
            />
            <button
              type="button"
              className={styles.dangerButton}
              onClick={() => handleRemove(index)}
              disabled={disabled}
            >
              Remove
            </button>
          </div>
          <div className={styles.field} style={{ marginTop: '0.5rem' }}>
            <input
              type="text"
              placeholder="description (optional)"
              value={cmd.description}
              onChange={(e) => handleChange(index, 'description', e.target.value)}
              className={styles.input}
              disabled={disabled}
            />
          </div>
        </div>
      ))}
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={handleAdd}
        disabled={disabled}
      >
        + Add command
      </button>
    </div>
  );
}

CommandsEditor.propTypes = {
  value: PropTypes.arrayOf(PropTypes.object).isRequired,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Shared form fields used by both Create and Edit forms
// ---------------------------------------------------------------------------

function DeviceTypeFormFields({ fields, setFields, disabled }) {
  return (
    <>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`dt-name-${fields._id}`}>Name *</label>
          <input
            id={`dt-name-${fields._id}`}
            type="text"
            value={fields.name}
            onChange={(e) => setFields((f) => ({ ...f, name: e.target.value }))}
            className={styles.input}
            placeholder="e.g. Weather Station"
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`dt-slug-${fields._id}`}>Slug *</label>
          <input
            id={`dt-slug-${fields._id}`}
            type="text"
            value={fields.slug}
            onChange={(e) => setFields((f) => ({ ...f, slug: e.target.value }))}
            className={styles.input}
            placeholder="e.g. weather-station"
            disabled={disabled}
          />
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={`dt-desc-${fields._id}`}>Description</label>
        <input
          id={`dt-desc-${fields._id}`}
          type="text"
          value={fields.description}
          onChange={(e) => setFields((f) => ({ ...f, description: e.target.value }))}
          className={styles.input}
          disabled={disabled}
        />
      </div>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`dt-conn-${fields._id}`}>Connection type</label>
          <select
            id={`dt-conn-${fields._id}`}
            value={fields.connection_type}
            onChange={(e) => setFields((f) => ({ ...f, connection_type: e.target.value }))}
            className={styles.input}
            disabled={disabled}
          >
            <option value="mqtt">MQTT (push)</option>
            <option value="api">3rd Party API (poll)</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`dt-threshold-${fields._id}`}>
            Offline threshold (min)
          </label>
          <input
            id={`dt-threshold-${fields._id}`}
            type="number"
            min="1"
            value={fields.default_offline_threshold_minutes}
            onChange={(e) =>
              setFields((f) => ({ ...f, default_offline_threshold_minutes: e.target.value }))
            }
            className={styles.input}
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`dt-ack-${fields._id}`}>
            Command ack timeout (sec)
          </label>
          <input
            id={`dt-ack-${fields._id}`}
            type="number"
            min="1"
            value={fields.command_ack_timeout_seconds}
            onChange={(e) =>
              setFields((f) => ({ ...f, command_ack_timeout_seconds: e.target.value }))
            }
            className={styles.input}
            disabled={disabled}
          />
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label}>
          <input
            type="checkbox"
            checked={fields.is_active}
            onChange={(e) => setFields((f) => ({ ...f, is_active: e.target.checked }))}
            disabled={disabled}
            style={{ marginRight: '0.5rem' }}
          />
          Active
        </label>
      </div>
      <div className={styles.field}>
        <p className={styles.label} style={{ marginBottom: '0.5rem' }}>Stream type definitions</p>
        <StreamDefinitionsEditor
          value={fields.stream_type_definitions}
          onChange={(v) => setFields((f) => ({ ...f, stream_type_definitions: v }))}
          disabled={disabled}
        />
      </div>
      <div className={styles.field}>
        <p className={styles.label} style={{ marginBottom: '0.5rem' }}>Commands</p>
        <CommandsEditor
          value={fields.commands}
          onChange={(v) => setFields((f) => ({ ...f, commands: v }))}
          disabled={disabled}
        />
      </div>
    </>
  );
}

DeviceTypeFormFields.propTypes = {
  fields: PropTypes.object.isRequired,
  setFields: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Create form
// ---------------------------------------------------------------------------

function CreateDeviceTypeForm({ onDone }) {
  const createDeviceType = useCreateDeviceType();
  const [fields, setFields] = useState({
    _id: 'create',
    name: '',
    slug: '',
    description: '',
    connection_type: 'mqtt',
    default_offline_threshold_minutes: 10,
    command_ack_timeout_seconds: 30,
    is_active: true,
    stream_type_definitions: [],
    commands: [],
  });
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!fields.name.trim()) { setError('Name is required.'); return; }
    if (!fields.slug.trim()) { setError('Slug is required.'); return; }
    try {
      // eslint-disable-next-line no-unused-vars
      const { _id, ...payload } = fields;
      await createDeviceType.mutateAsync(payload);
      onDone();
    } catch (err) {
      setError(err.response?.data?.slug?.[0] || err.response?.data?.error?.message || 'Failed to create device type.');
    }
  };

  return (
    <section className={styles.section}>
      <h2>New device type</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <DeviceTypeFormFields
          fields={fields}
          setFields={setFields}
          disabled={createDeviceType.isPending}
        />
        <div className={styles.actions}>
          <button type="submit" className={styles.primaryButton} disabled={createDeviceType.isPending}>
            {createDeviceType.isPending ? 'Creating…' : 'Create device type'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onDone} disabled={createDeviceType.isPending}>
            Cancel
          </button>
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </section>
  );
}

CreateDeviceTypeForm.propTypes = {
  onDone: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Edit form
// ---------------------------------------------------------------------------

function EditDeviceTypeForm({ deviceType, onDone }) {
  const updateDeviceType = useUpdateDeviceType(deviceType.id);
  const [fields, setFields] = useState({
    _id: deviceType.id,
    name: deviceType.name || '',
    slug: deviceType.slug || '',
    description: deviceType.description || '',
    connection_type: deviceType.connection_type || 'mqtt',
    default_offline_threshold_minutes: deviceType.default_offline_threshold_minutes ?? 10,
    command_ack_timeout_seconds: deviceType.command_ack_timeout_seconds ?? 30,
    is_active: deviceType.is_active ?? true,
    stream_type_definitions: deviceType.stream_type_definitions || [],
    commands: deviceType.commands || [],
  });
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!fields.name.trim()) { setError('Name is required.'); return; }
    try {
      // eslint-disable-next-line no-unused-vars
      const { _id, ...payload } = fields;
      await updateDeviceType.mutateAsync(payload);
      onDone();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Failed to update device type.');
    }
  };

  return (
    <section className={styles.section}>
      <h2>Edit: {deviceType.name}</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <DeviceTypeFormFields
          fields={fields}
          setFields={setFields}
          disabled={updateDeviceType.isPending}
        />
        <div className={styles.actions}>
          <button type="submit" className={styles.primaryButton} disabled={updateDeviceType.isPending}>
            {updateDeviceType.isPending ? 'Saving…' : 'Save changes'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onDone} disabled={updateDeviceType.isPending}>
            Cancel
          </button>
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </section>
  );
}

EditDeviceTypeForm.propTypes = {
  deviceType: PropTypes.object.isRequired,
  onDone: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function DeviceTypeLibrary() {
  const { data: deviceTypes = [], isLoading, isError } = useDeviceTypes();
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const editingDeviceType = editingId != null
    ? deviceTypes.find((dt) => dt.id === editingId)
    : null;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Device Type Library</h1>
        <button
          className={styles.primaryButton}
          onClick={() => { setShowCreate((v) => !v); setEditingId(null); }}
        >
          {showCreate ? 'Cancel' : '+ New device type'}
        </button>
      </div>

      {showCreate && (
        <CreateDeviceTypeForm onDone={() => setShowCreate(false)} />
      )}

      {editingDeviceType && (
        <EditDeviceTypeForm
          deviceType={editingDeviceType}
          onDone={() => setEditingId(null)}
        />
      )}

      <section className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load device types.</p>}
        {!isLoading && !isError && deviceTypes.length === 0 && (
          <p className={styles.empty}>No device types yet.</p>
        )}
        {!isLoading && !isError && deviceTypes.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Slug</th>
                <th>Connection</th>
                <th>Offline threshold</th>
                <th>Streams</th>
                <th>Commands</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {deviceTypes.map((dt) => (
                <tr key={dt.id}>
                  <td>{dt.name}</td>
                  <td>{dt.slug}</td>
                  <td>{CONNECTION_TYPE_LABELS[dt.connection_type] || dt.connection_type}</td>
                  <td>{dt.default_offline_threshold_minutes} min</td>
                  <td>{(dt.stream_type_definitions || []).length}</td>
                  <td>{(dt.commands || []).length}</td>
                  <td>
                    <span style={{ color: dt.is_active ? 'var(--success)' : 'var(--text-muted)' }}>
                      {dt.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <button
                      className={styles.secondaryButton}
                      onClick={() => { setEditingId(dt.id); setShowCreate(false); }}
                    >
                      Edit
                    </button>
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

export default DeviceTypeLibrary;
