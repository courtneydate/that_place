/**
 * Notification Event Types — That Place Admin page.
 *
 * Lists the NotificationEventType registry and lets an admin edit each
 * event's severity, delivery channels, message template, and active state.
 * Event types are seeded by the backend (a new key needs an emitter in code),
 * so this page edits existing types rather than creating new ones.
 *
 * Ref: SPEC.md § Data Model — NotificationEventType; ROADMAP Sprint 23
 */
import { useState } from 'react';
import {
  useNotificationEventTypes,
  useUpdateNotificationEventType,
} from '../../hooks/useNotificationEventTypes';
import styles from './AdminPage.module.css';

const SEVERITIES = ['info', 'warning', 'critical'];
const CHANNELS = ['in_app', 'email'];

const SEVERITY_BADGE = {
  info: styles.badgeInactive,
  warning: styles.badgeWarning,
  critical: styles.badgeDanger,
};

// ---------------------------------------------------------------------------
// Edit form
// ---------------------------------------------------------------------------

function EventTypeForm({ eventType, onSave, onCancel, saving, error }) {
  const [form, setForm] = useState({
    label: eventType.label,
    description: eventType.description || '',
    severity: eventType.severity,
    default_channels: eventType.default_channels || [],
    message_template: eventType.message_template,
    is_active: eventType.is_active,
  });
  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  const toggleChannel = (channel) =>
    setForm((f) => ({
      ...f,
      default_channels: f.default_channels.includes(channel)
        ? f.default_channels.filter((c) => c !== channel)
        : [...f.default_channels, channel],
    }));

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave(form);
  };

  const placeholders = (eventType.metadata_schema || []).join(', ') || 'none';

  return (
    <form onSubmit={handleSubmit} className={styles.form} style={{ maxWidth: '720px' }}>
      <p className={styles.sectionDesc}>
        Editing <code>{eventType.key}</code> — audience: {eventType.audience}
      </p>
      <div className={styles.field}>
        <label className={styles.label}>Label</label>
        <input
          className={styles.input}
          value={form.label}
          onChange={(e) => set('label', e.target.value)}
          required
        />
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
        <label className={styles.label}>Severity</label>
        <select
          className={styles.input}
          style={{ width: '160px' }}
          value={form.severity}
          onChange={(e) => set('severity', e.target.value)}
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className={styles.field}>
        <span className={styles.label}>Delivery channels</span>
        {CHANNELS.map((channel) => (
          <label key={channel} className={styles.toggleField}>
            <input
              type="checkbox"
              className={styles.checkbox}
              checked={form.default_channels.includes(channel)}
              onChange={() => toggleChannel(channel)}
            />
            <span className={styles.toggleLabelTitle}>{channel}</span>
          </label>
        ))}
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Message template</label>
        <textarea
          className={styles.input}
          value={form.message_template}
          onChange={(e) => set('message_template', e.target.value)}
          rows={3}
          required
        />
        <p className={styles.fieldHint}>
          Placeholders in braces are filled from event data. Available: {placeholders}.
        </p>
      </div>
      <label className={styles.toggleField}>
        <input
          type="checkbox"
          className={styles.checkbox}
          checked={form.is_active}
          onChange={(e) => set('is_active', e.target.checked)}
        />
        <span className={styles.toggleLabelTitle}>Active</span>
      </label>
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

function NotificationEventTypes() {
  const { data, isLoading, isError } = useNotificationEventTypes();
  const updateMutation = useUpdateNotificationEventType();
  const [editingId, setEditingId] = useState(null);
  const [formError, setFormError] = useState('');

  const eventTypes = Array.isArray(data) ? data : (data?.results ?? []);
  const editing = eventTypes.find((et) => et.id === editingId) || null;

  const handleSave = (formData) => {
    setFormError('');
    updateMutation.mutate(
      { id: editingId, ...formData },
      {
        onSuccess: () => setEditingId(null),
        onError: (err) =>
          setFormError(
            err.response?.data?.error?.message
            ?? 'Failed to update event type.',
          ),
      },
    );
  };

  if (isLoading) return <p className={styles.loading}>Loading event types…</p>;
  if (isError) return <p className={styles.error}>Failed to load event types.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Notification Event Types</h1>
      </div>
      <p className={styles.sectionDesc}>
        The registry that turns system and platform events into notifications.
        Edit an event&apos;s severity, delivery channels, and message template.
      </p>

      {editing && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Edit: {editing.label}</h2>
          <EventTypeForm
            eventType={editing}
            onSave={handleSave}
            onCancel={() => { setEditingId(null); setFormError(''); }}
            saving={updateMutation.isPending}
            error={formError}
          />
        </div>
      )}

      {eventTypes.length === 0 && (
        <p className={styles.empty}>No event types registered.</p>
      )}

      {eventTypes.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Key</th>
                <th>Label</th>
                <th>Severity</th>
                <th>Audience</th>
                <th>Channels</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {eventTypes.map((et) => (
                <tr key={et.id}>
                  <td className={styles.mono}>{et.key}</td>
                  <td>{et.label}</td>
                  <td>
                    <span className={SEVERITY_BADGE[et.severity] || styles.badgeInactive}>
                      {et.severity}
                    </span>
                  </td>
                  <td className={styles.mono}>{et.audience}</td>
                  <td className={styles.mono}>
                    {(et.default_channels || []).join(', ') || '—'}
                  </td>
                  <td>
                    <span className={et.is_active ? styles.badgeActive : styles.badgeInactive}>
                      {et.is_active ? 'active' : 'inactive'}
                    </span>
                  </td>
                  <td>
                    <button
                      className={styles.secondaryButton}
                      style={{ padding: '0.375rem 0.75rem' }}
                      onClick={() => { setEditingId(et.id); setFormError(''); }}
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default NotificationEventTypes;
