/**
 * WidgetBuilderModal — step-through modal for adding a widget to a dashboard.
 *
 * Supports three widget types:
 *   value_card  — single stream picker
 *   gauge       — single stream picker + min/max/threshold config
 *   line_chart  — multi-stream picker (with per-stream axis toggle) + time range
 *
 * Status indicator and health/uptime chart are deferred to Sprint 13.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { colors } from '../theme/colors';
import TimeRangeSelector from './TimeRangeSelector';
import styles from './WidgetBuilderModal.module.css';

const WIDGET_TYPES = [
  { value: 'value_card', label: 'Value Card' },
  { value: 'line_chart', label: 'Line Chart' },
  { value: 'gauge', label: 'Gauge' },
  { value: 'status_indicator', label: 'Status Indicator (Sprint 13)', disabled: true },
  { value: 'health_uptime_chart', label: 'Health / Uptime Chart (Sprint 13)', disabled: true },
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

// ---------------------------------------------------------------------------
// StreamRow — one row in the line-chart multi-stream picker
// ---------------------------------------------------------------------------

/**
 * A single stream-selection row for the line chart builder.
 * Manages its own stream query so each row can independently load streams.
 *
 * @param {object}   props
 * @param {object}   props.row           - { id, siteId, deviceId, streamId, axis }
 * @param {number}   props.index         - Row index (0-based); axis toggle shown for index > 0.
 * @param {Array}    props.allDevices    - Full device list from parent.
 * @param {Array}    props.sites         - Full site list from parent.
 * @param {function} props.onChange      - Called with updated row object.
 * @param {function} [props.onRemove]    - Called when the row remove button is clicked.
 */
