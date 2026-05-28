/**
 * React Query hooks for derived streams (Sprint 27).
 *
 * Tenant-scoped CRUD plus on-demand backfill. Reads are open to all tenant
 * roles; writes require Tenant Admin (enforced server-side).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const DERIVED_KEY = ['derived-streams'];

export function useDerivedStreams() {
  return useQuery({
    queryKey: DERIVED_KEY,
    queryFn: () => api.get('/api/v1/derived-streams/').then((r) => r.data),
  });
}

export function useCreateDerivedStream() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.post('/api/v1/derived-streams/', data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DERIVED_KEY });
      queryClient.invalidateQueries({ queryKey: ['streams'] });
      queryClient.invalidateQueries({ queryKey: ['device-streams'] });
    },
  });
}

export function useDeleteDerivedStream() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/derived-streams/${id}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DERIVED_KEY });
      queryClient.invalidateQueries({ queryKey: ['streams'] });
      queryClient.invalidateQueries({ queryKey: ['device-streams'] });
    },
  });
}

export function useBackfillDerivedStream() {
  return useMutation({
    mutationFn: ({ id, dateFrom, dateTo }) =>
      api.post(`/api/v1/derived-streams/${id}/backfill/`, {
        date_from: dateFrom,
        date_to: dateTo,
      }).then((r) => r.data),
  });
}
