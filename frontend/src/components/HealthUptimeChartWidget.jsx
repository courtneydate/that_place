/**
 * HealthUptimeChartWidget — plots device health history as a chart.
 *
 * Three modes controlled by config.chart_type:
 *   online_offline — binary area chart (online=1 / offline=0) from health history API
 *   battery        — line chart of _battery virtual stream readings
 *   signal         — line chart of _signal virtual stream readings
 *
 * Config: { device_id, device_name, chart_type, time_range }
 * Ref: SPEC.md § Feature: Dashboards & Visualisation — Health/Uptime Chart widget
 */
import PropTypes from 'prop-types';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import ReactApexChart from 'react-apexcharts';
import api from '../services/api';
import { useDeviceHealthHistory, useStreamReadings } from '../hooks/useDashboards';
import { colors } from '../theme/colors';
import styles from './HealthUptimeChartWidget.module.css';

/** Resolve { from, to } ISO strings from a time_range preset. */
function resolveTimeRange(timeRange) {
  const now = new Date();
  const msMap = {
    '1h': 60 * 60 * 1000,
    '24h': 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
  };
  const ms = msMap[timeRange] ?? msMap['24h'];
  return {
    from: new Date(now.getTime() - ms).toISOString(),
    to: now.toISOString(),
  };
}

/**
 * @param {object}   props
 * @param {object}   props.config          - Widget config: { device_id, device_name, chart_type, time_range }.
 * @param {number}   props.refetchInterval - Poll interval in ms.
 * @param {boolean}  props.canEdit         - Show action buttons when true.
 * @param {function} props.onRemove        - Called when remove is clicked.
 * @param {function} [props.onEdit]        - Called when edit is clicked.
 */
