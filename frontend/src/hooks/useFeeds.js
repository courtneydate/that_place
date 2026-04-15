/**
 * React Query hooks for the feeds app.
 *
 * Covers:
 *   - FeedProvider CRUD (ThatPlaceAdmin write, all authenticated read)
 *   - FeedChannel list + readings (all authenticated read)
 *   - TenantFeedSubscription CRUD (Tenant Admin)
 *   - ReferenceDataset CRUD + row operations (ThatPlaceAdmin write, all read)
 *   - TenantDatasetAssignment CRUD + resolve (Tenant Admin)
 *
 * Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const FEED_PROVIDERS_KEY = ['feed-providers'];
const feedProviderKey = (id) => [...FEED_PROVIDERS_KEY, id];
const feedProviderChannelsKey = (id) => [...FEED_PROVIDERS_KEY, id, 'channels'];

const FEED_SUBSCRIPTIONS_KEY = ['feed-subscriptions'];
const feedSubscriptionKey = (id) => [...FEED_SUBSCRIPTIONS_KEY, id];

const REFERENCE_DATASETS_KEY = ['reference-datasets'];
const referenceDatasetsKey = (id) => [...REFERENCE_DATASETS_KEY, id];
const datasetRowsKey = (id, version) => [...REFERENCE_DATASETS_KEY, id, 'rows', version];

const DATASET_ASSIGNMENTS_KEY = ['dataset-assignments'];
const datasetAssignmentKey = (id) => [...DATASET_ASSIGNMENTS_KEY, id];

// ---------------------------------------------------------------------------
// FeedProvider hooks
// ---------------------------------------------------------------------------

export function useFeedProviders() {
  return useQuery({
    queryKey: FEED_PROVIDERS_KEY,
    queryFn: () => api.get('/api/v1/feed-providers/').then((r) => r.data),
  });
}

export function useFeedProvider(id) {
  return useQuery({
    queryKey: feedProviderKey(id),
    queryFn: () => api.get(`/api/v1/feed-providers/${id}/`).then((r) => r.data),
    enabled: id != null,
  });
}

export function useFeedProviderChannels(id) {
  return useQuery({
    queryKey: feedProviderChannelsKey(id),
    queryFn: () => api.get(`/api/v1/feed-providers/${id}/channels/`).then((r) => r.data),
    enabled: id != null,
  });
}

export function useCreateFeedProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/feed-providers/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: FEED_PROVIDERS_KEY }),
  });
}

export function useUpdateFeedProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }) =>
      api.put(`/api/v1/feed-providers/${id}/`, data).then((r) => r.data),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: FEED_PROVIDERS_KEY });
      qc.invalidateQueries({ queryKey: feedProviderKey(id) });
    },
  });
}

export function useDeleteFeedProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/feed-providers/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: FEED_PROVIDERS_KEY }),
  });
}

// ---------------------------------------------------------------------------
// TenantFeedSubscription hooks
// ---------------------------------------------------------------------------

export function useFeedSubscriptions() {
  return useQuery({
    queryKey: FEED_SUBSCRIPTIONS_KEY,
    queryFn: () => api.get('/api/v1/feed-subscriptions/').then((r) => r.data),
  });
}

export function useCreateFeedSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/feed-subscriptions/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: FEED_SUBSCRIPTIONS_KEY }),
  });
}

export function useUpdateFeedSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }) =>
      api.patch(`/api/v1/feed-subscriptions/${id}/`, data).then((r) => r.data),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: FEED_SUBSCRIPTIONS_KEY });
      qc.invalidateQueries({ queryKey: feedSubscriptionKey(id) });
    },
  });
}

export function useDeleteFeedSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/feed-subscriptions/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: FEED_SUBSCRIPTIONS_KEY }),
  });
}

// ---------------------------------------------------------------------------
// ReferenceDataset hooks
// ---------------------------------------------------------------------------

export function useReferenceDatasets() {
  return useQuery({
    queryKey: REFERENCE_DATASETS_KEY,
    queryFn: () => api.get('/api/v1/reference-datasets/').then((r) => r.data),
  });
}

export function useReferenceDataset(id) {
  return useQuery({
    queryKey: referenceDatasetsKey(id),
    queryFn: () => api.get(`/api/v1/reference-datasets/${id}/`).then((r) => r.data),
    enabled: id != null,
  });
}

export function useDatasetRows(datasetId, version) {
  return useQuery({
    queryKey: datasetRowsKey(datasetId, version),
    queryFn: () => {
      const params = version ? `?version=${encodeURIComponent(version)}` : '';
      return api.get(`/api/v1/reference-datasets/${datasetId}/rows/${params}`).then((r) => r.data);
    },
    enabled: datasetId != null,
  });
}

export function useCreateReferenceDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/reference-datasets/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: REFERENCE_DATASETS_KEY }),
  });
}

export function useUpdateReferenceDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }) =>
      api.put(`/api/v1/reference-datasets/${id}/`, data).then((r) => r.data),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: REFERENCE_DATASETS_KEY });
      qc.invalidateQueries({ queryKey: referenceDatasetsKey(id) });
    },
  });
}

export function useDeleteReferenceDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/reference-datasets/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: REFERENCE_DATASETS_KEY }),
  });
}

export function useBulkImportRows() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, file }) => {
      const form = new FormData();
      form.append('file', file);
      return api
        .post(`/api/v1/reference-datasets/${datasetId}/rows/bulk/`, form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        .then((r) => r.data);
    },
    onSuccess: (_, { datasetId }) => {
      qc.invalidateQueries({ queryKey: [...REFERENCE_DATASETS_KEY, datasetId, 'rows'] });
    },
  });
}

// ---------------------------------------------------------------------------
// TenantDatasetAssignment hooks
// ---------------------------------------------------------------------------

export function useDatasetAssignments(siteId) {
  return useQuery({
    queryKey: [...DATASET_ASSIGNMENTS_KEY, { siteId }],
    queryFn: () => {
      const params = siteId ? `?site=${siteId}` : '';
      return api.get(`/api/v1/dataset-assignments/${params}`).then((r) => r.data);
    },
  });
}

export function useResolveAssignment(id) {
  return useQuery({
    queryKey: [...DATASET_ASSIGNMENTS_KEY, id, 'resolve'],
    queryFn: () =>
      api.get(`/api/v1/dataset-assignments/${id}/resolve/`).then((r) => r.data),
    enabled: id != null,
    retry: false,
  });
}

export function useCreateDatasetAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/dataset-assignments/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: DATASET_ASSIGNMENTS_KEY }),
  });
}

export function useUpdateDatasetAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }) =>
      api.patch(`/api/v1/dataset-assignments/${id}/`, data).then((r) => r.data),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: DATASET_ASSIGNMENTS_KEY });
      qc.invalidateQueries({ queryKey: datasetAssignmentKey(id) });
    },
  });
}

export function useDeleteDatasetAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/dataset-assignments/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: DATASET_ASSIGNMENTS_KEY }),
  });
}
