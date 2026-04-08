/**
 * React Query hooks for stream configuration.
 *
 * Streams are scoped to a device. Label, unit, and display_enabled
 * are editable by Tenant Admins.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

export function useStream(streamId) {
  return useQuery({
    queryKey: ['stream', streamId],
    queryFn: () => api.get(`/api/v1/streams/${streamId}/`).then((r) => r.data),
    enabled: !!streamId,
  });
}

export function useDeviceStreams(deviceId) {
  return useQuery({
    queryKey: ['device-streams', deviceId],
    queryFn: () =>
      api.get(`/api/v1/devices/${deviceId}/streams/`).then((r) => r.data),
    enabled: !!deviceId,
  });
}

export function useUpdateStream(deviceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ streamId, data }) =>
      api.put(`/api/v1/streams/${streamId}/`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['device-streams', deviceId] });
    },
  });
}
