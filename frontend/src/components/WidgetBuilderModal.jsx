/**
 * WidgetBuilderModal — modal for adding or editing a dashboard widget.
 *
 * Supports all five widget types:
 *   value_card           — single stream picker
 *   gauge                — single stream picker + min/max/threshold config
 *   line_chart           — multi-stream picker (per-stream axis toggle) + time range
 *   status_indicator     — single stream picker + device type mapping preview
 *   health_uptime_chart  — device picker + chart type + time range
 *
 * Edit mode: pass an `editingWidget` prop to pre-populate all fields.
 * The widget type selector is locked in edit mode — type cannot be changed.
 */
import PropTypes from 'prop-types';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { colors } from '../theme/colors';
import TimeRangeSelector from './TimeRangeSelector';
import styles from './WidgetBuilderModal.module.css';

const WIDGET_TYPES = [
  { value: 'value_card', label: 'Value Card' },
  { value: 'line_chart', label: 'Line Chart' },
  { value: 'gauge', label: 'Gauge' },
  { value: 'status_indicator', label: 'Status Indicator' },
  { value: 'health_uptime_chart', label: 'Health / Uptime Chart' },
];

const HEALTH_CHART_TYPES = [
  { value: 'online_offline', label: 'Online / Offline History' },
  { value: 'battery', label: 'Battery Level' },
  { value: 'signal', label: 'Signal Strength' },
];

const HEALTH_TIME_RANGES = [
  { value: '1h', label: 'Last hour' },
  { value: '24h', label: '24 hours' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
];

/** Ordered palette for auto-assigning stream line colours. */
const STREAM_COLORS = [
  colors.brand.primary,
  colors.status.critical,
  colors.status.degraded,
  colors.brand.secondary,
  colors.neutral[600],
  colors.neutral[400],
];

// ---------------------------------------------------------------------------
// Internal hooks — scoped to this modal
// ---------------------------------------------------------------------------

function useSiteList() {
  return useQuery({
    queryKey: ['sites'],
    queryFn: () => api.get('/api/v1/sites/').then((r) => r.data),
  });
}

function useDeviceList() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: () => api.get('/api/v1/devices/').then((r) => r.data),
  });
}

function useDeviceStreamList(deviceId) {
  return useQuery({
    queryKey: ['device-streams', deviceId],
    queryFn: () => api.get(`/api/v1/devices/${deviceId}/streams/`).then((r) => r.data),
    enabled: !!deviceId,
  });
}

function useAllDeviceTypes() {
  return useQuery({
    queryKey: ['device-types'],
    queryFn: () => api.get('/api/v1/device-types/').then((r) => r.data),
  });
}

// ---------------------------------------------------------------------------
// StreamRow — one row in the line-chart multi-stream picker
// ---------------------------------------------------------------------------

/**
 * A single stream-selection row for the line chart builder.
 * Manages its own stream query so each row can independently load streams.
 *
 * @param {object}   props
 * @param {object}   props.row           - { id, siteId, deviceId, streamId, axis, preLabel? }
 * @param {number}   props.index         - Row index (0-based).
 * @param {Array}    props.allDevices    - Full device list from parent.
 * @param {Array}    props.sites         - Full site list from parent.
 * @param {function} props.onChange      - Called with updated row object.
 * @param {function} [props.onRemove]    - Called when the row remove button is clicked.
 */
