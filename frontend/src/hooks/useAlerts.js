/**
 * React Query hooks for alert management.
 *
 * List and detail are accessible to all tenant users.
 * Acknowledge and resolve require Operator or Admin role (enforced on backend).
 * Ref: SPEC.md § Feature: Alerts
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const ALERTS_KEY = ['alerts'];

export function useAlerts(params = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.rule) query.set('rule', params.rule);
  if (params.site) query.set('site', params.site);
  const qs = query.toString();

  return useQuery({
    queryKey: [...ALERTS_KEY, params],
    queryFn: () => api.get(`/api/v1/alerts/${qs ? `?${qs}` : ''}`).then((r) => r.data),
    refetchInterval: 30_000, // Poll every 30 s — no WebSocket in MVP
  });
}

export function useAlert(alertId) {
  return useQuery({
    queryKey: [...ALERTS_KEY, alertId],
    queryFn: () => api.get(`/api/v1/alerts/${alertId}/`).then((r) => r.data),
    enabled: !!alertId,
  });
}

export function useActiveAlertCount() {
  /**
   * Returns the count of active alerts for use in the nav badge.
   * Polls every 30 s to keep the badge current without WebSocket.
   */
  return useQuery({
    queryKey: [...ALERTS_KEY, 'count', 'active'],
    queryFn: () =>
      api.get('/api/v1/alerts/?status=active').then((r) => r.data.length),
    refetchInterval: 30_000,
  });
}

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, note }) =>
      api.post(`/api/v1/alerts/${alertId}/acknowledge/`, { note }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ALERTS_KEY });
    },
  });
}

export function useResolveAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId) =>
      api.post(`/api/v1/alerts/${alertId}/resolve/`, {}).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ALERTS_KEY });
    },
  });
}
