/**
 * Per-user, per-rule channel opt-out controls (Sprint 26).
 *
 * Each user sees four toggles (In-app, Email, SMS, Push) for the rule they're
 * viewing. Toggling immediately saves the new state via the
 * /my-notification-prefs/ endpoint. The panel hides itself when the user isn't
 * a target of any notify action on the rule (endpoint returns 403).
 *
 * Ref: SPEC.md §8 Phase 5b; ROADMAP Sprint 26
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import {
  useMyRuleNotificationPrefs,
  useSaveMyRuleNotificationPrefs,
} from '../../hooks/useRules';
import styles from '../admin/AdminPage.module.css';

const CHANNEL_KEYS = ['in_app', 'email', 'sms', 'push'];
const CHANNEL_LABELS = {
  in_app: 'In-app',
  email: 'Email',
  sms: 'SMS',
  push: 'Push',
};

function MyNotificationsPanel({ ruleId }) {
  const prefsQuery = useMyRuleNotificationPrefs(ruleId);
  const savePrefs = useSaveMyRuleNotificationPrefs(ruleId);
  const [saveError, setSaveError] = useState('');

  if (prefsQuery.isLoading) return null;
  if (prefsQuery.isError) {
    if (prefsQuery.error?.response?.status === 403) return null;
    return (
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>My notifications</h2>
        <p className={styles.error}>Failed to load notification preferences.</p>
      </div>
    );
  }

  const prefs = prefsQuery.data;

  const handleToggle = async (channel) => {
    setSaveError('');
    const next = { ...prefs, [channel]: !prefs[channel] };
    try {
      await savePrefs.mutateAsync(next);
    } catch (err) {
      setSaveError(
        err.response?.data?.error?.message ||
          'Failed to save preference. Please try again.',
      );
    }
  };

  return (
    <div className={styles.section}>
      <h2 className={styles.sectionTitle}>My notifications</h2>
      <p style={{ fontSize: '0.8125rem', color: '#6B7280', marginTop: 0 }}>
        Choose which channels you receive when this rule fires. Your global
        notification settings still apply — most-restrictive wins.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.75rem' }}>
        {CHANNEL_KEYS.map((channel) => (
          <label
            key={channel}
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}
          >
            <input
              type="checkbox"
              checked={!!prefs[channel]}
              disabled={savePrefs.isPending}
              onChange={() => handleToggle(channel)}
            />
            {CHANNEL_LABELS[channel]}
          </label>
        ))}
      </div>
      {saveError && (
        <p className={styles.error} style={{ marginTop: '0.5rem' }}>{saveError}</p>
      )}
    </div>
  );
}

MyNotificationsPanel.propTypes = {
  ruleId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

export default MyNotificationsPanel;