function StreamRow({ row, index, allDevices, sites, onChange, onRemove }) {
  const { data: streams = [], isLoading: streamsLoading } = useDeviceStreamList(
    row.deviceId || null,
  );

  const devicesForSite = row.siteId
    ? allDevices.filter((d) => String(d.site) === String(row.siteId) && d.status === 'active')
    : allDevices.filter((d) => d.status === 'active');

  const handleSite = (e) => onChange({ ...row, siteId: e.target.value, deviceId: '', streamId: '' });
  const handleDevice = (e) => onChange({ ...row, deviceId: e.target.value, streamId: '' });
  const handleStream = (e) => {
    const selected = streams.find((s) => String(s.id) === e.target.value);
    onChange({
      ...row,
      streamId: e.target.value,
      streamLabel: selected?.label || selected?.key || '',
    });
  };
  const handleAxis = (e) => onChange({ ...row, axis: e.target.value });

  return (
    <div className={styles.streamRow}>
      <div className={styles.streamRowSelects}>
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
        <select
          className={styles.select}
          value={row.streamId}
          onChange={handleStream}
          disabled={!row.deviceId || streamsLoading}
        >
          <option value="">— Stream —</option>
          {streams.filter((s) => s.display_enabled).map((s) => (
            <option key={s.id} value={s.id}>
              {s.label || s.key}{s.unit ? ` (${s.unit})` : ''}
            </option>
          ))}
        </select>
        {index > 0 && (
          <select className={styles.selectNarrow} value={row.axis} onChange={handleAxis}>
            <option value="left">Left axis</option>
            <option value="right">Right axis</option>
          </select>
        )}
      </div>
      {onRemove && (
        <button type="button" className={styles.rowRemoveBtn} onClick={onRemove}>×</button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

/**
 * @param {object}   props
 * @param {number}   props.dashboardId  - Parent dashboard PK.
 * @param {number}   props.nextOrder    - Position order for the new widget.
 * @param {function} props.onSubmit     - Called with widget payload when confirmed.
 * @param {function} props.onClose      - Called when the modal is dismissed.
 */
function WidgetBuilderModal({ nextOrder, onSubmit, onClose }) {
  // --- shared state ---
  const [widgetType, setWidgetType] = useState('value_card');
  const [error, setError] = useState('');

  // --- single-stream state (value_card + gauge) ---
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
    { id: 0, siteId: '', deviceId: '', streamId: '', streamLabel: '', axis: 'left' },
  ]);
  const [linePreset, setLinePreset] = useState('24h');
  const [lineDateFrom, setLineDateFrom] = useState('');
  const [lineDateTo, setLineDateTo] = useState('');

  const { data: sites = [], isLoading: sitesLoading } = useSiteList();
  const { data: allDevices = [], isLoading: devicesLoading } = useDeviceList();
  const { data: streams = [], isLoading: streamsLoading } = useDeviceStreamList(deviceId || null);

  const devicesForSite = siteId
    ? allDevices.filter((d) => String(d.site) === String(siteId) && d.status === 'active')
    : allDevices.filter((d) => d.status === 'active');

  // Reset single-stream fields when type changes
  const handleTypeChange = (t) => {
    setWidgetType(t);
    setError('');
    setSiteId('');
    setDeviceId('');
    setStreamId('');
  };

  // --- line chart row helpers ---
  const addStreamRow = () => {
    setStreamRows((prev) => [
      ...prev,
      { id: Date.now(), siteId: '', deviceId: '', streamId: '', streamLabel: '', axis: 'left' },
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

  // --- submit ---
  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');

    if (widgetType === 'value_card') {
      if (!streamId) { setError('Please select a stream.'); return; }
      onSubmit({
        widget_type: 'value_card',
        stream_ids: [Number(streamId)],
        config: {},
        position: { order: nextOrder },
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
        position: { order: nextOrder },
      });
      return;
    }

    if (widgetType === 'line_chart') {
      const validRows = streamRows.filter((r) => r.streamId);
      if (validRows.length === 0) { setError('Add at least one stream.'); return; }
      const streamConfigs = validRows.map((r, i) => ({
        stream_id: Number(r.streamId),
        axis: i === 0 ? 'left' : r.axis,
        color: STREAM_COLORS[i % STREAM_COLORS.length],
        label: r.streamLabel || `Stream ${r.streamId}`,
      }));
      const timeConfig =
        linePreset === 'custom'
          ? { time_range: 'custom', date_from: lineDateFrom, date_to: lineDateTo }
          : { time_range: linePreset };
      onSubmit({
        widget_type: 'line_chart',
        stream_ids: streamConfigs.map((s) => s.stream_id),
        config: { streams: streamConfigs, ...timeConfig },
        position: { order: nextOrder },
      });
    }
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>Add Widget</h2>
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
            >
              {WIDGET_TYPES.map((t) => (
                <option key={t.value} value={t.value} disabled={t.disabled}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* ---- value_card and gauge: single stream picker ---- */}
          {(widgetType === 'value_card' || widgetType === 'gauge') && (
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
                  <input
                    id="gauge-min"
                    type="number"
                    className={styles.input}
                    value={gaugeMin}
                    onChange={(e) => setGaugeMin(e.target.value)}
                  />
                </div>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-max">Max</label>
                  <input
                    id="gauge-max"
                    type="number"
                    className={styles.input}
                    value={gaugeMax}
                    onChange={(e) => setGaugeMax(e.target.value)}
                  />
                </div>
              </div>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-warn">Warning threshold</label>
                  <input
                    id="gauge-warn"
                    type="number"
                    className={styles.input}
                    value={gaugeWarn}
                    onChange={(e) => setGaugeWarn(e.target.value)}
                  />
                </div>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="gauge-danger">Danger threshold</label>
                  <input
                    id="gauge-danger"
                    type="number"
                    className={styles.input}
                    value={gaugeDanger}
                    onChange={(e) => setGaugeDanger(e.target.value)}
                  />
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
                  <button
                    type="button"
                    className={styles.addStreamBtn}
                    onClick={addStreamRow}
                  >
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

          {error && <p className={styles.error}>{error}</p>}

          <div className={styles.actions}>
            <button type="submit" className={styles.primaryButton}>Add Widget</button>
            <button type="button" className={styles.secondaryButton} onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default WidgetBuilderModal;
