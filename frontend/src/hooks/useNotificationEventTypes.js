/**
 * React Query hooks for the NotificationEventType registry.
 *
 * That Place Admin only — the registry defines how system and platform
 * events become notifications (severity, channels, message template).
 * Event types are seeded by the backend; this page edits them.
 *
 * Ref: SPEC.md § Data Model — NotificationEventType; ROADMAP Sprint 23
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const EVENT_TYPES_KEY = ['notification-event-types'];

export function useNotificationEventTypes() {
  /** List all NotificationEventType records, ordered by key. */
  return useQuery({
    queryKey: EVENT_TYPES_KEY,
    queryFn: () =>
      api.get('/api/v1/notification-event-types/').then((r) => r.data),
  });
}

export function useUpdateNotificationEventType() {
  /**
   * PATCH a NotificationEventType — severity, default_channels,
   * message_template, label, description, or is_active. Invalidates the
   * registry cache on success.
   */
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }) =>
      api
        .patch(`/api/v1/notification-event-types/${id}/`, data)
        .then((r) => r.data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: EVENT_TYPES_KEY }),
  });
}
