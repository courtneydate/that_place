/**
 * React Query hooks for CSV export.
 *
 * Export history is Admin-only. The stream export itself is a file download
 * rather than a JSON mutation — handled directly via the Axios instance so
 * we get a Blob back instead of parsed JSON.
 */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

export function useExportHistory() {
  return useQuery({
    queryKey: ['export-history'],
    queryFn: () => api.get('/api/v1/exports/').then((r) => r.data),
  });
}

/**
 * Trigger a streaming CSV download.
 *
 * Returns a function that, when called with { streamIds, dateFrom, dateTo },
 * posts to the export endpoint, converts the binary response to a Blob, and
 * triggers a browser download via a temporary anchor element.
 */
export function useExportDownload() {
  const download = async ({ streamIds, dateFrom, dateTo }) => {
    const response = await api.post(
      '/api/v1/exports/stream/',
      { stream_ids: streamIds, date_from: dateFrom, date_to: dateTo },
      { responseType: 'blob' },
    );

    const url = URL.createObjectURL(response.data);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'that-place-export.csv';
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  return download;
}
