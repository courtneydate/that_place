/**
 * React Query hooks for MeterProfile (Sprint 29).
 *
 * MeterProfile is the optional billing-meter sidecar to a Device. The
 * collection lives at /api/v1/devices/:id/meter-profile/ — there is at most
 * one profile per device, so we model it as a single object resource rather
 * than a list.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

export const METER_PROFILE_KEY = (deviceId) => ['meter-profile', deviceId];

/**
 * Fetch a device's MeterProfile. Returns `null` (not an error) when the
 * device has no profile yet — the panel uses that to show "Mark as meter".
 */
export function useMeterProfile(deviceId) {
  return useQuery({
    queryKey: METER_PROFILE_KEY(deviceId),
    queryFn: async () => {
      try {
        const resp = await api.get(`/api/v1/devices/${deviceId}/meter-profile/`);
        return resp.data;
      } catch (err) {
        if (err.response?.status === 404) return null;
        throw err;
      }
    },
    enabled: !!deviceId,
  });
}

/** Create or replace the MeterProfile via PUT (Tenant Admin only). */
export function useSaveMeterProfile(deviceId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.put(`/api/v1/devices/${deviceId}/meter-profile/`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: METER_PROFILE_KEY(deviceId) });
    },
  });
}

/** Partial update — used by the panel for single-field edits (PATCH). */
export function usePatchMeterProfile(deviceId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) =>
      api.patch(`/api/v1/devices/${deviceId}/meter-profile/`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: METER_PROFILE_KEY(deviceId) });
    },
  });
}

/** Remove the MeterProfile from a device. */
export function useDeleteMeterProfile(deviceId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete(`/api/v1/devices/${deviceId}/meter-profile/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: METER_PROFILE_KEY(deviceId) });
    },
  });
}

/**
 * Upload a CSV of MeterProfile rows. The response is the import summary —
 * the caller renders the per-row errors so the operator can fix and re-upload.
 */
export function useBulkUploadMeterProfiles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file) => {
      const form = new FormData();
      form.append('file', file);
      const resp = await api.post('/api/v1/meter-profiles/bulk/', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return resp.data;
    },
    onSuccess: () => {
      // The upload may have changed any number of devices' meter profiles —
      // invalidate the umbrella key so all open device pages refresh.
      qc.invalidateQueries({ queryKey: ['meter-profile'] });
    },
  });
}
