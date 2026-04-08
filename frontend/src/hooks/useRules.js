/**
 * React Query hooks for rule management.
 *
 * Rules are Tenant Admin only — create/update/delete require admin role.
 * List and detail are also restricted to admins (enforced on backend).
 * Ref: SPEC.md § Feature: Rules Engine, § Feature: Rule Versioning & Audit Trail
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

const RULES_KEY = ['rules'];

export function useRules() {
  return useQuery({
    queryKey: RULES_KEY,
    queryFn: () => api.get('/api/v1/rules/').then((r) => r.data),
  });
}

export function useRule(ruleId) {
  return useQuery({
    queryKey: [...RULES_KEY, ruleId],
    queryFn: () => api.get(`/api/v1/rules/${ruleId}/`).then((r) => r.data),
    enabled: !!ruleId,
  });
}

export function useCreateRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/rules/', data).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RULES_KEY }),
  });
}

export function useUpdateRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, data }) =>
      api.put(`/api/v1/rules/${ruleId}/`, data).then((r) => r.data),
    onSuccess: (_, { ruleId }) => {
      queryClient.invalidateQueries({ queryKey: RULES_KEY });
      queryClient.invalidateQueries({ queryKey: [...RULES_KEY, ruleId] });
    },
  });
}

export function usePatchRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, data }) =>
      api.patch(`/api/v1/rules/${ruleId}/`, data).then((r) => r.data),
    onSuccess: (_, { ruleId }) => {
      queryClient.invalidateQueries({ queryKey: RULES_KEY });
      queryClient.invalidateQueries({ queryKey: [...RULES_KEY, ruleId] });
    },
  });
}

export function useDeleteRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ruleId) => api.delete(`/api/v1/rules/${ruleId}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RULES_KEY }),
  });
}
