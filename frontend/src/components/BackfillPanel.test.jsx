/**
 * Sprint 29a — BackfillPanel tests.
 *
 * Covers:
 *   - empty state renders the form + "No backfill jobs yet"
 *   - submit calls the start mutation with the chosen date range
 *   - active job disables the form and the button shows the job's status
 *   - failed job renders the error_detail under the row
 *   - rejected start mutation surfaces the API message
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import BackfillPanel from './BackfillPanel';

let mockJobsQuery = { isLoading: false, data: [] };
const mockStartMutate = jest.fn(() => Promise.resolve());
let mockStartState = { isPending: false };

jest.mock('../hooks/useIntegrations', () => ({
  useBackfillJobs: () => mockJobsQuery,
  useStartBackfillJob: () => ({
    mutateAsync: mockStartMutate,
    isPending: mockStartState.isPending,
  }),
}));

beforeEach(() => {
  mockJobsQuery = { isLoading: false, data: [] };
  mockStartState = { isPending: false };
  mockStartMutate.mockReset();
  mockStartMutate.mockResolvedValue({});
});

const ds = { id: 7, provider_name: 'SoilScouts' };

describe('BackfillPanel', () => {
  it('renders an empty state when no jobs exist', () => {
    render(<BackfillPanel ds={ds} />);
    expect(screen.getByRole('heading', { name: /historical backfill/i })).toBeInTheDocument();
    expect(screen.getByText(/no backfill jobs yet/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start backfill/i })).toBeEnabled();
  });

  it('submits the date range to startJob', async () => {
    render(<BackfillPanel ds={ds} />);
    const from = screen.getByLabelText('From');
    const to = screen.getByLabelText('To');
    fireEvent.change(from, { target: { value: '2026-05-01' } });
    fireEvent.change(to, { target: { value: '2026-05-07' } });
    fireEvent.click(screen.getByRole('button', { name: /start backfill/i }));
    await waitFor(() => expect(mockStartMutate).toHaveBeenCalledTimes(1));
    expect(mockStartMutate).toHaveBeenCalledWith({
      dateFrom: '2026-05-01',
      dateTo: '2026-05-07',
    });
  });

  it('disables the form while a job is running and shows running label', () => {
    mockJobsQuery = {
      isLoading: false,
      data: [
        {
          id: 1, date_from: '2026-05-01', date_to: '2026-05-07',
          status: 'running', rows_stored: 0, rows_fetched: 0,
          error_detail: '', created_by_email: 'a@x',
          finished_at: null,
        },
      ],
    };
    render(<BackfillPanel ds={ds} />);
    expect(screen.getByLabelText('From')).toBeDisabled();
    expect(screen.getByLabelText('To')).toBeDisabled();
    expect(screen.getByRole('button', { name: /backfill running/i })).toBeDisabled();
  });

  it('shows failed error_detail under the failed row', () => {
    mockJobsQuery = {
      isLoading: false,
      data: [
        {
          id: 2, date_from: '2026-05-01', date_to: '2026-05-07',
          status: 'failed', rows_stored: 0, rows_fetched: 0,
          error_detail: 'History request failed: refused',
          created_by_email: 'a@x', finished_at: '2026-05-08T00:00:00Z',
        },
      ],
    };
    render(<BackfillPanel ds={ds} />);
    expect(screen.getByText(/refused/)).toBeInTheDocument();
  });

  it('surfaces the API error message on a rejected start', async () => {
    mockStartMutate.mockRejectedValueOnce({
      response: {
        data: { error: { message: 'Backfill job 5 is already running for this data source.' } },
      },
    });
    render(<BackfillPanel ds={ds} />);
    fireEvent.click(screen.getByRole('button', { name: /start backfill/i }));
    await waitFor(() =>
      expect(screen.getByText(/already running/i)).toBeInTheDocument(),
    );
  });
});
