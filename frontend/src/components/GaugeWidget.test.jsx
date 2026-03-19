import { render, screen } from '@testing-library/react';
import { renderWithQuery } from '../test-utils';
import GaugeWidget from './GaugeWidget';

jest.mock('../hooks/useDashboards', () => ({
  useStreamReadings: jest.fn(),
}));

jest.mock('../services/api', () => ({
  get: jest.fn().mockResolvedValue({ data: { id: 1, label: 'Pressure', key: 'pressure', unit: 'bar' } }),
}));

// react-apexcharts is stubbed via jest.config moduleNameMapper

import { useStreamReadings } from '../hooks/useDashboards';

const BASE_CONFIG = {
  stream_id: 1,
  min: 0,
  max: 100,
  warning_threshold: 60,
  danger_threshold: 80,
};

const defaultProps = {
  config: BASE_CONFIG,
  refetchInterval: 30000,
  canEdit: false,
  onRemove: jest.fn(),
};

describe('GaugeWidget', () => {
  it('shows loading state while readings are fetching', () => {
    useStreamReadings.mockReturnValue({ isLoading: true, isError: false, data: null });
    renderWithQuery(<GaugeWidget {...defaultProps} />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  it('shows error state when readings query fails', () => {
    useStreamReadings.mockReturnValue({ isLoading: false, isError: true, data: null });
    renderWithQuery(<GaugeWidget {...defaultProps} />);
    expect(screen.getByText('Failed to load.')).toBeInTheDocument();
  });

  it('renders the ApexCharts radialBar stub when data is available', () => {
    useStreamReadings.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [{ value: '45', recorded_at: '2026-01-01T00:00:00Z' }],
    });
    renderWithQuery(<GaugeWidget {...defaultProps} />);
    const chart = screen.getByTestId('apex-chart');
    expect(chart).toBeInTheDocument();
    expect(chart.dataset.type).toBe('radialBar');
  });

  it('renders min and max range labels', () => {
    useStreamReadings.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [{ value: '45', recorded_at: '2026-01-01T00:00:00Z' }],
    });
    renderWithQuery(<GaugeWidget {...defaultProps} />);
    expect(screen.getByText(/^0/)).toBeInTheDocument();
    expect(screen.getByText(/^100/)).toBeInTheDocument();
  });

  it('shows the three band labels', () => {
    useStreamReadings.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [{ value: '45', recorded_at: '2026-01-01T00:00:00Z' }],
    });
    renderWithQuery(<GaugeWidget {...defaultProps} />);
    expect(screen.getByText(/Normal/)).toBeInTheDocument();
    expect(screen.getByText(/Warning/)).toBeInTheDocument();
    expect(screen.getByText(/Danger/)).toBeInTheDocument();
  });

  it('uses label_override when provided', () => {
    useStreamReadings.mockReturnValue({ isLoading: true, isError: false, data: null });
    renderWithQuery(
      <GaugeWidget {...defaultProps} config={{ ...BASE_CONFIG, label_override: 'Tank Pressure' }} />,
    );
    expect(screen.getByText('Tank Pressure')).toBeInTheDocument();
  });

  it('shows remove button when canEdit is true', () => {
    useStreamReadings.mockReturnValue({ isLoading: true, isError: false, data: null });
    renderWithQuery(<GaugeWidget {...defaultProps} canEdit={true} />);
    expect(screen.getByTitle('Remove widget')).toBeInTheDocument();
  });

  it('hides remove button when canEdit is false', () => {
    useStreamReadings.mockReturnValue({ isLoading: true, isError: false, data: null });
    renderWithQuery(<GaugeWidget {...defaultProps} canEdit={false} />);
    expect(screen.queryByTitle('Remove widget')).not.toBeInTheDocument();
  });
});
