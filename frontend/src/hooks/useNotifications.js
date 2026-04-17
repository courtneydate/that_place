/**
 * React Query hooks for in-app notifications.
 *
 * Notifications are scoped to the requesting user — no tenant filtering needed.
 * The unread count polls every 30 s for nav badge freshness.
 * Ref: SPEC.md § Feature: Notifications
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const NOTIFICATIONS_KEY = ['notifications'];

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