function HealthUptimeChartWidget({ config = {}, refetchInterval, canEdit, onRemove, onEdit }) {
  const {
    device_id: deviceId,
    device_name: deviceName,
    chart_type: chartType = 'online_offline',
    time_range: timeRange = '24h',
  } = config;

  // Fetch device streams (for battery/signal modes only)
  const { data: deviceStreams = [], isLoading: streamsLoading } = useQuery({
    queryKey: ['device-streams', deviceId],
    queryFn: () => api.get(`/api/v1/devices/${deviceId}/streams/`).then((r) => r.data),
    enabled: !!deviceId && chartType !== 'online_offline',
  });

  const targetKey = chartType === 'battery' ? '_battery' : chartType === 'signal' ? '_signal' : null;
  const targetStream = deviceStreams.find((s) => s.key === targetKey) ?? null;

  // Health history (online_offline mode)
  const {
    data: healthData,
    isLoading: historyLoading,
    isError: historyError,
  } = useDeviceHealthHistory(
    chartType === 'online_offline' ? deviceId : null,
    { time_range: timeRange },
    { refetchInterval },
  );

  // Stream readings (battery / signal modes)
  const rangeParams = useMemo(() => resolveTimeRange(timeRange), [timeRange]);
  const {
    data: streamReadings,
    isLoading: readingsLoading,
    isError: readingsError,
  } = useStreamReadings(
    targetStream?.id ?? null,
    rangeParams,
    { refetchInterval },
  );

  // -----------------------------------------------------------------------
  // Derive chart config + series
  // -----------------------------------------------------------------------

  const isLoading =
    chartType === 'online_offline'
      ? historyLoading
      : streamsLoading || readingsLoading;

  const hasError =
    chartType === 'online_offline'
      ? historyError
      : readingsError;

  const { series, chartOptions, chartType: apexType } = useMemo(() => {
    if (chartType === 'online_offline') {
      const timeline = healthData?.timeline ?? [];
      const seriesData = timeline.map((t) => ({
        x: new Date(t.timestamp).getTime(),
        y: t.is_online ? 1 : 0,
      }));

      return {
        series: [{ name: 'Status', data: seriesData }],
        apexType: 'area',
        chartOptions: {
          chart: { type: 'area', toolbar: { show: false }, animations: { enabled: false } },
          stroke: { curve: 'stepline', width: 1 },
          fill: { type: 'solid', opacity: 0.6 },
          colors: [colors.status.online],
          dataLabels: { enabled: false },
          xaxis: {
            type: 'datetime',
            labels: { style: { colors: colors.text.secondary }, datetimeUTC: false },
          },
          yaxis: {
            min: 0,
            max: 1,
            tickAmount: 1,
            labels: {
              style: { colors: colors.text.secondary },
              formatter: (v) => (v === 1 ? 'Online' : 'Offline'),
            },
          },
          tooltip: {
            x: { format: 'dd MMM HH:mm' },
            y: { formatter: (v) => (v === 1 ? 'Online' : 'Offline') },
          },
          grid: { borderColor: colors.surface.border },
        },
      };
    }

    // battery or signal line chart
    const readings = Array.isArray(streamReadings) ? streamReadings : [];
    const seriesData = readings.map((r) => [new Date(r.timestamp).getTime(), Number(r.value)]);
    const unit = chartType === 'battery' ? '%' : 'dBm';
    const label = chartType === 'battery' ? 'Battery' : 'Signal';

    return {
      series: [{ name: label, data: seriesData }],
      apexType: 'line',
      chartOptions: {
        chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false } },
        stroke: { curve: 'smooth', width: 2 },
        colors: [chartType === 'battery' ? colors.status.online : colors.status.degraded],
        dataLabels: { enabled: false },
        xaxis: {
          type: 'datetime',
          labels: { style: { colors: colors.text.secondary }, datetimeUTC: false },
        },
        yaxis: {
          labels: {
            style: { colors: colors.text.secondary },
            formatter: (v) => `${v}${unit}`,
          },
        },
        tooltip: { x: { format: 'dd MMM HH:mm' } },
        grid: { borderColor: colors.surface.border },
      },
    };
  }, [chartType, healthData, streamReadings]);

  const hasData = series[0]?.data?.length > 0;
  const noStreamMsg =
    !isLoading && !targetStream && chartType !== 'online_offline'
      ? `No ${chartType} stream found for this device.`
      : null;

  const title = deviceName
    ? `${deviceName} — ${chartType === 'online_offline' ? 'Uptime' : chartType === 'battery' ? 'Battery' : 'Signal'}`
    : chartType === 'online_offline' ? 'Uptime' : chartType === 'battery' ? 'Battery' : 'Signal';

  return (
    <div className={styles.card}>
      {canEdit && (
        <div className={styles.actions}>
          {onEdit && <button type="button" className={styles.editBtn} onClick={onEdit} title="Edit widget">✎</button>}
          <button type="button" className={styles.removeBtn} onClick={onRemove} title="Remove widget">×</button>
        </div>
      )}
      <p className={styles.label}>{title}</p>
      <div className={styles.chartArea}>
        {isLoading && <p className={styles.statusMsg}>Loading…</p>}
        {!isLoading && hasError && <p className={styles.statusMsg}>Failed to load data.</p>}
        {!isLoading && noStreamMsg && <p className={styles.statusMsg}>{noStreamMsg}</p>}
        {!isLoading && !hasError && !noStreamMsg && !hasData && (
          <p className={styles.statusMsg}>No data in this time range.</p>
        )}
        {!isLoading && !hasError && !noStreamMsg && hasData && (
          <ReactApexChart
            options={chartOptions}
            series={series}
            type={apexType}
            height={240}
          />
        )}
      </div>
    </div>
  );
}

HealthUptimeChartWidget.propTypes = {
  config: PropTypes.object.isRequired,
  refetchInterval: PropTypes.number,
  canEdit: PropTypes.bool,
  onRemove: PropTypes.func.isRequired,
  onEdit: PropTypes.func,
};

export default HealthUptimeChartWidget;
