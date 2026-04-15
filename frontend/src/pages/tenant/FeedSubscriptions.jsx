/**
 * Feed Subscriptions — Tenant Admin page.
 *
 * Top section: read-only list of system-scope providers (polled globally,
 * no subscription required — tenants can browse channels and copy IDs for rules).
 *
 * Bottom section: this tenant's subscriptions to tenant-scope providers
 * (each requires credentials entered by the Tenant Admin).
 *
 * Ref: SPEC.md § Feature: Feed Providers — Tenant-scope feeds
 */
import { useState } from 'react';
import {
  useCreateFeedSubscription,
  useDeleteFeedSubscription,
  useFeedProviderChannels,
  useFeedProviders,
  useFeedSubscriptions,
  useUpdateFeedSubscription,
} from '../../hooks/useFeeds';
import styles from '../admin/AdminPage.module.css';

// ---------------------------------------------------------------------------
// System feed panel — read-only channel browser for scope=system providers
// ---------------------------------------------------------------------------

function SystemChannelTable({ providerId }) {
  const { data, isLoading, isError } = useFeedProviderChannels(providerId);
  const channels = Array.isArray(data) ? data : (data?.results ?? []);

  if (isLoading) return <p className={styles.loading}>Loading channels…</p>;
  if (isError) return <p className={styles.error}>Failed to load channels.</p>;
  if (!channels.length)
    return <p className={styles.empty}>No channels yet — data will appear after the first poll.</p>;

  return (
    <table className={styles.table} style={{ marginTop: '0.75rem' }}>
      <thead>
        <tr>
          <th>Channel ID</th>
          <th>Key</th>
          <th>Label</th>
          <th>Unit</th>
          <th>Dimension</th>
          <th>Latest value</th>
        </tr>
      </thead>
      <tbody>
        {channels.map((ch) => (
          <tr key={ch.id}>
            <td className={styles.mono}>{ch.id}</td>
            <td className={styles.mono}>{ch.key}</td>
            <td>{ch.label}</td>
            <td className={styles.mono}>{ch.unit || '—'}</td>
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

function SystemFeedsSection({ providers }) {
  const [expandedId, setExpandedId] = useState(null);

  if (!providers.length) return null;

  return (
    <div style={{ marginBottom: '2rem' }}>
      <h2 className={styles.sectionTitle} style={{ marginBottom: '0.25rem' }}>
        Available system feeds
      </h2>
      <p style={{ margin: '0 0 1rem', fontSize: '0.875rem', color: '#6B7280' }}>
        These feeds are polled globally — no subscription needed. Use the channel IDs
        below when building rules.
      </p>
      {providers.map((p) => (
        <div key={p.id} className={styles.section}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{ flex: 1 }}>
              <span className={styles.sectionTitle} style={{ display: 'inline' }}>{p.name}</span>
              {p.description && (
                <span style={{ marginLeft: '0.75rem', fontSize: '0.875rem', color: '#6B7280' }}>
                  {p.description}
                </span>
              )}
            </div>
            <button
              className={styles.secondaryButton}
              onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
            >
              {expandedId === p.id ? 'Hide channels' : 'View channels'}
            </button>
          </div>
          {expandedId === p.id && <SystemChannelTable providerId={p.id} />}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------

const EMPTY_FORM = {
  provider: '',
  credentials: '{}',
  subscribed_channel_ids: '',
  is_active: true,
};

// ---------------------------------------------------------------------------
// Subscription form (create / edit)
// ---------------------------------------------------------------------------

function SubscriptionForm({ initial, tenantProviders, onSave, onCancel, saving, error }) {
  const [form, setForm] = useState(
    initial
      ? {
          provider: initial.provider,
          credentials: JSON.stringify(initial.credentials ?? {}, null, 2),
          subscribed_channel_ids: (initial.subscribed_channel_ids ?? []).join(', '),
          is_active: initial.is_active ?? true,
        }
      : EMPTY_FORM
  );

  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    let credentials = {};
    try {
      credentials = JSON.parse(form.credentials || '{}');
    } catch {
      return;
    }
    const channelIds = form.subscribed_channel_ids
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => !isNaN(n));
    onSave({
      provider: Number(form.provider),
      credentials,
      subscribed_channel_ids: channelIds,
      is_active: form.is_active,
    });
  };

  return (
    <form onSubmit={handleSubmit} className={styles.form}>
      <div className={styles.field}>
        <label className={styles.label}>Provider</label>
        <select
          className={styles.input}
          value={form.provider}
          onChange={(e) => set('provider', e.target.value)}
          required
          disabled={!!initial}
        >
          <option value="">— select a provider —</option>
          {tenantProviders.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Credentials (JSON)</label>
        <textarea
          className={styles.input}
          style={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}
          value={form.credentials}
          onChange={(e) => set('credentials', e.target.value)}
          rows={4}
          placeholder='{"api_key": "your-key-here"}'
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Subscribed channel IDs (comma-separated, leave blank for all)</label>
        <input
          className={styles.input}
          value={form.subscribed_channel_ids}
          onChange={(e) => set('subscribed_channel_ids', e.target.value)}
          placeholder="e.g. 3, 7, 12"
        />
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

function FeedSubscriptions() {
  const { data: subsData, isLoading, isError } = useFeedSubscriptions();
  const { data: providersData } = useFeedProviders();
  const createMutation = useCreateFeedSubscription();
  const updateMutation = useUpdateFeedSubscription();
  const deleteMutation = useDeleteFeedSubscription();

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formError, setFormError] = useState('');

  const subs = Array.isArray(subsData) ? subsData : (subsData?.results ?? []);
  const allProviders = Array.isArray(providersData)
    ? providersData
    : (providersData?.results ?? []);
  const systemProviders = allProviders.filter((p) => p.scope === 'system');
  const tenantProviders = allProviders.filter((p) => p.scope === 'tenant');

  const handleCreate = (formData) => {
    setFormError('');
    createMutation.mutate(formData, {
      onSuccess: () => setCreating(false),
      onError: (err) =>
        setFormError(err.response?.data?.error?.message ?? 'Failed to create subscription.'),
    });
  };

  const handleUpdate = (sub, formData) => {
    setFormError('');
    updateMutation.mutate(
      { id: sub.id, ...formData },
      {
        onSuccess: () => setEditingId(null),
        onError: (err) =>
          setFormError(err.response?.data?.error?.message ?? 'Failed to update subscription.'),
      }
    );
  };

  const handleDelete = (id) => {
    if (!window.confirm('Remove this feed subscription?')) return;
    deleteMutation.mutate(id);
  };

  if (isLoading) return <p className={styles.loading}>Loading feed subscriptions…</p>;
  if (isError) return <p className={styles.error}>Failed to load feed subscriptions.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Feeds</h1>
        {!creating && tenantProviders.length > 0 && (
          <button className={styles.primaryButton} onClick={() => setCreating(true)}>
            + New Subscription
          </button>
        )}
      </div>

      <SystemFeedsSection providers={systemProviders} />

      <h2 className={styles.sectionTitle} style={{ marginBottom: '0.25rem' }}>
        Your subscriptions
      </h2>
      <p style={{ margin: '0 0 1rem', fontSize: '0.875rem', color: '#6B7280' }}>
        Tenant-scope feeds require you to subscribe with your own credentials.
      </p>

      {tenantProviders.length === 0 && (
        <p className={styles.empty} style={{ marginBottom: '1rem' }}>
          No tenant-scope feed providers are available. Contact your That Place Admin to add one.
        </p>
      )}

      {creating && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>New Feed Subscription</h2>
          <SubscriptionForm
            tenantProviders={tenantProviders}
            onSave={handleCreate}
            onCancel={() => { setCreating(false); setFormError(''); }}
            saving={createMutation.isPending}
            error={formError}
          />
        </div>
      )}

      {subs.length === 0 && !creating && (
        <p className={styles.empty}>No feed subscriptions yet.</p>
      )}

      {subs.map((sub) => {
        const provider = allProviders.find((p) => p.id === sub.provider);
        return (
          <div key={sub.id} className={styles.section}>
            {editingId === sub.id ? (
              <>
                <h2 className={styles.sectionTitle}>Edit subscription</h2>
                <SubscriptionForm
                  initial={sub}
                  tenantProviders={tenantProviders}
                  onSave={(data) => handleUpdate(sub, data)}
                  onCancel={() => { setEditingId(null); setFormError(''); }}
                  saving={updateMutation.isPending}
                  error={formError}
                />
              </>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div style={{ flex: 1 }}>
                  <span className={styles.sectionTitle} style={{ display: 'inline' }}>
                    {provider?.name ?? `Provider ${sub.provider}`}
                  </span>
                  {' '}
                  <span className={sub.is_active ? styles.badgeActive : styles.badgeInactive}>
                    {sub.is_active ? 'active' : 'inactive'}
                  </span>
                  {sub.last_poll_status && (
                    <span
                      className={sub.last_poll_status === 'ok' ? styles.badgeActive : styles.badgeInactive}
                      style={{ marginLeft: '0.5rem' }}
                    >
                      {sub.last_poll_status}
                    </span>
                  )}
                  <p style={{ margin: '0.25rem 0 0', fontSize: '0.8125rem', color: '#6B7280' }}>
                    Channel IDs:{' '}
                    {sub.subscribed_channel_ids?.length
                      ? sub.subscribed_channel_ids.join(', ')
                      : 'all'}
                    {sub.last_polled_at && (
                      <> · Last polled: {new Date(sub.last_polled_at).toLocaleString()}</>
                    )}
                  </p>
                </div>
                <button
                  className={styles.secondaryButton}
                  onClick={() => setEditingId(sub.id)}
                >
                  Edit
                </button>
                <button
                  className={styles.dangerButton}
                  onClick={() => handleDelete(sub.id)}
                >
                  Remove
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default FeedSubscriptions;
