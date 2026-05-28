/**
 * Quality badge (Sprint 28).
 *
 * Renders a small coloured chip next to a stream value when the reading's
 * data quality is not `measured`. `measured` is the silent default — only
 * non-measured values get a badge to keep the table quiet.
 *
 * Ref: SPEC.md § Feature: Data Quality Flags
 */
import PropTypes from 'prop-types';

const STYLES = {
  measured: null,
  estimated: { color: '#92400E', background: '#FEF3C7', label: 'estimated' },
  substituted: { color: '#9A3412', background: '#FFEDD5', label: 'substituted' },
  gap: { color: '#7F1D1D', background: '#FECACA', label: 'gap' },
};

function QualityBadge({ quality }) {
  const style = STYLES[quality];
  if (!style) return null;
  return (
    <span
      style={{
        marginLeft: '0.5rem',
        padding: '0.1rem 0.4rem',
        borderRadius: '0.25rem',
        fontSize: '0.7rem',
        fontWeight: 600,
        color: style.color,
        background: style.background,
        textTransform: 'uppercase',
        letterSpacing: '0.025em',
      }}
      aria-label={`data quality: ${style.label}`}
    >
      {style.label}
    </span>
  );
}

QualityBadge.propTypes = {
  quality: PropTypes.string,
};

export default QualityBadge;
