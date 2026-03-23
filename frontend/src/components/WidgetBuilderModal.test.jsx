import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithQuery } from '../test-utils';
import WidgetBuilderModal from './WidgetBuilderModal';

jest.mock('../services/api', () => ({
  get: jest.fn((url) => {
    if (url.includes('/sites/')) return Promise.resolve({ data: [] });
    if (url.includes('/devices/')) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: [] });
  }),
}));

const defaultProps = {
  nextOrder: 0,
  onSubmit: jest.fn(),
  onClose: jest.fn(),
};

describe('WidgetBuilderModal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders with value_card selected by default', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    const select = screen.getByRole('combobox', { name: /widget type/i });
    expect(select.value).toBe('value_card');
  });

  it('calls onClose when the × button is clicked', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.click(screen.getByRole('button', { name: '×' }));
    expect(defaultProps.onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Cancel is clicked', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.click(screen.getByText('Cancel'));
    expect(defaultProps.onClose).toHaveBeenCalledTimes(1);
  });

  it('shows validation error for value_card when no stream is selected', async () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add Widget' }));
    await waitFor(() => {
      expect(screen.getByText('Please select a stream.')).toBeInTheDocument();
    });
  });

  it('shows gauge config fields when gauge type is selected', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    const select = screen.getByRole('combobox', { name: /widget type/i });
    fireEvent.change(select, { target: { value: 'gauge' } });
    expect(screen.getByLabelText(/min/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/max/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/warning threshold/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/danger threshold/i)).toBeInTheDocument();
  });

  it('shows validation error for gauge when no stream is selected', async () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'gauge' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Widget' }));
    await waitFor(() => {
      expect(screen.getByText('Please select a stream.')).toBeInTheDocument();
    });
  });

  it('renders gauge config fields with sensible defaults', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'gauge' },
    });
    expect(screen.getByLabelText(/min/i).value).toBe('0');
    expect(screen.getByLabelText(/max/i).value).toBe('100');
    expect(screen.getByLabelText(/warning threshold/i).value).toBe('60');
    expect(screen.getByLabelText(/danger threshold/i).value).toBe('80');
  });

  it('gauge config fields accept user input', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'gauge' },
    });
    fireEvent.change(screen.getByLabelText(/max/i), { target: { value: '200' } });
    expect(screen.getByLabelText(/max/i).value).toBe('200');
  });

  it('shows line chart stream row and time range selector when line_chart is selected', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'line_chart' },
    });
    expect(screen.getByText('+ Add another stream')).toBeInTheDocument();
    expect(screen.getByText('Last hour')).toBeInTheDocument();
    expect(screen.getByText('Custom')).toBeInTheDocument();
  });

  it('adds a second stream row when "+ Add another stream" is clicked', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'line_chart' },
    });
    fireEvent.click(screen.getByText('+ Add another stream'));
    // There should now be two row-level site selects (both say "All sites")
    expect(screen.getAllByText('All sites')).toHaveLength(2);
  });

  it('shows validation error for line_chart when no streams are selected', async () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'line_chart' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Widget' }));
    await waitFor(() => {
      expect(screen.getByText('Add at least one stream.')).toBeInTheDocument();
    });
  });

  it('status_indicator option is enabled', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    const option = screen.getByRole('option', { name: /status indicator/i });
    expect(option).not.toBeDisabled();
  });

  it('selecting status_indicator shows site and device pickers', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'status_indicator' },
    });
    // Site filter and device picker should appear
    expect(screen.getByRole('option', { name: /all sites/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /select a device/i })).toBeInTheDocument();
  });

  it('health_uptime_chart option is enabled', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    const option = screen.getByRole('option', { name: /health.*uptime/i });
    expect(option).not.toBeDisabled();
  });

  it('selecting health_uptime_chart shows chart type options', () => {
    renderWithQuery(<WidgetBuilderModal {...defaultProps} />);
    fireEvent.change(screen.getByRole('combobox', { name: /widget type/i }), {
      target: { value: 'health_uptime_chart' },
    });
    expect(screen.getByRole('option', { name: /online.*offline/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /battery/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /signal/i })).toBeInTheDocument();
  });
});
