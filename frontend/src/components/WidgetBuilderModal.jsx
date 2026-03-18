/**
 * WidgetBuilderModal — step-through modal for adding a widget to a dashboard.
 *
 * Flow: select widget type → pick site → pick device → pick stream → confirm.
 * Sprint 11 only supports value_card. The type selector is included for future sprints.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import styles from './WidgetBuilderModal.module.css';

const WIDGET_TYPES = [
  { value: 'value_card', label: 'Value Card' },
  { value: 'line_chart', label: 'Line Chart (Sprint 12)' },
  { value: 'gauge', label: 'Gauge (Sprint 12)' },
  { value: 'status_indicator', label: 'Status Indicator (Sprint 13)' },
  { value: 'health_uptime_chart', label: 'Health / Uptime Chart (Sprint 13)' },
];

/** Fetch all sites for the tenant. */
function useSiteList() {
  return useQuery({
    queryKey: ['sites'],
    queryFn: () => api.get('/api/v1/sites/').then((r) => r.data),
  });
}

/** Fetch all devices for the tenant; client-side filter by siteId. */
function useDeviceList() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: () => api.get('/api/v1/devices/').then((r) => r.data),
  });
}

/** Fetch streams for a device. */
function useDeviceStreamList(deviceId) {
  return useQuery({
    queryKey: ['device-streams', deviceId],
    queryFn: () => api.get(`/api/v1/devices/${deviceId}/streams/`).then((r) => r.data),
    enabled: !!deviceId,
  });
}

/**
 * @param {object}   props
 * @param {number}   props.dashboardId    - Parent dashboard PK.
 * @param {number}   props.nextOrder      - Position order for the new widget.
 * @param {function} props.onSubmit       - Called with widget payload when confirmed.
 * @param {function} props.onClose        - Called when the modal is dismissed.
 */
function WidgetBuilderModal({ dashboardId, nextOrder, onSubmit, onClose }) {
  const [widgetType, setWidgetType] = useState('value_card');
  const [siteId, setSiteId] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [streamId, setStreamId] = useState('');
  const [error, setError] = useState('');

  const { data: sites = [], isLoading: sitesLoading } = useSiteList();
  const { data: allDevices = [], isLoading: devicesLoading } = useDeviceList();
  const { data: streams = [], isLoading: streamsLoading } = useDeviceStreamList(deviceId || null);

  const devicesForSite = siteId
    ? allDevices.filter((d) => String(d.site) === String(siteId) && d.status === 'active')
    : allDevices.filter((d) => d.status === 'active');

  const handleSiteChange = (e) => {
    setSiteId(e.target.value);
    setDeviceId('');
    setStreamId('');
  };

  const handleDeviceChange = (e) => {
    setDeviceId(e.target.value);
    setStreamId('');
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!streamId) {
      setError('Please select a stream.');
      return;
    }
    onSubmit({
      widget_type: widgetType,
      stream_ids: [Number(streamId)],
      config: {},
      position: { order: nextOrder },
    });
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
            <label className={styles.label}>Widget Type</label>
            <select
              className={styles.select}
              value={widgetType}
              onChange={(e) => setWidgetType(e.target.value)}
            >
              {WIDGET_TYPES.map((t) => (
                <option key={t.value} value={t.value} disabled={t.value !== 'value_card'}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* Site filter (optional) */}
          <div className={styles.field}>
            <label className={styles.label}>Filter by Site (optional)</label>
            <select
              className={styles.select}
              value={siteId}
              onChange={handleSiteChange}
              disabled={sitesLoading}
            >
              <option value="">All sites</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          {/* Device */}
          <div className={styles.field}>
            <label className={styles.label}>Device</label>
            <select
              className={styles.select}
              value={deviceId}
              onChange={handleDeviceChange}
              disabled={devicesLoading}
            >
              <option value="">— Select a device —</option>
              {devicesForSite.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </div>

          {/* Stream */}
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
