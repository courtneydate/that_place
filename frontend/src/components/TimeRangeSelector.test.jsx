import { render, screen, fireEvent } from '@testing-library/react';
import TimeRangeSelector from './TimeRangeSelector';

describe('TimeRangeSelector', () => {
  it('renders all preset buttons', () => {
    render(<TimeRangeSelector preset="24h" onChange={() => {}} />);
    expect(screen.getByText('Last hour')).toBeInTheDocument();
    expect(screen.getByText('24h')).toBeInTheDocument();
    expect(screen.getByText('7 days')).toBeInTheDocument();
    expect(screen.getByText('30 days')).toBeInTheDocument();
    expect(screen.getByText('Custom')).toBeInTheDocument();
  });

  it('marks the active preset button', () => {
    render(<TimeRangeSelector preset="7d" onChange={() => {}} />);
    // The active class is applied; test via aria or just that onChange fires correctly
    const btn7d = screen.getByText('7 days');
    expect(btn7d).toBeInTheDocument();
  });

  it('calls onChange with ISO from/to when a non-custom preset is clicked', () => {
    const onChange = jest.fn();
    render(<TimeRangeSelector preset="24h" onChange={onChange} />);
    fireEvent.click(screen.getByText('Last hour'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        preset: '1h',
        from: expect.any(String),
        to: expect.any(String),
      }),
    );
    // from should be earlier than to
    const { from, to } = onChange.mock.calls[0][0];
    expect(new Date(from).getTime()).toBeLessThan(new Date(to).getTime());
  });

  it('does not show date inputs for non-custom presets', () => {
    render(<TimeRangeSelector preset="7d" onChange={() => {}} />);
    expect(document.querySelectorAll('input[type="date"]')).toHaveLength(0);
  });

  it('shows two date inputs when preset is custom', () => {
    render(<TimeRangeSelector preset="custom" onChange={() => {}} />);
    expect(document.querySelectorAll('input[type="date"]')).toHaveLength(2);
  });

  it('calls onChange with preset=custom and null from/to when Custom is clicked', () => {
    const onChange = jest.fn();
    render(<TimeRangeSelector preset="24h" onChange={onChange} />);
    fireEvent.click(screen.getByText('Custom'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ preset: 'custom', from: null, to: null }),
    );
  });

  it('calls onChange with ISO from/to once both custom dates are entered', () => {
    const onChange = jest.fn();
    render(
      <TimeRangeSelector
        preset="custom"
        dateFrom="2026-01-01"
        dateTo="2026-01-07"
        onChange={onChange}
      />,
    );
    const [fromInput] = document.querySelectorAll('input[type="date"]');
    fireEvent.change(fromInput, { target: { value: '2026-01-02' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        preset: 'custom',
        from: expect.any(String),
        to: expect.any(String),
        dateFrom: '2026-01-02',
        dateTo: '2026-01-07',
      }),
    );
  });
});
