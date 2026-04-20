/**
 * React Query hooks for device command sending and history.
 *
 * sendCommand — dispatches a command to a device via POST and invalidates history.
 * useCommandHistory — fetches the CommandLog list for a device.
 *
 * Admin and Operator only; View-Only users should not render the UI that
 * calls these hooks.
 *
 * Ref: SPEC.md § Feature: Device Control
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

export function useCommandHistory(deviceId) {
  return useQuery({
    queryKey: ['command-history', deviceId],
    queryFn: () =>
      api.get(`/api/v1/devices/${deviceId}/commands/`).then((r) => r.data),
    enabled: !!deviceId,
    refetchInterval: 10000, // Poll every 10 s so ack/timeout status updates
  });
}

export function useSendCommand(deviceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ commandName, params }) =>
      api
        .post(`/api/v1/devices/${deviceId}/command/`, {
          command_name: commandName,
          params,
        })
        .then((r) => r.data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['command-history', deviceId] }),
  });
}
