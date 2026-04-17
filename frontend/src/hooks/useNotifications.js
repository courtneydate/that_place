/**
 * React Query hooks for in-app notifications, preferences, and snooze.
 *
 * Notifications are scoped to the requesting user — no tenant filtering needed.
 * The unread count polls every 30 s for nav badge freshness.
 * Ref: SPEC.md § Feature: Notifications
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const NOTIFICATIONS_KEY = ['notifications'];
const PREFERENCES_KEY = ['notifications', 'preferences'];
const SNOOZES_KEY = ['notifications', 'snoozes'];

export function useNotifications(params = {}) {
  const qs = params.unreadOnly ? '?unread_only=true' : '';
  return useQuery({
    queryKey: [...NOTIFICATIONS_KEY, params],
    queryFn: () => api.get(`/api/v1/notifications/${qs}`).then((r) => r.data),
    refetchInterval: 30_000,
  });
}

export function useUnreadCount() {
  /**
   * Returns the count of unread in-app notifications for the nav bell badge.
   * Polls every 30 s.
   */
  return useQuery({
    queryKey: [...NOTIFICATIONS_KEY, 'unread-count'],
    queryFn: () =>
      api.get('/api/v1/notifications/unread-count/').then((r) => r.data.count),
    refetchInterval: 30_000,
  });
}

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (notificationId) =>
      api.post(`/api/v1/notifications/${notificationId}/read/`).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });
}

export function useMarkAllRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post('/api/v1/notifications/mark-all-read/').then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });
}

// ---------------------------------------------------------------------------
// Notification preferences
// ---------------------------------------------------------------------------

export function useNotificationPreferences() {
  /**
   * Returns the current user's notification channel preferences.
   * A default row is created on first GET if none exists.
   * Ref: SPEC.md § Feature: Notifications — Channels
   */
  return useQuery({
    queryKey: PREFERENCES_KEY,
    queryFn: () =>
      api.get('/api/v1/notifications/preferences/').then((r) => r.data),
  });
}

export function useUpdateNotificationPreferences() {
  /**
   * PUT /api/v1/notifications/preferences/ — update channel opt-ins and phone.
   * Accepts any combination of in_app_enabled, email_enabled, sms_enabled,
   * phone_number. Invalidates preferences cache on success.
   */
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.put('/api/v1/notifications/preferences/', data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY }),
  });
}

// ---------------------------------------------------------------------------
// Notification snooze
// ---------------------------------------------------------------------------

export function useSnoozes() {
  /**
   * Returns all active snoozes for the current user.
   * Ref: SPEC.md § Feature: Notifications — Notification snooze
   */
  return useQuery({
    queryKey: SNOOZES_KEY,
    queryFn: () =>
      api.get('/api/v1/notifications/snooze/').then((r) => r.data),
  });
}

export function useSnooze() {
  /**
   * POST /api/v1/notifications/snooze/ — create or extend a rule snooze.
   * Payload: { rule_id, duration_minutes } where duration_minutes is one of
   * 15, 60, 240, 1440. Invalidates snooze list on success.
   */
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ rule_id, duration_minutes }) =>
      api
        .post('/api/v1/notifications/snooze/', { rule_id, duration_minutes })
        .then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SNOOZES_KEY }),
  });
}

export function useCancelSnooze() {
  /**
   * DELETE /api/v1/notifications/snooze/:rule_id/ — cancel an active snooze.
   * Idempotent — no-op if no snooze exists. Invalidates snooze list on success.
   */
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ruleId) =>
      api.delete(`/api/v1/notifications/snooze/${ruleId}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SNOOZES_KEY }),
  });
}
