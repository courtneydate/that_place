/**
 * Settings — tenant timezone and notification preference configuration page.
 *
 * Tenant Admins can update the timezone via a select dropdown.
 * Non-admins see the current timezone as read-only text.
 * All users can manage their own notification channel preferences.
 * Ref: SPEC.md § Tenant Settings, § Feature: Notifications — Channels
 */
import { useEffect, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSettings, useUpdateSettings } from '../../hooks/useSettings';
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
} from '../../hooks/useNotifications';
import styles from '../admin/AdminPage.module.css';

const TIMEZONE_OPTIONS = [
  'Australia/Sydney',
  'Australia/Melbourne',
  'Australia/Brisbane',
  'Australia/Adelaide',
  'Australia/Perth',
  'Australia/Darwin',
  'Australia/Hobart',
  'Pacific/Auckland',
  'Pacific/Fiji',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'UTC',
];

function Settings() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  // Timezone
  const { data: settings, isLoading, isError } = useSettings();
  const updateSettings = useUpdateSettings();
  const [timezone, setTimezone] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState('');

  useEffect(() => {
    if (settings?.timezone) {
      setTimezone(settings.timezone);
    }
  }, [settings]);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaveError('');
    setSaveSuccess('');
    try {
      await updateSettings.mutateAsync({ timezone });
      setSaveSuccess('Settings saved.');
    } catch (err) {
      setSaveError(
        err.response?.data?.error?.message || 'Failed to save settings.'
      );
    }
  };

  // Notification preferences
  const { data: prefs, isLoading: prefsLoading, isError: prefsError } = useNotificationPreferences();
  const updatePrefs = useUpdateNotificationPreferences();

  const [inAppEnabled, setInAppEnabled] = useState(true);
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState('');
  const [prefsSaveError, setPrefsSaveError] = useState('');
  const [prefsSaveSuccess, setPrefsSaveSuccess] = useState('');

  useEffect(() => {
    if (prefs) {
      setInAppEnabled(prefs.in_app_enabled);
      setEmailEnabled(prefs.email_enabled);
      setSmsEnabled(prefs.sms_enabled);
      setPhoneNumber(prefs.phone_number || '');
    }
  }, [prefs]);

  const handlePrefsSave = async (e) => {
    e.preventDefault();
    setPrefsSaveError('');
    setPrefsSaveSuccess('');
    try {
      await updatePrefs.mutateAsync({
        in_app_enabled: inAppEnabled,
        email_enabled: emailEnabled,
        sms_enabled: smsEnabled,
        phone_number: phoneNumber,
      });
      setPrefsSaveSuccess('Preferences saved.');
    } catch (err) {
      setPrefsSaveError(
        err.response?.data?.error?.message || 'Failed to save preferences.'
      );
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Settings</h1>
      </div>

      {/* Timezone */}
      <section className={styles.section}>
        <h2>Tenant timezone</h2>

        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load settings.</p>}

        {!isLoading && !isError && settings && (
          isAdmin ? (
            <form onSubmit={handleSave} className={styles.form} noValidate>
              <div className={styles.field}>
                <label className={styles.label} htmlFor="timezone-select">
                  Timezone
                </label>
                <select
                  id="timezone-select"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className={styles.input}
                  disabled={updateSettings.isPending}
                >
                  {TIMEZONE_OPTIONS.map((tz) => (
                    <option key={tz} value={tz}>{tz}</option>
                  ))}
                </select>
              </div>
              <div className={styles.actions}>
                <button
                  type="submit"
                  className={styles.primaryButton}
                  disabled={updateSettings.isPending}
                >
                  {updateSettings.isPending ? 'Saving…' : 'Save'}
                </button>
              </div>
              {saveError && <p className={styles.error}>{saveError}</p>}
              {saveSuccess && <p className={styles.success}>{saveSuccess}</p>}
            </form>
          ) : (
            <p>
              <span className={styles.label}>Current timezone: </span>
              {settings.timezone || 'Not set'}
            </p>
          )
        )}
      </section>

      {/* Notification preferences */}
      <section className={styles.section}>
        <h2>Notification preferences</h2>
        <p className={styles.sectionDesc}>
          Choose how you receive alerts from That Place. In-app and email notifications
          are on by default. SMS must be explicitly enabled and requires a phone number.
        </p>

        {prefsLoading && <p className={styles.loading}>Loading…</p>}
        {prefsError && <p className={styles.error}>Failed to load preferences.</p>}

        {!prefsLoading && !prefsError && prefs && (
          <form onSubmit={handlePrefsSave} className={styles.form} noValidate>
            <div className={styles.toggleField}>
              <input
                type="checkbox"
                id="pref-in-app"
                checked={inAppEnabled}
                onChange={(e) => setInAppEnabled(e.target.checked)}
                className={styles.checkbox}
                disabled={updatePrefs.isPending}
              />
              <label htmlFor="pref-in-app" className={styles.toggleLabel}>
                <span className={styles.toggleLabelTitle}>In-app notifications</span>
                <span className={styles.toggleLabelDesc}>
                  Show alert and system notifications in the bell menu.
                </span>
              </label>
            </div>

            <div className={styles.toggleField}>
              <input
                type="checkbox"
                id="pref-email"
                checked={emailEnabled}
                onChange={(e) => setEmailEnabled(e.target.checked)}
                className={styles.checkbox}
                disabled={updatePrefs.isPending}
              />
              <label htmlFor="pref-email" className={styles.toggleLabel}>
                <span className={styles.toggleLabelTitle}>Email notifications</span>
                <span className={styles.toggleLabelDesc}>
                  Receive an email when a rule fires and you are a target.
                </span>
              </label>
            </div>

            <div className={styles.toggleField}>
              <input
                type="checkbox"
                id="pref-sms"
                checked={smsEnabled}
                onChange={(e) => setSmsEnabled(e.target.checked)}
                className={styles.checkbox}
                disabled={updatePrefs.isPending}
              />
              <label htmlFor="pref-sms" className={styles.toggleLabel}>
                <span className={styles.toggleLabelTitle}>SMS notifications</span>
                <span className={styles.toggleLabelDesc}>
                  Receive an SMS for critical alerts. Off by default — requires a
                  phone number below.
                </span>
              </label>
            </div>

            {smsEnabled && (
              <div className={styles.field}>
                <label className={styles.label} htmlFor="pref-phone">
                  Phone number
                </label>
                <input
                  id="pref-phone"
                  type="tel"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  placeholder="+61412345678"
                  className={styles.input}
                  disabled={updatePrefs.isPending}
                />
                <span className={styles.fieldHint}>
                  E.164 format recommended (e.g. +61412345678).
                </span>
              </div>
            )}

            <div className={styles.actions}>
              <button
                type="submit"
                className={styles.primaryButton}
                disabled={updatePrefs.isPending}
              >
                {updatePrefs.isPending ? 'Saving…' : 'Save preferences'}
              </button>
            </div>
            {prefsSaveError && <p className={styles.error}>{prefsSaveError}</p>}
            {prefsSaveSuccess && <p className={styles.success}>{prefsSaveSuccess}</p>}
          </form>
        )}
      </section>
    </div>
  );
}

export default Settings;
