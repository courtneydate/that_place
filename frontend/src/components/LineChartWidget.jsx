/**
 * LineChartWidget — multi-stream line chart with optional dual Y-axis.
 *
 * Reads config.streams[] for stream bindings (stream_id, axis, color, label).
 * All streams default to the left Y-axis; streams with axis='right' appear on
 * the right axis. Supports a local time-range override (defaults from widget config,
 * not persisted to the server during this sprint).
 *
 * Implemented with ApexCharts — see SPEC.md § Dashboards & Visualisation.
 */
import { useMemo, useState } from 'react';
import ReactApexChart from 'react-apexcharts';
import { useMultipleStreamReadings } from '../hooks/useDashboards';
import { colors } from '../theme/colors';
import TimeRangeSelector, { presetToRange } from './TimeRangeSelector';
import styles from './LineChartWidget.module.css';

/** Ordered palette for auto-assigned stream colours (falls back when no color in config). */
const STREAM_COLORS = [
  colors.brand.primary,
  colors.status.critical,
  colors.status.degraded,
  colors.brand.secondary,
  colors.neutral[600],
  colors.neutral[400],
];

/** Build API { from, to } params from the current time range state. */
function buildParams(preset, dateFrom, dateTo) {
  if (preset === 'custom') {
    if (!dateFrom || !dateTo) return {};
    return {
      from: new Date(dateFrom).toISOString(),
      to: new Date(dateTo + 'T23:59:59').toISOString(),
    };
  }
  return presetToRange(preset);
}

/**
 * @param {object}   props
 * @param {object}   props.config          - Widget JSONB config: { streams, time_range, date_from, date_to }.
 * @param {number}   props.refetchInterval - Poll interval in ms.
 * @param {boolean}  props.canEdit         - Show remove button when true.
 * @param {function} props.onRemove        - Called when remove is clicked.
 */
function LineChartWidget({ config = {}, refetchInterval, canEdit, onRemove }) {
  const streamConfigs = useMemo(() => config.streams || [], [config.streams]);

  const [preset, setPreset] = useState(config.time_range || '24h');
  const [dateFrom, setDateFrom] = useState(config.date_from || '');
  const [dateTo, setDateTo] = useState(config.date_to || '');

  const params = useMemo(
    () => buildParams(preset, dateFrom, dateTo),
    [preset, dateFrom, dateTo],
  );

  const queryResults = useMultipleStreamReadings(streamConfigs, params, { refetchInterval });

  const isLoading = queryResults.some((r) => r.isLoading);
  const hasError = queryResults.some((r) => r.isError);

  const handleRangeChange = ({ preset: p, dateFrom: df, dateTo: dt }) => {
    setPreset(p);
    setDateFrom(df || '');
    setDateTo(dt || '');
  };

  /** Build ApexCharts series — one entry per stream. */
  const series = useMemo(
    () =>
      streamConfigs.map((sc, i) => {
        const readings = queryResults[i]?.data || [];
        return {
          name: sc.label || `Stream ${sc.stream_id}`,
          data: readings.map((r) => [new Date(r.recorded_at).getTime(), Number(r.value)]),
        };
      }),
    [streamConfigs, queryResults],
  );

  const hasRightAxis = streamConfigs.some((sc) => sc.axis === 'right');
  const hasData = series.some((s) => s.data.length > 0);

  /** Build yaxis config — single object for one axis, array for dual. */
  const yaxisConfig = useMemo(() => {
    if (!hasRightAxis) {
      return { labels: { style: { colors: colors.text.secondary } } };
    }
    return streamConfigs.map((sc, i) => ({
      seriesName: series[i]?.name,
      opposite: sc.axis === 'right',
      labels: {
        style: { colors: [sc.color || STREAM_COLORS[i % STREAM_COLORS.length]] },
      },
      axisBorder: {
        show: true,
        color: sc.color || STREAM_COLORS[i % STREAM_COLORS.length],
      },
    }));
  }, [streamConfigs, series, hasRightAxis]);

  const chartOptions = {
    chart: {
      type: 'line',
      toolbar: { show: false },
      animations: { enabled: false },
      background: 'transparent',
    },
    colors: streamConfigs.map((sc, i) => sc.color || STREAM_COLORS[i % STREAM_COLORS.length]),
    stroke: { curve: 'smooth', width: 2 },
    xaxis: {
      type: 'datetime',
      labels: {
        style: { colors: colors.text.secondary },
        datetimeUTC: false,
      },
    },
    yaxis: yaxisConfig,
    legend: { show: streamConfigs.length > 1, position: 'top' },
    tooltip: { x: { format: 'dd MMM HH:mm' }, shared: true },
    grid: { borderColor: colors.surface.border },
  };

  return (
    <div className={styles.card}>
      {canEdit && (
        <button className={styles.removeBtn} onClick={onRemove} title="Remove widget">
          ×
        </button>
      )}
      <div className={styles.header}>
        <TimeRangeSelector
          preset={preset}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onChange={handleRangeChange}
        />
      </div>
      <div className={styles.chartArea}>
        {isLoading && <p className={styles.statusMsg}>Loading…</p>}
        {!isLoading && hasError && <p className={styles.statusMsg}>Failed to load data.</p>}
        {!isLoading && !hasError && !hasData && (
          <p className={styles.statusMsg}>No readings in this time range.</p>
        )}
        {!isLoading && !hasError && hasData && (
          <ReactApexChart
            options={chartOptions}
            series={series}
            type="line"
            height={260}
          />
        )}
      </div>
    </div>
  );
}

export default LineChartWidget;
