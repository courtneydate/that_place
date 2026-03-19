/**
 * React Query hooks for dashboard and widget management, and stream readings.
 *
 * Dashboards are shared across all tenant users.
 * Operators and Admins can create/edit/delete. View-Only can only read.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

// ---------------------------------------------------------------------------
// Dashboard hooks
// ---------------------------------------------------------------------------

export function useDashboards() {
  return useQuery({
    queryKey: ['dashboards'],
    queryFn: () => api.get('/api/v1/dashboards/').then((r) => r.data),
  });
}

export function useDashboard(id) {
  return useQuery({
    queryKey: ['dashboards', id],
    queryFn: () => api.get(`/api/v1/dashboards/${id}/`).then((r) => r.data),
    enabled: !!id,
  });
}

export function useCreateDashboard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/dashboards/', data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards'] });
    },
  });
}

export function useUpdateDashboard(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.put(`/api/v1/dashboards/${id}/`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards', id] });
      queryClient.invalidateQueries({ queryKey: ['dashboards'] });
    },
  });
}

export function useDeleteDashboard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/dashboards/${id}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Widget hooks
// ---------------------------------------------------------------------------

export function useCreateWidget(dashboardId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.post(`/api/v1/dashboards/${dashboardId}/widgets/`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards', dashboardId] });
    },
  });
}

export function useUpdateWidget(dashboardId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ widgetId, data }) =>
      api
        .put(`/api/v1/dashboards/${dashboardId}/widgets/${widgetId}/`, data)
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards', dashboardId] });
    },
  });
}

export function useDeleteWidget(dashboardId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (widgetId) =>
      api.delete(`/api/v1/dashboards/${dashboardId}/widgets/${widgetId}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards', dashboardId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Stream readings hook
// ---------------------------------------------------------------------------

/**
 * Fetch readings for a stream with optional time range and limit filters.
 *
 * @param {number|null} streamId - Stream PK to fetch readings for.
 * @param {object} params - Optional: { from, to, limit }
 * @param {object} queryOptions - Additional React Query options (e.g. refetchInterval).
 */
export function useStreamReadings(streamId, params = {}, queryOptions = {}) {
  return useQuery({
    queryKey: ['stream-readings', streamId, params],
    queryFn: () =>
      api
        .get(`/api/v1/streams/${streamId}/readings/`, { params })
        .then((r) => r.data),
    enabled: !!streamId,
    ...queryOptions,
  });
}

/**
 * Fetch readings for multiple streams in parallel.
 *
 * @param {Array<{stream_id: number}>} streamConfigs - Array of stream config objects.
 * @param {object} params - Shared query params applied to all streams: { from, to, limit }
 * @param {object} queryOptions - Additional React Query options (e.g. refetchInterval).
 * @returns {Array} Array of query result objects, one per stream, in the same order.
 */
export function useMultipleStreamReadings(streamConfigs = [], params = {}, queryOptions = {}) {
  return useQueries({
    queries: streamConfigs.map(({ stream_id }) => ({
      queryKey: ['stream-readings', stream_id, params],
      queryFn: () =>
        api.get(`/api/v1/streams/${stream_id}/readings/`, { params }).then((r) => r.data),
      enabled: !!stream_id,
      ...queryOptions,
    })),
  });
}
