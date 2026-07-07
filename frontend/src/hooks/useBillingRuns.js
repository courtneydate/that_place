/**
 * React Query hooks for billing runs, invoices, and schedules (Sprint 32).
 *
 * Covers:
 *   - useBillingRuns / useBillingRun       — run list + detail
 *   - useCreateBillingRun                  — dispatch a new run
 *   - useRetryBillingRun                   — retry a failed run
 *   - useRecomputeBillingRun               — rebuild a draft run
 *   - useFinalizeBillingRun                — lock + issue invoices
 *   - useVoidBillingRun                    — void a finalized run
 *   - useBillingRunLineItems               — line items for a run
 *   - useBillingRunSnapshot                — snapshot for a run
 *   - useBillingInvoices / useBillingInvoice — invoice list + detail
 *   - useInvoicePdfUrl                     — 15-min signed URL
 *   - useResendInvoice                     — re-queue email delivery
 *   - useBillingSchedules / useBillingSchedule — schedule CRUD
 *   - useCreateBillingSchedule / useUpdateBillingSchedule / useDeleteBillingSchedule
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

// ---------------------------------------------------------------------------
// Cache keys
// ---------------------------------------------------------------------------

export const RUNS_KEY = ['billing-runs'];
export const runKey = (id) => ['billing-run', id];
export const runLineItemsKey = (id) => ['billing-run-line-items', id];
export const runSnapshotKey = (id) => ['billing-run-snapshot', id];
export const runReconciliationKey = (id) => ['billing-run-reconciliation', id];
export const INVOICES_KEY = ['billing-invoices'];
export const invoiceKey = (id) => ['billing-invoice', id];
export const SCHEDULES_KEY = ['billing-schedules'];
export const scheduleKey = (id) => ['billing-schedule', id];

// ---------------------------------------------------------------------------
// BillingRun queries
// ---------------------------------------------------------------------------

export function useBillingRuns(filters = {}) {
  const params = new URLSearchParams();
  if (filters.site) params.set('site', filters.site);
  if (filters.status) params.set('status', filters.status);
  const qs = params.toString();
  return useQuery({
    queryKey: [...RUNS_KEY, qs],
    queryFn: () =>
      api.get(`/api/v1/billing-runs/${qs ? `?${qs}` : ''}`).then((r) => r.data),
  });
}

export function useBillingRun(id) {
  return useQuery({
    queryKey: runKey(id),
    queryFn: () => api.get(`/api/v1/billing-runs/${id}/`).then((r) => r.data),
    enabled: !!id,
  });
}

export function useBillingRunLineItems(runId) {
  return useQuery({
    queryKey: runLineItemsKey(runId),
    queryFn: () =>
      api.get(`/api/v1/billing-runs/${runId}/line-items/`).then((r) => r.data),
    enabled: !!runId,
  });
}

export function useBillingRunSnapshot(runId) {
  return useQuery({
    queryKey: runSnapshotKey(runId),
    queryFn: () =>
      api.get(`/api/v1/billing-runs/${runId}/snapshot/`).then((r) => r.data),
    enabled: !!runId,
  });
}

/**
 * Reconciliation report for a hierarchical run (Sprint 34).
 * 404s for PPA / single-tier runs — treated as "no report" (null), not an error.
 */
export function useReconciliation(runId) {
  return useQuery({
    queryKey: runReconciliationKey(runId),
    queryFn: () =>
      api
        .get(`/api/v1/billing-runs/${runId}/reconciliation/`)
        .then((r) => r.data)
        .catch((err) => {
          if (err.response?.status === 404) return null;
          throw err;
        }),
    enabled: !!runId,
  });
}

// ---------------------------------------------------------------------------
// BillingRun mutations
// ---------------------------------------------------------------------------

export function useCreateBillingRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.post('/api/v1/billing-runs/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: RUNS_KEY }),
  });
}

