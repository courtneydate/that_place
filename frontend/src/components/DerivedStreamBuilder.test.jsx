/**
 * Sprint 27 — DerivedStreamBuilder tests.
 *
 * Coverage:
 *   - renders with the default `delta` formula and the right param controls
 *   - switching formula re-renders the right params (factor for scale,
 *     window_minutes for window_*)
 *   - submitting calls the create mutation with the assembled payload
 *   - shows a save error when the mutation rejects
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DerivedStreamBuilder from './DerivedStreamBuilder';

let mockDevices = [];
let mockStreams = [];
const mockCreate = jest.fn(() => Promise.resolve({}));

jest.mock('../hooks/useDevices', () => ({
  useDevices: () => ({ data: mockDevices, isLoading: false }),
}));
jest.mock('../hooks/useStreams', () => ({
  useDeviceStreams: () => ({ data: mockStreams, isLoading: false }),
}));
jest.mock('../hooks/useDerivedStreams', () => ({
  useCreateDerivedStream: () => ({
    mutateAsync: mockCreate,
    isPending: false,
  }),
}));

beforeEach(() => {
  mockDevices = [{ id: 1, name: 'Meter A' }];
  mockStreams = [
    { id: 100, key: 'cumulative_kwh', label: 'Cumulative kWh', data_type: 'numeric' },
  ];
  mockCreate.mockReset();
  mockCreate.mockResolvedValue({});
});

describe('DerivedStreamBuilder', () => {
  it('renders with delta selected by default and shows the max-gap param', () => {
    render(<DerivedStreamBuilder onDone={() => {}} />);
    expect(screen.getByLabelText(/stream key/i)).toBeInTheDocument();
    const formulaSelect = screen.getByLabelText(/formula/i);
    expect(formulaSelect).toHaveValue('delta');
    expect(screen.getByLabelText(/max gap minutes/i)).toBeInTheDocument();
  });

  it('switches to scale and shows the factor input', () => {
    render(<DerivedStreamBuilder onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/formula/i), { target: { value: 'scale' } });
    expect(screen.getByLabelText(/factor/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/max gap minutes/i)).not.toBeInTheDocument();
  });

  it('switches to window_min and shows the window-minutes input', () => {
    render(<DerivedStreamBuilder onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/formula/i), { target: { value: 'window_min' } });
    expect(screen.getByLabelText(/window minutes/i)).toBeInTheDocument();
  });

  it('blocks submit when the stream key is blank', async () => {
    render(<DerivedStreamBuilder onDone={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /create derived stream/i }));
    await waitFor(() => {
      expect(screen.getByText(/stream key is required/i)).toBeInTheDocument();
    });
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('submits a delta derived stream with the chosen source', async () => {
    const onDone = jest.fn();
    render(<DerivedStreamBuilder onDone={onDone} />);

    fireEvent.change(screen.getByLabelText(/stream key/i), { target: { value: 'interval_kwh' } });
    // Pick device, then stream.
    fireEvent.change(screen.getByLabelText(/^device$/i), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText(/^stream$/i), { target: { value: '100' } });

    fireEvent.click(screen.getByRole('button', { name: /create derived stream/i }));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    const payload = mockCreate.mock.calls[0][0];
    expect(payload).toMatchObject({
      key: 'interval_kwh',
      formula: 'delta',
      source_stream_ids: [100],
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it('surfaces a save error when the create mutation rejects', async () => {
    mockCreate.mockRejectedValueOnce({
      response: { data: { error: { message: 'Stream key already exists.' } } },
    });
    render(<DerivedStreamBuilder onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/stream key/i), { target: { value: 'x' } });
    fireEvent.change(screen.getByLabelText(/^device$/i), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText(/^stream$/i), { target: { value: '100' } });

    fireEvent.click(screen.getByRole('button', { name: /create derived stream/i }));

    await waitFor(() => {
      expect(screen.getByText(/stream key already exists/i)).toBeInTheDocument();
    });
  });
});
