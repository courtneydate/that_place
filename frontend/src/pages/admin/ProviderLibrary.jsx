/**
 * Provider Library — Fieldmouse Admin page.
 *
 * Lists all 3rd party API providers. FM Admin can create, edit, and delete
 * provider configs including auth schema, endpoints, and available streams.
 * Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import {
  useCreateProvider,
  useDeleteProvider,
  useProviders,
  useUpdateProvider,
} from '../../hooks/useIntegrations';
import styles from './AdminPage.module.css';

const AUTH_TYPES = [
  { value: 'api_key_header', label: 'API Key (Header)' },
  { value: 'api_key_query', label: 'API Key (Query Parameter)' },
  { value: 'bearer_token', label: 'Bearer Token' },
  { value: 'basic_auth', label: 'Basic Auth (Username/Password)' },
  { value: 'oauth2_client_credentials', label: 'OAuth2 Client Credentials' },
  { value: 'oauth2_password', label: 'OAuth2 Password Grant' },
];

const DATA_TYPES = ['numeric', 'boolean', 'string'];

// ---------------------------------------------------------------------------
// Auth param schema editor — list of {key, label, type, required}
// ---------------------------------------------------------------------------

function AuthParamSchemaEditor({ value, onChange, disabled }) {
  /**
   * Edits the auth_param_schema array.
   * Each entry: {key, label, type (text/password), required}
   */
  const handleChange = (i, field, v) =>
    onChange(value.map((item, idx) => (idx === i ? { ...item, [field]: v } : item)));

  return (
    <div>
      {value.map((param, i) => (
        <div key={i} className={styles.inlineFields} style={{ marginBottom: '0.5rem' }}>
          <input
            type="text"
            placeholder="key (e.g. username)"
            value={param.key || ''}
            onChange={(e) => handleChange(i, 'key', e.target.value)}
            className={styles.input}
            disabled={disabled}
          />
          <input
            type="text"
            placeholder="label (e.g. Username)"
            value={param.label || ''}
            onChange={(e) => handleChange(i, 'label', e.target.value)}
            className={styles.input}
            disabled={disabled}
          />
          <select
            value={param.type || 'text'}
            onChange={(e) => handleChange(i, 'type', e.target.value)}
            className={styles.input}
            disabled={disabled}
          >
            <option value="text">text</option>
            <option value="password">password</option>
          </select>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', whiteSpace: 'nowrap' }}>
            <input
              type="checkbox"
              checked={param.required ?? true}
              onChange={(e) => handleChange(i, 'required', e.target.checked)}
              disabled={disabled}
            />
            Required
          </label>
          <button
            type="button"
            className={styles.dangerButton}
            onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            disabled={disabled}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={() => onChange([...value, { key: '', label: '', type: 'text', required: true }])}
        disabled={disabled}
      >
        + Add credential field
      </button>
    </div>
  );
}

AuthParamSchemaEditor.propTypes = {
  value: PropTypes.arrayOf(PropTypes.object).isRequired,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Available streams editor — list of {key, label, unit, data_type, jsonpath}
// ---------------------------------------------------------------------------

function AvailableStreamsEditor({ value, onChange, disabled }) {
  /**
   * Edits the available_streams array.
   * Each entry: {key, label, unit, data_type, jsonpath}
   */
  const handleChange = (i, field, v) =>
    onChange(value.map((s, idx) => (idx === i ? { ...s, [field]: v } : s)));

  return (
    <div>
      {value.map((stream, i) => (
        <div
          key={i}
          style={{
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: '0.6rem',
            marginBottom: '0.5rem',
          }}
        >
          <div className={styles.inlineFields}>
            <input
              type="text"
              placeholder="key (e.g. soil_moisture)"
              value={stream.key || ''}
              onChange={(e) => handleChange(i, 'key', e.target.value)}
              className={styles.input}
              disabled={disabled}
            />
            <input
              type="text"
              placeholder="label (e.g. Soil Moisture)"
              value={stream.label || ''}
              onChange={(e) => handleChange(i, 'label', e.target.value)}
              className={styles.input}
              disabled={disabled}
            />
            <input
              type="text"
              placeholder="unit (e.g. %)"
              value={stream.unit || ''}
              onChange={(e) => handleChange(i, 'unit', e.target.value)}
              className={styles.input}
              disabled={disabled}
            />
            <select
              value={stream.data_type || 'numeric'}
              onChange={(e) => handleChange(i, 'data_type', e.target.value)}
              className={styles.input}
              disabled={disabled}
            >
              {DATA_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button
              type="button"
              className={styles.dangerButton}
              onClick={() => onChange(value.filter((_, idx) => idx !== i))}
              disabled={disabled}
            >
              Remove
            </button>
          </div>
          <div className={styles.field} style={{ marginTop: '0.4rem' }}>
            <input
              type="text"
              placeholder="JSONPath expression (e.g. $.soil_moisture)"
              value={stream.jsonpath || ''}
              onChange={(e) => handleChange(i, 'jsonpath', e.target.value)}
              className={styles.input}
              disabled={disabled}
              style={{ fontFamily: 'monospace' }}
            />
          </div>
        </div>
      ))}
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={() =>
          onChange([...value, { key: '', label: '', unit: '', data_type: 'numeric', jsonpath: '' }])
        }
        disabled={disabled}
      >
        + Add stream
      </button>
    </div>
  );
}

AvailableStreamsEditor.propTypes = {
  value: PropTypes.arrayOf(PropTypes.object).isRequired,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Shared form fields
// ---------------------------------------------------------------------------

const OAUTH2_AUTH_TYPES = ['oauth2_password', 'oauth2_client_credentials'];

const EMPTY_FIELDS = {
  name: '',
  slug: '',
  description: '',
  logo: null,
  base_url: '',
  auth_type: 'api_key_header',
  token_url: '',
  refresh_url: '',
  auth_param_schema: [],
  discovery_path: '',
  discovery_method: 'GET',
  discovery_id_jsonpath: '',
  discovery_name_jsonpath: '',
  detail_path_template: '',
  detail_method: 'GET',
  available_streams: [],
  default_poll_interval_seconds: 300,
  max_requests_per_second: '',
  is_active: true,
};

function fieldsFromProvider(p) {
  return {
    name: p.name || '',
    slug: p.slug || '',
    description: p.description || '',
    logo: null,
    base_url: p.base_url || '',
    auth_type: p.auth_type || 'api_key_header',
    token_url: p.token_url || '',
    refresh_url: p.refresh_url || '',
    auth_param_schema: p.auth_param_schema || [],
    discovery_path: p.discovery_endpoint?.path || '',
    discovery_method: p.discovery_endpoint?.method || 'GET',
    discovery_id_jsonpath: p.discovery_endpoint?.device_id_jsonpath || '',
    discovery_name_jsonpath: p.discovery_endpoint?.device_name_jsonpath || '',
    detail_path_template: p.detail_endpoint?.path_template || '',
    detail_method: p.detail_endpoint?.method || 'GET',
    available_streams: p.available_streams || [],
    default_poll_interval_seconds: p.default_poll_interval_seconds ?? 300,
    max_requests_per_second: p.max_requests_per_second ?? '',
    is_active: p.is_active ?? true,
  };
}

/**
 * Convert a DRF error response body into a human-readable string.
 * Handles:
 *   - {error: {code, message}}           — our standard error format
 *   - {field: ['msg', ...]}              — DRF field-level errors
 *   - {field: {nested_field: ['msg']}}   — nested object errors (e.g. JSONField)
 *   - {field: [{key: ['msg']}, ...]}     — list-of-object errors (e.g. array fields)
 *   - plain strings                      — pass through as-is
 */
function formatApiErrors(data) {
  if (!data) return 'Request failed.';
  if (typeof data === 'string') return data || 'Request failed.';
  if (data.error?.message) return data.error.message;

  function flatten(obj, prefix) {
    const lines = [];
    for (const [key, val] of Object.entries(obj)) {
      const rawLabel = key === 'non_field_errors' ? 'Error' : key.replace(/_/g, ' ');
      const label = prefix ? `${prefix} › ${rawLabel}` : rawLabel;
      if (Array.isArray(val)) {
        // Array of strings — standard DRF field error list
        if (val.length > 0 && typeof val[0] === 'string') {
          lines.push(`${label}: ${val.join(' ')}`);
        } else {
          // Array of objects — e.g. errors on each item in an array field
          val.forEach((item, i) => {
            if (item && typeof item === 'object') {
              lines.push(...flatten(item, `${label}[${i}]`));
            }
          });
        }
      } else if (val && typeof val === 'object') {
        // Nested object — e.g. errors on fields inside a JSONField
        lines.push(...flatten(val, label));
      } else {
        lines.push(`${label}: ${val}`);
      }
    }
    return lines;
  }

  const lines = flatten(data, '');
  return lines.length ? lines.join('\n') : 'Validation failed.';
}

function buildFormData(fields) {
  const fd = new FormData();
  fd.append('name', fields.name.trim());
  fd.append('slug', fields.slug.trim());
  fd.append('description', fields.description.trim());
  // Only append logo when it is an actual File — never send an empty string
  if (fields.logo instanceof File) fd.append('logo', fields.logo);
  fd.append('base_url', fields.base_url.trim());
  fd.append('auth_type', fields.auth_type);
  fd.append('token_url', (fields.token_url || '').trim());
  fd.append('refresh_url', (fields.refresh_url || '').trim());
  fd.append('auth_param_schema', JSON.stringify(fields.auth_param_schema));
  fd.append('discovery_endpoint', JSON.stringify({
    path: fields.discovery_path,
    method: fields.discovery_method,
    device_id_jsonpath: fields.discovery_id_jsonpath,
    device_name_jsonpath: fields.discovery_name_jsonpath || undefined,
  }));
  fd.append('detail_endpoint', JSON.stringify({
    path_template: fields.detail_path_template,
    method: fields.detail_method,
  }));
  fd.append('available_streams', JSON.stringify(fields.available_streams));
  fd.append('default_poll_interval_seconds', String(fields.default_poll_interval_seconds));
  if (fields.max_requests_per_second !== '' && fields.max_requests_per_second !== null) {
    fd.append('max_requests_per_second', String(fields.max_requests_per_second));
  }
  fd.append('is_active', fields.is_active ? 'true' : 'false');
  return fd;
}

function ProviderFormFields({ fields, setFields, disabled }) {
  return (
    <>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label}>Name *</label>
          <input
            type="text"
            value={fields.name}
            onChange={(e) => setFields((f) => ({ ...f, name: e.target.value }))}
            className={styles.input}
            placeholder="e.g. SoilScouts"
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Slug *</label>
          <input
            type="text"
            value={fields.slug}
            onChange={(e) => setFields((f) => ({ ...f, slug: e.target.value }))}
            className={styles.input}
            placeholder="e.g. soilscouts"
            disabled={disabled}
          />
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Description</label>
        <input
          type="text"
          value={fields.description}
          onChange={(e) => setFields((f) => ({ ...f, description: e.target.value }))}
          className={styles.input}
          disabled={disabled}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Logo</label>
        <input
          type="file"
          accept="image/*"
          onChange={(e) => setFields((f) => ({ ...f, logo: e.target.files[0] || null }))}
          className={styles.input}
          disabled={disabled}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Base URL *</label>
        <input
          type="url"
          value={fields.base_url}
          onChange={(e) => setFields((f) => ({ ...f, base_url: e.target.value }))}
          className={styles.input}
          placeholder="https://api.provider.example.com"
          disabled={disabled}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Auth type *</label>
        <select
          value={fields.auth_type}
          onChange={(e) => setFields((f) => ({ ...f, auth_type: e.target.value }))}
          className={styles.input}
          disabled={disabled}
        >
          {AUTH_TYPES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
      </div>

      {OAUTH2_AUTH_TYPES.includes(fields.auth_type) && (
        <>
          <div className={styles.field}>
            <label className={styles.label}>Token URL *</label>
            <input
              type="url"
              value={fields.token_url}
              onChange={(e) => setFields((f) => ({ ...f, token_url: e.target.value }))}
              className={styles.input}
              placeholder="https://api.provider.example.com/auth/token/"
              disabled={disabled}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Refresh URL (if different from Token URL)</label>
            <input
              type="url"
              value={fields.refresh_url}
              onChange={(e) => setFields((f) => ({ ...f, refresh_url: e.target.value }))}
              className={styles.input}
              placeholder="https://api.provider.example.com/auth/token/refresh/"
              disabled={disabled}
            />
          </div>
        </>
      )}

      <div className={styles.field}>
        <p className={styles.label} style={{ marginBottom: '0.4rem' }}>Credential fields (auth param schema)</p>
        <AuthParamSchemaEditor
          value={fields.auth_param_schema}
          onChange={(v) => setFields((f) => ({ ...f, auth_param_schema: v }))}
          disabled={disabled}
        />
      </div>

      <p className={styles.label} style={{ marginTop: '1rem', marginBottom: '0.5rem', fontWeight: 600 }}>
        Discovery endpoint
      </p>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label}>Path</label>
          <input
            type="text"
            value={fields.discovery_path}
            onChange={(e) => setFields((f) => ({ ...f, discovery_path: e.target.value }))}
            className={styles.input}
            placeholder="/api/devices/"
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Method</label>
          <select
            value={fields.discovery_method}
            onChange={(e) => setFields((f) => ({ ...f, discovery_method: e.target.value }))}
            className={styles.input}
            disabled={disabled}
          >
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
        </div>
      </div>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label}>Device ID JSONPath *</label>
          <input
            type="text"
            value={fields.discovery_id_jsonpath}
            onChange={(e) => setFields((f) => ({ ...f, discovery_id_jsonpath: e.target.value }))}
            className={styles.input}
            placeholder="$.results[*].id"
            style={{ fontFamily: 'monospace' }}
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Device name JSONPath (optional)</label>
          <input
            type="text"
            value={fields.discovery_name_jsonpath}
            onChange={(e) => setFields((f) => ({ ...f, discovery_name_jsonpath: e.target.value }))}
            className={styles.input}
            placeholder="$.results[*].name"
            style={{ fontFamily: 'monospace' }}
            disabled={disabled}
          />
        </div>
      </div>

      <p className={styles.label} style={{ marginTop: '1rem', marginBottom: '0.5rem', fontWeight: 600 }}>
        Detail endpoint
      </p>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label}>Path template</label>
          <input
            type="text"
            value={fields.detail_path_template}
            onChange={(e) => setFields((f) => ({ ...f, detail_path_template: e.target.value }))}
            className={styles.input}
            placeholder="/api/devices/{device_id}/readings/"
            style={{ fontFamily: 'monospace' }}
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Method</label>
          <select
            value={fields.detail_method}
            onChange={(e) => setFields((f) => ({ ...f, detail_method: e.target.value }))}
            className={styles.input}
            disabled={disabled}
          >
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
        </div>
      </div>

      <div className={styles.field} style={{ marginTop: '1rem' }}>
        <p className={styles.label} style={{ marginBottom: '0.4rem' }}>Available streams</p>
        <AvailableStreamsEditor
          value={fields.available_streams}
          onChange={(v) => setFields((f) => ({ ...f, available_streams: v }))}
          disabled={disabled}
        />
      </div>

      <div className={styles.inlineFields} style={{ marginTop: '0.75rem' }}>
        <div className={styles.field}>
          <label className={styles.label}>Poll interval (seconds, min 30)</label>
          <input
            type="number"
            min="30"
            value={fields.default_poll_interval_seconds}
            onChange={(e) =>
              setFields((f) => ({ ...f, default_poll_interval_seconds: Number(e.target.value) }))
            }
            className={styles.input}
            disabled={disabled}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Rate limit (requests/second, optional)</label>
          <input
            type="number"
            min="1"
            placeholder="e.g. 5"
            value={fields.max_requests_per_second}
            onChange={(e) =>
              setFields((f) => ({
                ...f,
                max_requests_per_second: e.target.value === '' ? '' : Number(e.target.value),
              }))
            }
            className={styles.input}
            disabled={disabled}
          />
        </div>
        <div className={styles.field} style={{ paddingTop: '1.6rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <input
              type="checkbox"
              checked={fields.is_active}
              onChange={(e) => setFields((f) => ({ ...f, is_active: e.target.checked }))}
              disabled={disabled}
            />
            Active
          </label>
        </div>
      </div>
    </>
  );
}

ProviderFormFields.propTypes = {
  fields: PropTypes.object.isRequired,
  setFields: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};

// ---------------------------------------------------------------------------
// Create form
// ---------------------------------------------------------------------------

function CreateProviderForm({ onDone }) {
  const create = useCreateProvider();
  const [fields, setFields] = useState({ ...EMPTY_FIELDS });
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!fields.name.trim()) { setError('Name is required.'); return; }
    if (!fields.slug.trim()) { setError('Slug is required.'); return; }
    if (!fields.base_url.trim()) { setError('Base URL is required.'); return; }
    if (!/^https?:\/\/.+/.test(fields.base_url.trim())) {
      setError('Base URL must start with http:// or https://');
      return;
    }
    if (OAUTH2_AUTH_TYPES.includes(fields.auth_type) && !fields.token_url.trim()) {
      setError('Token URL is required for OAuth2 auth types.');
      return;
    }
    if (fields.token_url.trim() && !/^https?:\/\/.+/.test(fields.token_url.trim())) {
      setError('Token URL must start with http:// or https://');
      return;
    }
    if (fields.refresh_url.trim() && !/^https?:\/\/.+/.test(fields.refresh_url.trim())) {
      setError('Refresh URL must start with http:// or https://');
      return;
    }
    try {
      await create.mutateAsync(buildFormData(fields));
      onDone();
    } catch (err) {
      setError(formatApiErrors(err.response?.data) || 'Failed to create provider.');
    }
  };

  return (
    <section className={styles.section}>
      <h2>New provider</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <ProviderFormFields fields={fields} setFields={setFields} disabled={create.isPending} />
        <div className={styles.actions}>
          <button type="submit" className={styles.primaryButton} disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create provider'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onDone} disabled={create.isPending}>
            Cancel
          </button>
        </div>
        {error && <p className={styles.error} style={{ whiteSpace: 'pre-line' }}>{error}</p>}
      </form>
    </section>
  );
}

CreateProviderForm.propTypes = { onDone: PropTypes.func.isRequired };

// ---------------------------------------------------------------------------
// Edit form
// ---------------------------------------------------------------------------

function EditProviderForm({ provider, onDone }) {
  const update = useUpdateProvider(provider.id);
  const [fields, setFields] = useState(fieldsFromProvider(provider));
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!fields.name.trim()) { setError('Name is required.'); return; }
    if (!fields.base_url.trim()) { setError('Base URL is required.'); return; }
    if (!/^https?:\/\/.+/.test(fields.base_url.trim())) {
      setError('Base URL must start with http:// or https://');
      return;
    }
    if (fields.token_url.trim() && !/^https?:\/\/.+/.test(fields.token_url.trim())) {
      setError('Token URL must start with http:// or https://');
      return;
    }
    if (fields.refresh_url.trim() && !/^https?:\/\/.+/.test(fields.refresh_url.trim())) {
      setError('Refresh URL must start with http:// or https://');
      return;
    }
    try {
      await update.mutateAsync(buildFormData(fields));
      onDone();
    } catch (err) {
      setError(formatApiErrors(err.response?.data) || 'Failed to update provider.');
    }
  };

  return (
    <section className={styles.section}>
      <h2>Edit: {provider.name}</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <ProviderFormFields fields={fields} setFields={setFields} disabled={update.isPending} />
        <div className={styles.actions}>
          <button type="submit" className={styles.primaryButton} disabled={update.isPending}>
            {update.isPending ? 'Saving…' : 'Save changes'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onDone} disabled={update.isPending}>
            Cancel
          </button>
        </div>
        {error && <p className={styles.error} style={{ whiteSpace: 'pre-line' }}>{error}</p>}
      </form>
    </section>
  );
}