export function useRetryBillingRun(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post(`/api/v1/billing-runs/${id}/retry/`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKey(id) });
      qc.invalidateQueries({ queryKey: RUNS_KEY });
    },
  });
}

export function useRecomputeBillingRun(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post(`/api/v1/billing-runs/${id}/recompute/`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKey(id) });
      qc.invalidateQueries({ queryKey: RUNS_KEY });
      qc.invalidateQueries({ queryKey: runLineItemsKey(id) });
      qc.invalidateQueries({ queryKey: runSnapshotKey(id) });
    },
  });
}

export function useFinalizeBillingRun(id) {
  const qc = useQueryClient();
  return useMutation({
    // Sprint 34: `force` + `note` override the reconciliation tolerance gate.
    mutationFn: ({ force, note } = {}) =>
      api
        .post(`/api/v1/billing-runs/${id}/finalize/`, {
          force: Boolean(force),
          note: note || '',
        })
        .then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKey(id) });
      qc.invalidateQueries({ queryKey: RUNS_KEY });
      qc.invalidateQueries({ queryKey: INVOICES_KEY });
      qc.invalidateQueries({ queryKey: runReconciliationKey(id) });
    },
  });
}

export function useVoidBillingRun(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reason, silentVoid } = {}) =>
      api
        .post(`/api/v1/billing-runs/${id}/void/`, {
          reason: reason || '',
          silent_void: Boolean(silentVoid),
        })
        .then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKey(id) });
      qc.invalidateQueries({ queryKey: RUNS_KEY });
      qc.invalidateQueries({ queryKey: INVOICES_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// Invoice queries + mutations
// ---------------------------------------------------------------------------

export function useBillingInvoices(filters = {}) {
  const params = new URLSearchParams();
  if (filters.billing_account) params.set('billing_account', filters.billing_account);
  if (filters.run) params.set('run', filters.run);
  const qs = params.toString();
  return useQuery({
    queryKey: [...INVOICES_KEY, qs],
    queryFn: () =>
      api.get(`/api/v1/invoices/${qs ? `?${qs}` : ''}`).then((r) => r.data),
  });
}

export function useBillingInvoice(id) {
  return useQuery({
    queryKey: invoiceKey(id),
    queryFn: () => api.get(`/api/v1/invoices/${id}/`).then((r) => r.data),
    enabled: !!id,
  });
}

export function useInvoicePdfUrl(id) {
  return useQuery({
    queryKey: ['invoice-pdf-url', id],
    queryFn: () => api.get(`/api/v1/invoices/${id}/pdf/`).then((r) => r.data),
    enabled: !!id,
    staleTime: 600_000, // 10 min — URL valid for 15 min; re-fetch before expiry
  });
}

export function useResendInvoice(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post(`/api/v1/invoices/${id}/resend/`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: invoiceKey(id) });
      qc.invalidateQueries({ queryKey: INVOICES_KEY });
    },
  });
}

// ---------------------------------------------------------------------------
// BillingSchedule queries + mutations
// ---------------------------------------------------------------------------

export function useBillingSchedules() {
  return useQuery({
    queryKey: SCHEDULES_KEY,
    queryFn: () => api.get('/api/v1/billing-schedules/').then((r) => r.data),
  });
}

export function useBillingSchedule(id) {
  return useQuery({
    queryKey: scheduleKey(id),
    queryFn: () => api.get(`/api/v1/billing-schedules/${id}/`).then((r) => r.data),
    enabled: !!id,
  });
}

export function useCreateBillingSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.post('/api/v1/billing-schedules/', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: SCHEDULES_KEY }),
  });
}

export function useUpdateBillingSchedule(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.patch(`/api/v1/billing-schedules/${id}/`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scheduleKey(id) });
      qc.invalidateQueries({ queryKey: SCHEDULES_KEY });
    },
  });
}

export function useDeleteBillingSchedule(id) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.delete(`/api/v1/billing-schedules/${id}/`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: SCHEDULES_KEY }),
  });
}
