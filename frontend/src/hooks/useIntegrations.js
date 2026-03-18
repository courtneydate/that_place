/**
 * React Query hooks for 3rd party API integrations.
 *
 * Covers:
 *   - ThirdPartyAPIProvider CRUD (FM Admin writes, all reads)
 *   - DataSource CRUD (Tenant Admin)
 *   - Device discovery and connection (Tenant Admin)
 *   - DataSourceDevice management (Tenant Admin)
 *
 * Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const PROVIDERS_KEY = ['api-providers'];
const DATA_SOURCES_KEY = ['data-sources'];

const dataSourceDevicesKey = (dsId) => ['data-sources', dsId, 'devices'];

// ---------------------------------------------------------------------------
// Provider hooks (FM Admin write / all read)
// ---------------------------------------------------------------------------

export function useProviders() {
  return useQuery({
    queryKey: PROVIDERS_KEY,
    queryFn: () => api.get('/api/v1/api-providers/').then((r) => r.data),
  });
}

export function useProvider(id) {
  return useQuery({
    queryKey: [...PROVIDERS_KEY, id],
    queryFn: () => api.get(`/api/v1/api-providers/${id}/`).then((r) => r.data),
    enabled: id != null,
  });
}

export function useCreateProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (formData) =>
      api.post('/api/v1/api-providers/', formData).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY }),
  });
}

export function useUpdateProvider(id) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (formData) =>
      api.put(`/api/v1/api-providers/${id}/`, formData).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY }),
  });
}

export function useDeleteProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/api-providers/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY }),
  });
}

// ---------------------------------------------------------------------------
// DataSource hooks (Tenant Admin)
// ---------------------------------------------------------------------------

export function useDataSources() {
  return useQuery({
    queryKey: DATA_SOURCES_KEY,
    queryFn: () => api.get('/api/v1/data-sources/').then((r) => r.data),
  });
}

export function useDataSource(id) {
  return useQuery({
    queryKey: [...DATA_SOURCES_KEY, id],
    queryFn: () => api.get(`/api/v1/data-sources/${id}/`).then((r) => r.data),
    enabled: id != null,
  });
}

export function useCreateDataSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/data-sources/', data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DATA_SOURCES_KEY }),
  });
}

export function useDeleteDataSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/data-sources/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DATA_SOURCES_KEY }),
  });
}

// ---------------------------------------------------------------------------
// Discovery + device connection
// ---------------------------------------------------------------------------

export function useDiscoverDevices(dsId) {
  return useMutation({
    mutationFn: () =>
      api.post(`/api/v1/data-sources/${dsId}/discover/`).then((r) => r.data),
  });
}

export function useConnectDevices(dsId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (devices) =>
      api.post(`/api/v1/data-sources/${dsId}/devices/`, devices).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: dataSourceDevicesKey(dsId) });
      queryClient.invalidateQueries({ queryKey: DATA_SOURCES_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// DataSourceDevice management
// ---------------------------------------------------------------------------

export function useDataSourceDevices(dsId) {
  return useQuery({
    queryKey: dataSourceDevicesKey(dsId),
    queryFn: () =>
      api.get(`/api/v1/data-sources/${dsId}/devices/`).then((r) => r.data),
    enabled: dsId != null,
  });
}

export function useUpdateDataSourceDevice(dsId, deviceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.patch(`/api/v1/data-sources/${dsId}/devices/${deviceId}/`, data).then((r) => r.data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: dataSourceDevicesKey(dsId) }),
  });
}

export function useDeactivateDataSourceDevice(dsId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deviceId) =>
      api.delete(`/api/v1/data-sources/${dsId}/devices/${deviceId}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: dataSourceDevicesKey(dsId) });
      queryClient.invalidateQueries({ queryKey: DATA_SOURCES_KEY });
    },
  });
}
