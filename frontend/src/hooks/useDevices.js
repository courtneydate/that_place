/**
 * React Query hooks for device management.
 *
 * Device reads are tenant-scoped on the backend.
 * Fieldmouse Admins see all devices (used for the pending approval queue).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const DEVICES_KEY = ['devices'];

export function useDevices(params = {}) {
  const query = new URLSearchParams(params).toString();
  return useQuery({
    queryKey: [...DEVICES_KEY, params],
    queryFn: () =>
      api.get(`/api/v1/devices/${query ? `?${query}` : ''}`).then((r) => r.data),
  });
}

export function useCreateDevice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/devices/', data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICES_KEY }),
  });
}

export function useApproveDevice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deviceId) =>
      api.post(`/api/v1/devices/${deviceId}/approve/`).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICES_KEY }),
  });
}

export function useRejectDevice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deviceId) =>
      api.post(`/api/v1/devices/${deviceId}/reject/`).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICES_KEY }),
  });
}

export function useDeleteDevice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deviceId) => api.delete(`/api/v1/devices/${deviceId}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICES_KEY }),
  });
}
