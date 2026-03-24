/**
 * React Query hooks for Tenant management (That Place Admin).
 *
 * Provides: useTenants, useTenant, useCreateTenant, useUpdateTenant, useSendInvite
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const TENANTS_KEY = ['tenants'];

export function useTenants() {
  return useQuery({
    queryKey: TENANTS_KEY,
    queryFn: () => api.get('/api/v1/tenants/').then((r) => r.data),
  });
}

export function useTenant(id) {
  return useQuery({
    queryKey: [...TENANTS_KEY, id],
    queryFn: () => api.get(`/api/v1/tenants/${id}/`).then((r) => r.data),
    enabled: !!id,
  });
}

export function useCreateTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/tenants/', data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TENANTS_KEY }),
  });
}

export function useUpdateTenant(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.patch(`/api/v1/tenants/${id}/`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TENANTS_KEY });
      queryClient.invalidateQueries({ queryKey: [...TENANTS_KEY, id] });
    },
  });
}

export function useSendInvite(tenantId) {
  return useMutation({
    mutationFn: (data) =>
      api.post(`/api/v1/tenants/${tenantId}/invite/`, data).then((r) => r.data),
  });
}
