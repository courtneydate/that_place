/**
 * GaugeWidget — radial gauge for a single stream with 3 threshold bands.
 *
 * Bands: normal (green) / warning (yellow) / danger (red).
 * Boundary values are configurable: warning_threshold and danger_threshold.
 * The gauge arc spans from config.min to config.max.
 *
 * Implemented with ApexCharts radialBar — see SPEC.md § Dashboards & Visualisation.
 */
import PropTypes from 'prop-types';
import { useQuery } from '@tanstack/react-query';
import ReactApexChart from 'react-apexcharts';
import api from '../services/api';
import { useStreamReadings } from '../hooks/useDashboards';
import { colors } from '../theme/colors';
import styles from './GaugeWidget.module.css';

/** Return the semantic band colour for a given value. */
function bandColor(value, warningThreshold, dangerThreshold) {
  if (value >= dangerThreshold) return colors.status.critical;
  if (value >= warningThreshold) return colors.status.degraded;
  return colors.status.online;
}

/**
 * @param {object}   props
 * @param {object}   props.config          - Widget JSONB config.
 * @param {number}   props.refetchInterval - Poll interval in ms.
 * @param {boolean}  props.canEdit         - Show action buttons when true.
 * @param {function} props.onRemove        - Called when remove is clicked.
 * @param {function} [props.onEdit]        - Called when edit is clicked.
 */
function GaugeWidget({ config = {}, refetchInterval, canEdit, onRemove, onEdit }) {
  const {
    stream_id: streamId,
    min = 0,
    max = 100,
    warning_threshold: warningThreshold = 60,
    danger_threshold: dangerThreshold = 80,
    label_override: labelOverride,
  } = config;

  const { data: stream } = useQuery({
    queryKey: ['stream', streamId],
    queryFn: () => api.get(`/api/v1/streams/${streamId}/`).then((r) => r.data),
    enabled: !!streamId,
    refetchInterval,
  });

  const { data: readings, isLoading, isError } = useStreamReadings(
    streamId,
    { limit: 1 },
    { refetchInterval },
  );

  const latestReading = readings?.[0] ?? null;
  const currentValue = latestReading ? Number(latestReading.value) : null;

  const percentage =
    currentValue !== null
      ? Math.min(100, Math.max(0, ((currentValue - min) / (max - min)) * 100))
      : 0;

  const gaugeColor =
    currentValue !== null
      ? bandColor(currentValue, warningThreshold, dangerThreshold)
      : colors.neutral[300];

  const label = labelOverride || stream?.label || stream?.key || `Stream ${streamId}`;
  const unit = stream?.unit || '';

  const displayValue =
    currentValue !== null ? `${currentValue}${unit ? ` ${unit}` : ''}` : '—';

  const chartOptions = {
    chart: {
      type: 'radialBar',
      sparkline: { enabled: true },
    },
    plotOptions: {
      radialBar: {
        startAngle: -135,
        endAngle: 135,
        track: {
          background: colors.neutral[200],
          strokeWidth: '97%',
        },
        hollow: { size: '60%' },
        dataLabels: {
          name: { show: false },
          value: {
            offsetY: -2,
            fontSize: '1.5rem',
            fontWeight: '600',
            color: colors.text.primary,
            formatter: () => displayValue,
          },
        },
      },
    },
    fill: { colors: [gaugeColor] },
    stroke: { lineCap: 'round' },
  };

  return (
    <div className={styles.card}>
      {canEdit && (
        <div className={styles.widgetActions}>
          {onEdit && <button className={styles.editBtn} onClick={onEdit} title="Edit widget">✎</button>}
          <button className={styles.removeBtn} onClick={onRemove} title="Remove widget">×</button>
        </div>
      )}
      <p className={styles.label}>{label}</p>

      {isLoading && <p className={styles.statusMsg}>Loading…</p>}
      {!isLoading && isError && <p className={styles.statusMsg}>Failed to load.</p>}
      {!isLoading && !isError && (
        <>
          <ReactApexChart
            options={chartOptions}
            series={[parseFloat(percentage.toFixed(1))]}
            type="radialBar"
            height={200}
          />
          <div className={styles.range}>
            <span>{min}{unit ? ` ${unit}` : ''}</span>
            <span>{max}{unit ? ` ${unit}` : ''}</span>
          </div>
          <div className={styles.bands}>
            <span className={styles.bandNormal}>▬ Normal &lt;{warningThreshold}</span>
            <span className={styles.bandWarning}>▬ Warning &lt;{dangerThreshold}</span>
            <span className={styles.bandDanger}>▬ Danger ≥{dangerThreshold}</span>
          </div>
        </>
      )}
    </div>
  );
}

GaugeWidget.propTypes = {
  config: PropTypes.object.isRequired,
  refetchInterval: PropTypes.number,
  canEdit: PropTypes.bool,
  onRemove: PropTypes.func.isRequired,
  onEdit: PropTypes.func,
};

export default GaugeWidget;
