/**
 * React Query hooks for billing accounts (Sprint 30).
 *
 * Three layers:
 *   - useBillingAccounts / useBillingAccount      — top-level account CRUD
 *   - useBillingAccountMeters / mutate hooks      — nested meter links
 *   - useBillingAccountTariffs / mutate hooks     — nested tariff assignments
 *   - useBillingAccountAuditLog                   — append-only history
 *   - useBulkUploadBillingAccounts                — CSV upsert
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

export const ACCOUNTS_KEY = ['billing-accounts'];
export const accountKey = (id) => ['billing-account', id];
export const metersKey = (id) => ['billing-account-meters', id];
export const tariffsKey = (id) => ['billing-account-tariffs', id];
export const auditLogKey = (id) => ['billing-account-audit-log', id];

// --- BillingAccount ---------------------------------------------------------

export function useBillingAccounts(filters = {}) {
  const params = new URLSearchParams();
  if (filters.account_type) params.set('account_type', filters.account_type);
  if (filters.is_active !== undefined) params.set('is_active', String(filters.is_active));
  const qs = params.toString();
  return useQuery({
    queryKey: [...ACCOUNTS_KEY, qs],
    queryFn: () => api.get(`/api/v1/billing-accounts/${qs ? `?${qs}` : ''}`).then((r) => r.data),
  });
}

export function useBillingAccount(id) {
  return useQuery({
    queryKey: accountKey(id),
    queryFn: () => api.get(`/api/v1/billing-accounts/${id}/`).then((r) => r.data),
    enabled: !!id,
  });
}

export function useCreateBillingAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.post('/api/v1/billing-accounts/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function usePatchBillingAccount(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.patch(`/api/v1/billing-accounts/${id}/`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: accountKey(id) });
      qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
      qc.invalidateQueries({ queryKey: auditLogKey(id) });
    },
  });
}

export function useDeleteBillingAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.delete(`/api/v1/billing-accounts/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

// --- Meter links ------------------------------------------------------------

export function useBillingAccountMeters(accountId) {
  return useQuery({
    queryKey: metersKey(accountId),
    queryFn: () =>
      api.get(`/api/v1/billing-accounts/${accountId}/meters/`).then((r) => r.data),
    enabled: !!accountId,
  });
}

export function useCreateBillingAccountMeter(accountId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.post(`/api/v1/billing-accounts/${accountId}/meters/`, data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: metersKey(accountId) }),
  });
}

export function useDeleteBillingAccountMeter(accountId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkId) =>
      api.delete(`/api/v1/billing-accounts/${accountId}/meters/${linkId}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: metersKey(accountId) }),
  });
}

// --- Tariff assignments -----------------------------------------------------

export function useBillingAccountTariffs(accountId) {
  return useQuery({
    queryKey: tariffsKey(accountId),
    queryFn: () =>
      api.get(`/api/v1/billing-accounts/${accountId}/tariffs/`).then((r) => r.data),
    enabled: !!accountId,
  });
}

export function useCreateBillingAccountTariff(accountId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.post(`/api/v1/billing-accounts/${accountId}/tariffs/`, data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: tariffsKey(accountId) }),
  });
}

export function useDeleteBillingAccountTariff(accountId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) =>
      api.delete(`/api/v1/billing-accounts/${accountId}/tariffs/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: tariffsKey(accountId) }),
  });
}

// --- Audit log --------------------------------------------------------------

export function useBillingAccountAuditLog(accountId) {
  return useQuery({
    queryKey: auditLogKey(accountId),
    queryFn: () =>
      api.get(`/api/v1/billing-accounts/${accountId}/audit-log/`).then((r) => r.data),
    enabled: !!accountId,
  });
}

// --- Bulk CSV upsert --------------------------------------------------------

export function useBulkUploadBillingAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file) => {
      const form = new FormData();
      form.append('file', file);
      const resp = await api.post('/api/v1/billing-accounts/bulk/', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return resp.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}
