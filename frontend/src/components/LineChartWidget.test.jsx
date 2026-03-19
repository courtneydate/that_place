import { render, screen } from '@testing-library/react';
import LineChartWidget from './LineChartWidget';

jest.mock('../hooks/useDashboards', () => ({
  useMultipleStreamReadings: jest.fn(),
}));

// react-apexcharts is stubbed via jest.config moduleNameMapper

import { useMultipleStreamReadings } from '../hooks/useDashboards';

const BASE_CONFIG = {
  streams: [{ stream_id: 1, axis: 'left', color: '#1A6B4A', label: 'Temperature' }],
  time_range: '24h',
};

const defaultProps = {
  config: BASE_CONFIG,
  refetchInterval: 30000,
  canEdit: false,
  onRemove: jest.fn(),
};

describe('LineChartWidget', () => {
  it('shows loading state while data is fetching', () => {
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: true, isError: false, data: null },
    ]);
    render(<LineChartWidget {...defaultProps} />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  it('shows error state when a query fails', () => {
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: false, isError: true, data: null },
    ]);
    render(<LineChartWidget {...defaultProps} />);
    expect(screen.getByText('Failed to load data.')).toBeInTheDocument();
  });

  it('shows empty-range message when readings array is empty', () => {
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: false, isError: false, data: [] },
    ]);
    render(<LineChartWidget {...defaultProps} />);
    expect(screen.getByText('No readings in this time range.')).toBeInTheDocument();
  });

  it('renders the ApexCharts stub when data is present', () => {
    useMultipleStreamReadings.mockReturnValue([
      {
        isLoading: false,
        isError: false,
        data: [{ recorded_at: '2026-01-01T00:00:00Z', value: '42.5' }],
      },
    ]);
    render(<LineChartWidget {...defaultProps} />);
    expect(screen.getByTestId('apex-chart')).toBeInTheDocument();
    expect(screen.getByTestId('apex-chart').dataset.type).toBe('line');
  });

  it('renders the time range selector', () => {
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: true, isError: false, data: null },
    ]);
    render(<LineChartWidget {...defaultProps} />);
    expect(screen.getByText('24h')).toBeInTheDocument();
  });

  it('shows remove button when canEdit is true', () => {
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: true, isError: false, data: null },
    ]);
    render(<LineChartWidget {...defaultProps} canEdit={true} />);
    expect(screen.getByTitle('Remove widget')).toBeInTheDocument();
  });

  it('hides remove button when canEdit is false', () => {
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: true, isError: false, data: null },
    ]);
    render(<LineChartWidget {...defaultProps} canEdit={false} />);
    expect(screen.queryByTitle('Remove widget')).not.toBeInTheDocument();
  });

  it('passes series with one entry per stream to the chart', () => {
    const twoStreamConfig = {
      streams: [
        { stream_id: 1, axis: 'left', color: '#1A6B4A', label: 'Temp' },
        { stream_id: 2, axis: 'right', color: '#EF4444', label: 'Humidity' },
      ],
      time_range: '24h',
    };
    useMultipleStreamReadings.mockReturnValue([
      { isLoading: false, isError: false, data: [{ recorded_at: '2026-01-01T00:00:00Z', value: '22' }] },
      { isLoading: false, isError: false, data: [{ recorded_at: '2026-01-01T00:00:00Z', value: '65' }] },
    ]);
    render(<LineChartWidget {...defaultProps} config={twoStreamConfig} />);
    const chart = screen.getByTestId('apex-chart');
    expect(chart.dataset.seriesCount).toBe('2');
  });
});
