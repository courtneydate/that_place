/**
 * Layout wrapper for tenant user pages.
 *
 * Renders a top navigation bar and main content area for tenant-scoped pages.
 * Navigation links will grow each sprint as new pages are added.
 */
import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useActiveAlertCount } from '../hooks/useAlerts';
import {
  useCancelSnooze,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useSnooze,
  useSnoozes,
  useUnreadCount,
} from '../hooks/useNotifications';
import styles from './TenantLayout.module.css';

// ---------------------------------------------------------------------------
// Notification bell + dropdown
// ---------------------------------------------------------------------------

const SNOOZE_DURATIONS = [
  { label: '15 min', value: 15 },
  { label: '1 hour', value: 60 },
  { label: '4 hours', value: 240 },
  { label: '24 hours', value: 1440 },
];

function NotificationBell() {
  /**
   * Bell icon in the header that shows the unread count badge and opens a
   * dropdown panel with recent notifications. Tapping a notification marks it
   * read and navigates to the related alert. "Mark all as read" clears the badge.
   *
   * Alert-type notifications include a snooze button that expands a duration
   * picker. If an active snooze exists for the rule, a clock indicator is shown
   * instead with a cancel option.
   *
   * Ref: SPEC.md § Feature: Notifications — dropdown panel, snooze
   */
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  // notifId of the notification whose snooze picker is currently expanded
  const [snoozingId, setSnoozingId] = useState(null);
  const ref = useRef(null);

  const { data: unreadCount = 0 } = useUnreadCount();
  const { data: notifications = [] } = useNotifications();
  const { data: snoozes = [] } = useSnoozes();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const snooze = useSnooze();
  const cancelSnooze = useCancelSnooze();

  // Build a map of rule_id → snooze for O(1) look-up
  const snoozeByRule = {};
  snoozes.forEach((s) => {
    snoozeByRule[s.rule] = s;
  });

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
        setSnoozingId(null);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleNotificationClick = async (notif) => {
    if (!notif.is_read) {
      await markRead.mutateAsync(notif.id);
    }
    setOpen(false);
    setSnoozingId(null);
    if (notif.alert) {
      navigate(`/app/alerts/${notif.alert}`);
    }
  };

  const handleMarkAll = async () => {
    await markAllRead.mutateAsync();
  };

  const handleSnooze = async (ruleId, durationMinutes) => {
    await snooze.mutateAsync({ rule_id: ruleId, duration_minutes: durationMinutes });
    setSnoozingId(null);
  };

  const handleCancelSnooze = async (ruleId) => {
    await cancelSnooze.mutateAsync(ruleId);
  };

  function notifTitle(notif) {
    if (notif.notification_type === 'alert') {
      return `Alert: ${notif.alert_rule_name || 'Rule fired'}`;
    }
    const labels = {
      device_approved: 'Device approved',
      device_offline: 'Device offline',
      device_deleted: 'Device deleted',
      datasource_poll_failure: 'Data source poll failure',
    };
    return labels[notif.event_type] || notif.event_type;
  }

  function notifDetail(notif) {
    const d = notif.event_data || {};
    if (d.device_name) return d.device_name;
    return null;
  }

  function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function formatSnoozeUntil(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }

  return (
    <div className={styles.bellWrap} ref={ref}>
      <button
        className={styles.bellButton}
        onClick={() => { setOpen((v) => !v); setSnoozingId(null); }}
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
      >
        {/* Bell SVG */}
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span className={styles.bellBadge}>
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className={styles.notifDropdown}>
          <div className={styles.notifHeader}>
            <span className={styles.notifTitle}>Notifications</span>
            {unreadCount > 0 && (
              <button
                className={styles.markAllBtn}
                onClick={handleMarkAll}
                disabled={markAllRead.isPending}
              >
                Mark all as read
              </button>
            )}
          </div>
          <div className={styles.notifList}>
            {notifications.length === 0 && (
              <p className={styles.notifEmpty}>No notifications yet.</p>
            )}
            {notifications.slice(0, 20).map((notif) => {
              const ruleId = notif.alert_rule_id;
              const isAlert = notif.notification_type === 'alert' && ruleId;
              const activeSnooze = isAlert ? snoozeByRule[ruleId] : null;
              const showPicker = snoozingId === notif.id;

              return (
                <div
                  key={notif.id}
                  className={`${styles.notifItem} ${notif.is_read ? styles.notifRead : styles.notifUnread}`}
                >
                  {/* Clickable body — navigate to alert */}
                  <button
                    className={styles.notifBody}
                    onClick={() => handleNotificationClick(notif)}
                  >
                    <div className={styles.notifItemTitle}>{notifTitle(notif)}</div>
                    {notifDetail(notif) && (
                      <div className={styles.notifItemDetail}>{notifDetail(notif)}</div>
                    )}
                    <div className={styles.notifItemTime}>{formatTime(notif.sent_at)}</div>
                  </button>

                  {/* Snooze / snoozed indicator row */}
                  {isAlert && (
                    <div className={styles.notifSnoozeRow}>
                      {activeSnooze ? (
                        /* Active snooze indicator */
                        <div className={styles.snoozedBadge}>
                          {/* Clock SVG */}
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="12" r="10" />
                            <polyline points="12 6 12 12 16 14" />
                          </svg>
                          <span>Snoozed until {formatSnoozeUntil(activeSnooze.snoozed_until)}</span>
                          <button
                            className={styles.cancelSnoozeBtn}
                            onClick={(e) => { e.stopPropagation(); handleCancelSnooze(ruleId); }}
                            disabled={cancelSnooze.isPending}
                            aria-label="Cancel snooze"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        /* Snooze trigger / duration picker */
                        showPicker ? (
                          <div className={styles.snoozePicker}>
                            <span className={styles.snoozePickerLabel}>Snooze for:</span>
                            {SNOOZE_DURATIONS.map((d) => (
                              <button
                                key={d.value}
                                className={styles.snoozeDurationBtn}
                                onClick={(e) => { e.stopPropagation(); handleSnooze(ruleId, d.value); }}
                                disabled={snooze.isPending}
                              >
                                {d.label}
                              </button>
                            ))}
                            <button
                              className={styles.snoozePickerCancel}
                              onClick={(e) => { e.stopPropagation(); setSnoozingId(null); }}
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            className={styles.snoozeBtn}
                            onClick={(e) => { e.stopPropagation(); setSnoozingId(notif.id); }}
                          >
                            Snooze
                          </button>
                        )
                      )}
                    </div>
                  )}

                  {!notif.is_read && <span className={styles.notifDot} />}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}


function TenantLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { data: activeAlertCount = 0 } = useActiveAlertCount();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <span className={styles.brand}>That Place</span>
        <nav className={styles.nav}>
          <NavLink
            to="/app/dashboards"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Dashboards
          </NavLink>
          <NavLink
            to="/app/users"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Users
          </NavLink>
          <NavLink
            to="/app/sites"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Sites
          </NavLink>
          <NavLink
            to="/app/devices"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Devices
          </NavLink>
          <NavLink
            to="/app/groups"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Groups
          </NavLink>
          <NavLink
            to="/app/rules"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Rules
          </NavLink>
          <div className={styles.navLinkWrap}>
            <NavLink
              to="/app/alerts"
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
            >
              Alerts
            </NavLink>
            {activeAlertCount > 0 && (
              <span className={styles.alertBadge}>
                {activeAlertCount > 99 ? '99+' : activeAlertCount}
              </span>
            )}
          </div>
          <NavLink
            to="/app/data-sources"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Data Sources
          </NavLink>
          <NavLink
            to="/app/feed-subscriptions"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Feeds
          </NavLink>
          <NavLink
            to="/app/dataset-assignments"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Datasets
          </NavLink>
          {(user?.role === 'admin' || user?.role === 'operator') && (
            <NavLink
              to="/app/reporting"
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
            >
              Reporting
            </NavLink>
          )}
          <NavLink
            to="/app/settings"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Settings
          </NavLink>
        </nav>
        <div className={styles.headerRight}>
          <NotificationBell />
          {user && (
            <div className={styles.userInfo}>
              {user.tenant_name && (
                <span className={styles.tenantName}>{user.tenant_name}</span>
              )}
              <span className={styles.userEmail}>{user.email}</span>
            </div>
          )}
          <button onClick={handleLogout} className={styles.logoutButton}>
            Sign out
          </button>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

export default TenantLayout;
