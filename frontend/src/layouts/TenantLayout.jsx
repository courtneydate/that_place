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
import { useMarkAllRead, useMarkRead, useNotifications, useUnreadCount } from '../hooks/useNotifications';
import styles from './TenantLayout.module.css';

// ---------------------------------------------------------------------------
// Notification bell + dropdown
// ---------------------------------------------------------------------------

function NotificationBell() {
  /**
   * Bell icon in the header that shows the unread count badge and opens a
   * dropdown panel with recent notifications. Tapping a notification marks it
   * read and navigates to the related alert. "Mark all as read" clears the badge.
   * Ref: SPEC.md § Feature: Notifications — dropdown panel
   */
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const { data: unreadCount = 0 } = useUnreadCount();
  const { data: notifications = [] } = useNotifications();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
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
    if (notif.alert) {
      navigate(`/app/alerts/${notif.alert}`);
    }
  };

  const handleMarkAll = async () => {
    await markAllRead.mutateAsync();
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

  return (
    <div className={styles.bellWrap} ref={ref}>
      <button
        className={styles.bellButton}
        onClick={() => setOpen((v) => !v)}
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
            {notifications.slice(0, 20).map((notif) => (
              <button
                key={notif.id}
                className={`${styles.notifItem} ${notif.is_read ? styles.notifRead : styles.notifUnread}`}
                onClick={() => handleNotificationClick(notif)}
              >
                <div className={styles.notifItemTitle}>{notifTitle(notif)}</div>
                {notifDetail(notif) && (
                  <div className={styles.notifItemDetail}>{notifDetail(notif)}</div>
                )}
                <div className={styles.notifItemTime}>{formatTime(notif.sent_at)}</div>
                {!notif.is_read && <span className={styles.notifDot} />}
              </button>
            ))}
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
