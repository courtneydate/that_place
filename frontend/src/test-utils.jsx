/**
 * Shared test utilities for components that need React Query context.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';

/**
 * Render a component wrapped in a fresh QueryClientProvider.
 * Retries are disabled so failed queries surface immediately in tests.
 */
function renderWithQuery(ui) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

export { renderWithQuery };