function StreamRow({ row, index, allDevices, sites, onChange, onRemove }) {
  const { data: streams = [] } = useDeviceStreamList(
    row.deviceId || null,
  );

  const devicesForSite = row.siteId
    ? allDevices.filter((d) => String(d.site) === String(row.siteId) && d.status === 'active')
    : allDevices.filter((d) => d.status === 'active');

  const handleSite = (e) => onChange({ ...row, siteId: e.target.value, deviceId: '', streamId: '', preLabel: '' });
  const handleDevice = (e) => onChange({ ...row, deviceId: e.target.value, streamId: '', preLabel: '' });
  const handleStream = (e) => {
    const selected = streams.find((s) => String(s.id) === e.target.value);
    onChange({
      ...row,
      streamId: e.target.value,
      streamLabel: selected?.label || selected?.key || '',
      preLabel: '',
    });
  };
  const handleAxis = (e) => onChange({ ...row, axis: e.target.value });

  return (
    <div className={styles.streamRowCard}>
      <div className={styles.streamRowHeader}>
        <span className={styles.streamRowLabel}>Stream {index + 1}</span>
        {onRemove && (
          <button type="button" className={styles.rowRemoveBtn} onClick={onRemove}>×</button>
        )}
      </div>
      <div className={styles.streamRowTop}>
        <select className={styles.select} value={row.siteId} onChange={handleSite}>
          <option value="">All sites</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <select className={styles.select} value={row.deviceId} onChange={handleDevice}>
          <option value="">— Device —</option>
          {devicesForSite.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </div>
      <div className={styles.streamRowBottom}>
        <select
          className={styles.select}
          value={row.streamId}
          onChange={handleStream}
          disabled={!row.deviceId && !row.preLabel}
        >
          {/* Show pre-populated label when no device is selected yet (edit mode) */}
          {!row.deviceId && row.preLabel && (
            <option value={row.streamId}>{row.preLabel}</option>
          )}
          {row.deviceId && (
            <>
              <option value="">— Stream —</option>
              {streams.filter((s) => s.display_enabled).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label || s.key}{s.unit ? ` (${s.unit})` : ''}
                </option>
              ))}
            </>
          )}
          {!row.deviceId && !row.preLabel && <option value="">— Stream —</option>}
        </select>
        {index > 0 && (
          <select className={styles.selectNarrow} value={row.axis} onChange={handleAxis}>
            <option value="left">Left axis</option>
            <option value="right">Right axis</option>
          </select>
        )}
      </div>
    </div>
  );
}

StreamRow.propTypes = {
  row: PropTypes.object.isRequired,
  index: PropTypes.number.isRequired,
  allDevices: PropTypes.array.isRequired,
  sites: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
  onRemove: PropTypes.func,
};

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

/**
 * @param {number}   [props.nextOrder]      - Position order for a new widget.
 * @param {object}   [props.editingWidget]  - Existing widget to edit (null = add mode).
 * @param {function} props.onSubmit         - Called with widget payload on confirm.
 * @param {function} props.onClose          - Called when the modal is dismissed.
 */
