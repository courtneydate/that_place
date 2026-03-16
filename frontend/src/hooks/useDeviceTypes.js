/**
 * React Query hooks for device type management.
 *
 * DeviceType reads are available to all authenticated users.
 * DeviceType writes are restricted to Fieldmouse Admins (enforced on backend).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const DEVICE_TYPES_KEY = ['device-types'];

export function useDeviceTypes() {
  return useQuery({
    queryKey: DEVICE_TYPES_KEY,
    queryFn: () => api.get('/api/v1/device-types/').then((r) => r.data),
  });
}

export function useCreateDeviceType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/device-types/', data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICE_TYPES_KEY }),
  });
}

export function useUpdateDeviceType(deviceTypeId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.put(`/api/v1/device-types/${deviceTypeId}/`, data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICE_TYPES_KEY }),
  });
}
