/**
 * Notification bell for the That Place Admin layout.
 *
 * Mirrors the tenant notification panel (Sprint 19) — unread badge, dropdown
 * list, mark-as-read on click, mark-all-read. Platform notifications carry a
 * server-rendered `message`, so the panel shows that text directly. Clicking
 * a device-pending-approval notification navigates to Pending Devices.
 *
 * Ref: ROADMAP Sprint 23
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUnreadCount,
} from '../hooks/useNotifications';
import styles from './AdminNotificationBell.module.css';

// Event types that have a meaningful admin destination on click.
const NAV_TARGETS = {
  device_pending_approval: '/admin/pending-devices',
};

function formatTime(iso) {
  /** Return a compact relative time label for a notification timestamp. */
  if (!iso) return '';
  const d = new Date(iso);
  const diffMins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function AdminNotificationBell() {
  /**
   * Bell icon in the That Place Admin header — shows the unread count badge
   * and opens a dropdown of recent platform notifications.
   */
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const { data: unreadCount = 0 } = useUnreadCount();
  const { data: notifications = [] } = useNotifications();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();

  // Close the dropdown when clicking outside it.
  useEffect(() => {
    function handleOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  const handleNotificationClick = async (notif) => {
    if (!notif.is_read) await markRead.mutateAsync(notif.id);
    setOpen(false);
    const target = NAV_TARGETS[notif.event_type];
    if (target) navigate(target);
  };

  return (
    <div className={styles.bellWrap} ref={ref}>
      <button
        className={styles.bellButton}
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
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
        <div className={styles.dropdown}>
          <div className={styles.header}>
            <span className={styles.title}>Notifications</span>
            {unreadCount > 0 && (
              <button
                className={styles.markAllBtn}
                onClick={() => markAllRead.mutate()}
                disabled={markAllRead.isPending}
              >
                Mark all as read
              </button>
            )}
          </div>
          <div className={styles.list}>
            {notifications.length === 0 && (
              <p className={styles.empty}>No notifications yet.</p>
            )}
            {notifications.slice(0, 20).map((notif) => (
              <button
                key={notif.id}
                className={`${styles.item} ${notif.is_read ? styles.read : styles.unread}`}
                onClick={() => handleNotificationClick(notif)}
              >
                <div className={styles.itemMessage}>
                  {notif.message || notif.event_type}
                </div>
                <div className={styles.itemTime}>{formatTime(notif.sent_at)}</div>
                {!notif.is_read && <span className={styles.dot} />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default AdminNotificationBell;