function WidgetBuilderModal({ nextOrder = 0, editingWidget = null, onSubmit, onClose }) {
  const isEditMode = !!editingWidget;

  // --- shared state ---
  const [widgetType, setWidgetType] = useState(editingWidget?.widget_type || 'value_card');
  const [error, setError] = useState('');

  // --- single-stream state (value_card + gauge + status_indicator) ---
  const [siteId, setSiteId] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [streamId, setStreamId] = useState('');

  // --- gauge config ---
  const [gaugeMin, setGaugeMin] = useState('0');
  const [gaugeMax, setGaugeMax] = useState('100');
  const [gaugeWarn, setGaugeWarn] = useState('60');
  const [gaugeDanger, setGaugeDanger] = useState('80');
  const [gaugeLabelOverride, setGaugeLabelOverride] = useState('');

  // --- line chart state ---
  const [streamRows, setStreamRows] = useState([
    { id: 0, siteId: '', deviceId: '', streamId: '', streamLabel: '', axis: 'left', preLabel: '' },
  ]);
  const [linePreset, setLinePreset] = useState('24h');
  const [lineDateFrom, setLineDateFrom] = useState('');
  const [lineDateTo, setLineDateTo] = useState('');

  // --- status_indicator state ---
  const [statusDeviceTypeId, setStatusDeviceTypeId] = useState('');

  // --- health_uptime_chart state ---
  const [healthSiteId, setHealthSiteId] = useState('');
  const [healthDeviceId, setHealthDeviceId] = useState('');
  const [healthChartType, setHealthChartType] = useState('online_offline');
  const [healthTimeRange, setHealthTimeRange] = useState('24h');

  // --- data ---
  const { data: sites = [], isLoading: sitesLoading } = useSiteList();
  const { data: allDevices = [], isLoading: devicesLoading } = useDeviceList();
  const { data: streams = [], isLoading: streamsLoading } = useDeviceStreamList(deviceId || null);
  const { data: allDeviceTypes = [] } = useAllDeviceTypes();

  // Pre-load stream details when editing value_card / gauge / status_indicator
  // (so we can resolve device_id and pre-populate the device selector)
  const preloadStreamId =
    isEditMode &&
    (widgetType === 'value_card' || widgetType === 'gauge' || widgetType === 'status_indicator')
      ? Number(streamId) || null
      : null;

  const { data: preloadedStream } = useQuery({
    queryKey: ['stream', preloadStreamId],
    queryFn: () => api.get(`/api/v1/streams/${preloadStreamId}/`).then((r) => r.data),
    enabled: !!preloadStreamId && !deviceId,
  });

  // Auto-populate device/site from pre-loaded stream (edit mode)
  useEffect(() => {
    if (!preloadedStream || deviceId) return;
    setDeviceId(String(preloadedStream.device));
    const device = allDevices.find((d) => d.id === preloadedStream.device);
    if (device) setSiteId(String(device.site));
  }, [preloadedStream, deviceId, allDevices]);

  // Derive device_type_id for status_indicator when device is selected (add mode)
  useEffect(() => {
    if (widgetType !== 'status_indicator' || isEditMode || !deviceId) return;
    const device = allDevices.find((d) => String(d.id) === String(deviceId));
    if (device?.device_type) setStatusDeviceTypeId(String(device.device_type));
  }, [deviceId, allDevices, widgetType, isEditMode]);

  // Pre-populate all fields when in edit mode
  useEffect(() => {
    if (!editingWidget) return;
    const { widget_type, config = {}, stream_ids = [] } = editingWidget;
    setWidgetType(widget_type);
    setError('');

    if (widget_type === 'value_card') {
      setStreamId(String(stream_ids[0] || ''));
    }

    if (widget_type === 'gauge') {
      setStreamId(String(config.stream_id || stream_ids[0] || ''));
      setGaugeMin(String(config.min ?? '0'));
      setGaugeMax(String(config.max ?? '100'));
      setGaugeWarn(String(config.warning_threshold ?? '60'));
      setGaugeDanger(String(config.danger_threshold ?? '80'));
      setGaugeLabelOverride(config.label_override || '');
    }

    if (widget_type === 'line_chart') {
      const configStreams = config.streams || [];
      if (configStreams.length > 0) {
        setStreamRows(
          configStreams.map((s, i) => ({
            id: i,
            siteId: '',
            deviceId: '',
            streamId: String(s.stream_id),
            streamLabel: s.label || '',
            axis: s.axis || 'left',
            color: s.color || STREAM_COLORS[i % STREAM_COLORS.length],
            preLabel: s.label || `Stream ${s.stream_id}`,
          })),
        );
      }
      setLinePreset(config.time_range || '24h');
      setLineDateFrom(config.date_from || '');
      setLineDateTo(config.date_to || '');
    }

    if (widget_type === 'status_indicator') {
      setStreamId(String(config.stream_id || stream_ids[0] || ''));
      setStatusDeviceTypeId(String(config.device_type_id || ''));
    }

    if (widget_type === 'health_uptime_chart') {
      setHealthDeviceId(String(config.device_id || ''));
      setHealthChartType(config.chart_type || 'online_offline');
      setHealthTimeRange(config.time_range || '24h');
      const device = allDevices.find((d) => d.id === config.device_id);
      if (device) setHealthSiteId(String(device.site));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingWidget?.id]);

  // Reset single-stream fields when type changes (add mode only)
  const handleTypeChange = (t) => {
    if (isEditMode) return;
    setWidgetType(t);
    setError('');
    setSiteId('');
    setDeviceId('');
    setStreamId('');
    setStatusDeviceTypeId('');
    setHealthSiteId('');
    setHealthDeviceId('');
  };

  // --- line chart row helpers ---
  const addStreamRow = () => {
    setStreamRows((prev) => [
      ...prev,
      { id: Date.now(), siteId: '', deviceId: '', streamId: '', streamLabel: '', axis: 'left', preLabel: '' },
    ]);
  };

  const updateStreamRow = (id, updated) => {
    setStreamRows((prev) => prev.map((r) => (r.id === id ? updated : r)));
  };

  const removeStreamRow = (id) => {
    setStreamRows((prev) => prev.filter((r) => r.id !== id));
  };

  const handleLineRangeChange = ({ preset, dateFrom, dateTo }) => {
    setLinePreset(preset);
    setLineDateFrom(dateFrom || '');
    setLineDateTo(dateTo || '');
  };

  // Devices filtered by site for health/uptime picker
  const healthDevicesForSite = healthSiteId
    ? allDevices.filter((d) => String(d.site) === String(healthSiteId) && d.status === 'active')
    : allDevices.filter((d) => d.status === 'active');

  // Status indicator: preview the mappings for the selected stream key
  const selectedStreamObj = streams.find((s) => String(s.id) === String(streamId));
  const previewDeviceType = allDeviceTypes.find((dt) => String(dt.id) === String(statusDeviceTypeId));
  const statusMappingPreview =
    selectedStreamObj && previewDeviceType
      ? previewDeviceType.status_indicator_mappings?.[selectedStreamObj.key] || []
      : [];

  // --- submit ---
  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');
    const position = isEditMode ? editingWidget.position : { order: nextOrder };

    if (widgetType === 'value_card') {
      if (!streamId) { setError('Please select a stream.'); return; }
      onSubmit({
        widget_type: 'value_card',
        stream_ids: [Number(streamId)],
        config: {},
        position,
      });
      return;
    }

    if (widgetType === 'gauge') {
      if (!streamId) { setError('Please select a stream.'); return; }
      const min = Number(gaugeMin);
      const max = Number(gaugeMax);
      const warn = Number(gaugeWarn);
      const danger = Number(gaugeDanger);
      if (min >= max) { setError('Min must be less than Max.'); return; }
      if (warn <= min || warn >= max) { setError('Warning threshold must be between Min and Max.'); return; }
      if (danger <= warn || danger > max) { setError('Danger threshold must be above Warning and ≤ Max.'); return; }
      onSubmit({
        widget_type: 'gauge',
        stream_ids: [Number(streamId)],
        config: {
          stream_id: Number(streamId),
          min,
          max,
          warning_threshold: warn,
          danger_threshold: danger,
          label_override: gaugeLabelOverride.trim() || null,
        },
        position,
      });
      return;
    }

    if (widgetType === 'line_chart') {
      const validRows = streamRows.filter((r) => r.streamId);
      if (validRows.length === 0) { setError('Add at least one stream.'); return; }
      const streamConfigs = validRows.map((r, i) => ({
        stream_id: Number(r.streamId),
        axis: i === 0 ? 'left' : r.axis,
        color: r.color || STREAM_COLORS[i % STREAM_COLORS.length],
        label: r.streamLabel || r.preLabel || `Stream ${r.streamId}`,
      }));
      const timeConfig =
        linePreset === 'custom'
          ? { time_range: 'custom', date_from: lineDateFrom, date_to: lineDateTo }
          : { time_range: linePreset };
      onSubmit({
        widget_type: 'line_chart',
        stream_ids: streamConfigs.map((s) => s.stream_id),
        config: { streams: streamConfigs, ...timeConfig },
        position,
      });
      return;
    }

    if (widgetType === 'status_indicator') {
      if (!streamId) { setError('Please select a stream.'); return; }
      const resolvedDtId =
        statusDeviceTypeId ||
        String(allDevices.find((d) => String(d.id) === String(deviceId))?.device_type || '');
      if (!resolvedDtId) { setError('Could not resolve device type. Please re-select the device.'); return; }
      onSubmit({
        widget_type: 'status_indicator',
        stream_ids: [Number(streamId)],
        config: {
          stream_id: Number(streamId),
          device_type_id: Number(resolvedDtId),
        },
        position,
      });
      return;
    }

    if (widgetType === 'health_uptime_chart') {
      if (!healthDeviceId) { setError('Please select a device.'); return; }
      const device = allDevices.find((d) => String(d.id) === String(healthDeviceId));
      onSubmit({
        widget_type: 'health_uptime_chart',
        stream_ids: [],
        config: {
          device_id: Number(healthDeviceId),
          device_name: device?.name || '',
          chart_type: healthChartType,
          time_range: healthTimeRange,
        },
        position,
      });
    }
  };

  const devicesForSite = siteId
    ? allDevices.filter((d) => String(d.site) === String(siteId) && d.status === 'active')
    : allDevices.filter((d) => d.status === 'active');

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>{isEditMode ? 'Edit Widget' : 'Add Widget'}</h2>
          <button className={styles.closeBtn} onClick={onClose}>×</button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          {/* Widget type */}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="widget-type">Widget Type</label>
            <select
              id="widget-type"
              className={styles.select}
              value={widgetType}
              onChange={(e) => handleTypeChange(e.target.value)}
              disabled={isEditMode}
            >
              {WIDGET_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* ---- value_card, gauge, status_indicator: single stream picker ---- */}
          {(widgetType === 'value_card' || widgetType === 'gauge' || widgetType === 'status_indicator') && (
            <>
              <div className={styles.field}>
                <label className={styles.label}>Filter by Site (optional)</label>
                <select
                  className={styles.select}
                  value={siteId}
                  onChange={(e) => { setSiteId(e.target.value); setDeviceId(''); setStreamId(''); }}
                  disabled={sitesLoading}
                >
                  <option value="">All sites</option>
                  {sites.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Device</label>
                <select
                  className={styles.select}
                  value={deviceId}
                  onChange={(e) => { setDeviceId(e.target.value); setStreamId(''); }}
                  disabled={devicesLoading}
                >
                  <option value="">— Select a device —</option>
                  {devicesForSite.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Stream</label>
                <select
                  className={styles.select}
                  value={streamId}
                  onChange={(e) => setStreamId(e.target.value)}
                  disabled={!deviceId || streamsLoading}
                >
                  <option value="">— Select a stream —</option>
                  {streams.filter((s) => s.display_enabled).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label || s.key}{s.unit ? ` (${s.unit})` : ''}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}

          {/* ---- gauge: config fields ---- */}
          {widgetType === 'gauge' && (
            <>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-min">Min</label>
                  <input id="gauge-min" type="number" className={styles.input} value={gaugeMin} onChange={(e) => setGaugeMin(e.target.value)} />
                </div>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-max">Max</label>
                  <input id="gauge-max" type="number" className={styles.input} value={gaugeMax} onChange={(e) => setGaugeMax(e.target.value)} />
                </div>
              </div>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-warn">Warning threshold</label>
                  <input id="gauge-warn" type="number" className={styles.input} value={gaugeWarn} onChange={(e) => setGaugeWarn(e.target.value)} />
                </div>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-danger">Danger threshold</label>
                  <input id="gauge-danger" type="number" className={styles.input} value={gaugeDanger} onChange={(e) => setGaugeDanger(e.target.value)} />
                </div>
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor="gauge-label">Label override (optional)</label>
                <input
                  id="gauge-label"
                  type="text"
                  className={styles.input}
                  value={gaugeLabelOverride}
                  onChange={(e) => setGaugeLabelOverride(e.target.value)}
                  placeholder="Defaults to stream label"
                />
              </div>
            </>
          )}

          {/* ---- status_indicator: mapping preview ---- */}
          {widgetType === 'status_indicator' && statusMappingPreview.length > 0 && (
            <div className={styles.infoBox}>
              <p className={styles.infoBoxTitle}>Status mappings for this stream:</p>
              <div className={styles.mappingList}>
                {statusMappingPreview.map((m) => (
                  <span key={m.value} className={styles.mappingEntry}>
                    <span className={styles.mappingDot} style={{ backgroundColor: m.color }} />
                    {m.label} ({m.value})
                  </span>
                ))}
              </div>
            </div>
          )}
          {widgetType === 'status_indicator' && streamId && statusMappingPreview.length === 0 && previewDeviceType && (
            <div className={styles.infoBox}>
              <p className={styles.infoBoxTitle}>
                No status mappings configured for this stream on the device type.
                A Fieldmouse Admin can add them in the Device Type Library.
              </p>
            </div>
          )}

          {/* ---- line_chart: multi-stream picker + time range ---- */}
          {widgetType === 'line_chart' && (
            <>
              <div className={styles.field}>
                <label className={styles.label}>Streams</label>
                <div className={styles.streamRowList}>
                  {streamRows.map((row, index) => (
                    <StreamRow
                      key={row.id}
                      row={row}
                      index={index}
                      allDevices={allDevices}
                      sites={sites}
                      onChange={(updated) => updateStreamRow(row.id, updated)}
                      onRemove={streamRows.length > 1 ? () => removeStreamRow(row.id) : null}
                    />
                  ))}
                </div>
                {streamRows.length < 6 && (
                  <button type="button" className={styles.addStreamBtn} onClick={addStreamRow}>
                    + Add another stream
                  </button>
                )}
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Time range</label>
                <TimeRangeSelector
                  preset={linePreset}
                  dateFrom={lineDateFrom}
                  dateTo={lineDateTo}
                  onChange={handleLineRangeChange}
                />
              </div>
            </>
          )}

          {/* ---- health_uptime_chart: device + chart type + time range ---- */}
          {widgetType === 'health_uptime_chart' && (
            <>
              <div className={styles.field}>
                <label className={styles.label}>Filter by Site (optional)</label>
                <select
                  className={styles.select}
                  value={healthSiteId}
                  onChange={(e) => { setHealthSiteId(e.target.value); setHealthDeviceId(''); }}
                  disabled={sitesLoading}
                >
                  <option value="">All sites</option>
                  {sites.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Device</label>
                <select
                  className={styles.select}
                  value={healthDeviceId}
                  onChange={(e) => setHealthDeviceId(e.target.value)}
                  disabled={devicesLoading}
                >
                  <option value="">— Select a device —</option>
                  {healthDevicesForSite.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Chart Type</label>
                <select
                  className={styles.select}
                  value={healthChartType}
                  onChange={(e) => setHealthChartType(e.target.value)}
                >
                  {HEALTH_CHART_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Time Range</label>
                <select
                  className={styles.select}
                  value={healthTimeRange}
                  onChange={(e) => setHealthTimeRange(e.target.value)}
                >
                  {HEALTH_TIME_RANGES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          {error && <p className={styles.error}>{error}</p>}

          <div className={styles.actions}>
            <button type="submit" className={styles.primaryButton}>
              {isEditMode ? 'Save Changes' : 'Add Widget'}
            </button>
            <button type="button" className={styles.secondaryButton} onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

WidgetBuilderModal.propTypes = {
  nextOrder: PropTypes.number,
  editingWidget: PropTypes.object,
  onSubmit: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default WidgetBuilderModal;