EditProviderForm.propTypes = {
  provider: PropTypes.object.isRequired,
  onDone: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function ProviderLibrary() {
  const { data: providers = [], isLoading, isError } = useProviders();
  const deleteProvider = useDeleteProvider();
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [deleteError, setDeleteError] = useState('');

  const editingProvider = editingId != null ? providers.find((p) => p.id === editingId) : null;

  const handleDelete = async (p) => {
    if (!window.confirm(`Delete provider "${p.name}"? This cannot be undone.`)) return;
    setDeleteError('');
    try {
      await deleteProvider.mutateAsync(p.id);
    } catch (err) {
      setDeleteError(formatApiErrors(err.response?.data) || 'Failed to delete provider.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>API Provider Library</h1>
        <button
          className={styles.primaryButton}
          onClick={() => { setShowCreate((v) => !v); setEditingId(null); }}
        >
          {showCreate ? 'Cancel' : '+ New provider'}
        </button>
      </div>

      {deleteError && <p className={styles.error}>{deleteError}</p>}

      {showCreate && <CreateProviderForm onDone={() => setShowCreate(false)} />}
      {editingProvider && (
        <EditProviderForm provider={editingProvider} onDone={() => setEditingId(null)} />
      )}

      <section className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load providers.</p>}
        {!isLoading && !isError && providers.length === 0 && (
          <p className={styles.empty}>No providers yet. Create one to get started.</p>
        )}
        {!isLoading && !isError && providers.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Slug</th>
                <th>Auth type</th>
                <th>Poll interval</th>
                <th>Rate limit</th>
                <th>Streams</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.logo_url && (
                      <img
                        src={p.logo_url}
                        alt=""
                        style={{ height: 20, marginRight: 6, verticalAlign: 'middle' }}
                      />
                    )}
                    {p.name}
                  </td>
                  <td>{p.slug}</td>
                  <td>{AUTH_TYPES.find((a) => a.value === p.auth_type)?.label || p.auth_type}</td>
                  <td>{p.default_poll_interval_seconds}s</td>
                  <td>{p.max_requests_per_second ? `${p.max_requests_per_second}/s` : '—'}</td>
                  <td>{(p.available_streams || []).length}</td>
                  <td>
                    <span style={{ color: p.is_active ? 'var(--success)' : 'var(--text-muted)' }}>
                      {p.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      className={styles.secondaryButton}
                      onClick={() => { setEditingId(p.id); setShowCreate(false); }}
                    >
                      Edit
                    </button>
                    <button
                      className={styles.dangerButton}
                      onClick={() => handleDelete(p)}
                      disabled={deleteProvider.isPending}
                    >
                      Delete
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

export default ProviderLibrary;
