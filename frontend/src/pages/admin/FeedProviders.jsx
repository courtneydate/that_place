/**
 * Feed Providers — That Place Admin page.
 *
 * Lists all FeedProviders. ThatPlaceAdmin can create, edit, delete, and
 * view the channels associated with each provider.
 *
 * Ref: SPEC.md § Feature: Feed Providers
 */
import { useState } from 'react';
import {
  useCreateFeedProvider,
  useDeleteFeedProvider,
  useFeedProviderChannels,
  useFeedProviders,
  useUpdateFeedProvider,
} from '../../hooks/useFeeds';
import styles from './AdminPage.module.css';

const AUTH_TYPES = [
  { value: 'none', label: 'None (public)' },
  { value: 'api_key_header', label: 'API Key (Header)' },
  { value: 'bearer_token', label: 'Bearer Token' },
  { value: 'oauth2_client_credentials', label: 'OAuth2 Client Credentials' },
  { value: 'oauth2_password', label: 'OAuth2 Password Grant' },
];

const SCOPES = [
  { value: 'system', label: 'System — shared across all tenants' },
  { value: 'tenant', label: 'Tenant — tenants subscribe with own credentials' },
];

const EMPTY_FORM = {
  slug: '',
  name: '',
  description: '',
  base_url: '',
  auth_type: 'none',
  scope: 'system',
  poll_interval_seconds: 300,
  is_active: true,
  endpoints: [],
};

// ---------------------------------------------------------------------------
// Channel panel (read-only, shown inline when expanded)
// ---------------------------------------------------------------------------

