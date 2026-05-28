/**
 * Sprint 28 — QualityBadge tests.
 *
 * The badge is intentionally silent on `measured` (the default) and visible
 * for the three non-default qualities.
 */
import { render, screen } from '@testing-library/react';
import QualityBadge from './QualityBadge';

describe('QualityBadge', () => {
  it('renders nothing for measured quality (the silent default)', () => {
    const { container } = render(<QualityBadge quality="measured" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an unknown quality value', () => {
    const { container } = render(<QualityBadge quality="totally-bogus" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when quality is missing', () => {
    const { container } = render(<QualityBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ['estimated', /estimated/i],
    ['substituted', /substituted/i],
    ['gap', /gap/i],
  ])('renders the %s label', (quality, pattern) => {
    render(<QualityBadge quality={quality} />);
    expect(screen.getByText(pattern)).toBeInTheDocument();
  });

  it('exposes an aria-label for assistive tech', () => {
    render(<QualityBadge quality="gap" />);
    expect(screen.getByLabelText(/data quality: gap/i)).toBeInTheDocument();
  });
});