function ChannelPanel({ providerId }) {
  const { data, isLoading, isError } = useFeedProviderChannels(providerId);

  if (isLoading) return <p className={styles.loading}>Loading channels…</p>;
  if (isError) return <p className={styles.error}>Failed to load channels.</p>;

  const channels = Array.isArray(data) ? data : (data?.results ?? []);

  if (!channels.length) return <p className={styles.empty}>No channels yet — channels are created automatically when the provider is polled.</p>;

  return (
    <table className={styles.table} style={{ marginTop: '0.75rem' }}>
      <thead>
        <tr>
          <th>Key</th>
          <th>Label</th>
          <th>Unit</th>
          <th>Type</th>
          <th>Dimension</th>
          <th>Latest reading</th>
        </tr>
      </thead>
      <tbody>
        {channels.map((ch) => (
          <tr key={ch.id}>
            <td className={styles.mono}>{ch.key}</td>
            <td>{ch.label}</td>
            <td className={styles.mono}>{ch.unit || '—'}</td>
            <td>{ch.data_type}</td>
            <td className={styles.mono}>{ch.dimension_value ?? '—'}</td>
            <td className={styles.mono}>
              {ch.latest_reading
                ? `${ch.latest_reading.value} @ ${new Date(ch.latest_reading.timestamp).toLocaleTimeString()}`
                : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// Provider form (create / edit)
// ---------------------------------------------------------------------------

function ProviderForm({ initial, onSave, onCancel, saving, error }) {
  const [form, setForm] = useState(initial ?? EMPTY_FORM);

  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave({
      ...form,
      poll_interval_seconds: Number(form.poll_interval_seconds) || 300,
    });
  };

  return (
    <form onSubmit={handleSubmit} className={styles.form}>
      <div className={styles.inlineFields}>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Name</label>
          <input
            className={styles.input}
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            required
          />
        </div>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Slug</label>
          <input
            className={styles.input}
            value={form.slug}
            onChange={(e) => set('slug', e.target.value)}
            placeholder="aemo-nem-summary"
            required
          />
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Description</label>
        <textarea
          className={styles.input}
          value={form.description}
          onChange={(e) => set('description', e.target.value)}
          rows={2}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Base URL</label>
        <input
          className={styles.input}
          value={form.base_url}
          onChange={(e) => set('base_url', e.target.value)}
          placeholder="https://api.example.com"
          required
        />
      </div>
      <div className={styles.inlineFields}>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Auth type</label>
          <select
            className={styles.input}
            value={form.auth_type}
            onChange={(e) => set('auth_type', e.target.value)}
          >
            {AUTH_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Scope</label>
          <select
            className={styles.input}
            value={form.scope}
            onChange={(e) => set('scope', e.target.value)}
          >
            {SCOPES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
        <div className={styles.field} style={{ width: '140px' }}>
          <label className={styles.label}>Poll interval (s)</label>
          <input
            className={styles.input}
            type="number"
            min={60}
            value={form.poll_interval_seconds}
            onChange={(e) => set('poll_interval_seconds', e.target.value)}
            required
          />
        </div>
      </div>
      <div className={styles.field}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => set('is_active', e.target.checked)}
          />
          <span className={styles.label} style={{ margin: 0 }}>Active</span>
        </label>
      </div>
      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <button type="submit" className={styles.primaryButton} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className={styles.secondaryButton} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function FeedProviders() {
  const { data, isLoading, isError } = useFeedProviders();
  const createMutation = useCreateFeedProvider();
  const updateMutation = useUpdateFeedProvider();
  const deleteMutation = useDeleteFeedProvider();

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [formError, setFormError] = useState('');

  const providers = Array.isArray(data) ? data : (data?.results ?? []);

  const handleCreate = (formData) => {
    setFormError('');
    createMutation.mutate(formData, {
      onSuccess: () => setCreating(false),
      onError: (err) =>
        setFormError(err.response?.data?.error?.message ?? 'Failed to create provider.'),
    });
  };

  const handleUpdate = (formData) => {
    setFormError('');
    updateMutation.mutate(formData, {
      onSuccess: () => setEditingId(null),
      onError: (err) =>
        setFormError(err.response?.data?.error?.message ?? 'Failed to update provider.'),
    });
  };

  const handleDelete = (id) => {
    if (!window.confirm('Delete this feed provider? All channels and readings will be removed.')) return;
    deleteMutation.mutate(id);
  };

  if (isLoading) return <p className={styles.loading}>Loading feed providers…</p>;
  if (isError) return <p className={styles.error}>Failed to load feed providers.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Feed Providers</h1>
        {!creating && (
          <button className={styles.primaryButton} onClick={() => setCreating(true)}>
            + New Provider
          </button>
        )}
      </div>

      {creating && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>New Feed Provider</h2>
          <ProviderForm
            onSave={handleCreate}
            onCancel={() => { setCreating(false); setFormError(''); }}
            saving={createMutation.isPending}
            error={formError}
          />
        </div>
      )}

      {providers.length === 0 && !creating && (
        <p className={styles.empty}>No feed providers yet. Create one to start polling external data feeds.</p>
      )}

      {providers.map((provider) => (
        <div key={provider.id} className={styles.section}>
          {editingId === provider.id ? (
            <>
              <h2 className={styles.sectionTitle}>Edit: {provider.name}</h2>
              <ProviderForm
                initial={provider}
                onSave={(data) => handleUpdate({ id: provider.id, ...data })}
                onCancel={() => { setEditingId(null); setFormError(''); }}
                saving={updateMutation.isPending}
                error={formError}
              />
            </>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
                <div style={{ flex: 1 }}>
                  <span className={styles.sectionTitle} style={{ display: 'inline' }}>
                    {provider.name}
                  </span>
                  {' '}
                  <span className={provider.is_active ? styles.badgeActive : styles.badgeInactive}>
                    {provider.is_active ? 'active' : 'inactive'}
                  </span>
                  {' '}
                  <span className={styles.badgeInactive}>{provider.scope}</span>
                </div>
                <button
                  className={styles.secondaryButton}
                  onClick={() => setExpandedId(expandedId === provider.id ? null : provider.id)}
                >
                  {expandedId === provider.id ? 'Hide channels' : 'Channels'}
                </button>
                <button
                  className={styles.secondaryButton}
                  onClick={() => setEditingId(provider.id)}
                >
                  Edit
                </button>
                <button
                  className={styles.dangerButton}
                  onClick={() => handleDelete(provider.id)}
                >
                  Delete
                </button>
              </div>
              <p className={styles.mono} style={{ margin: '0 0 0.25rem' }}>
                {provider.base_url}
              </p>
              {provider.description && (
                <p style={{ margin: 0, color: '#6B7280', fontSize: '0.875rem' }}>
                  {provider.description}
                </p>
              )}
              <p style={{ margin: '0.25rem 0 0', fontSize: '0.8125rem', color: '#6B7280' }}>
                Auth: {provider.auth_type} · Poll every {provider.poll_interval_seconds}s
              </p>
              {expandedId === provider.id && <ChannelPanel providerId={provider.id} />}
            </>
          )}
        </div>
      ))}
    </div>
  );
}

export default FeedProviders;
