/**
 * StatusIndicatorWidget — displays a colour/label badge driven by a stream's
 * current value mapped against the device type's status_indicator_mappings.
 *
 * Config: { stream_id, device_type_id }
 * Ref: SPEC.md § Feature: Dashboards & Visualisation — Status Indicator widget
 */
import PropTypes from 'prop-types';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import styles from './StatusIndicatorWidget.module.css';

/**
 * @param {object}   props
 * @param {object}   props.config          - Widget config: { stream_id, device_type_id }.
 * @param {number}   props.refetchInterval - Poll interval in ms.
 * @param {boolean}  props.canEdit         - Show action buttons when true.
 * @param {function} props.onRemove        - Called when remove is clicked.
 * @param {function} [props.onEdit]        - Called when edit is clicked.
 */
function StatusIndicatorWidget({ config = {}, refetchInterval, canEdit, onRemove, onEdit }) {
  const { stream_id: streamId, device_type_id: deviceTypeId } = config;

  const { data: stream, isLoading: streamLoading } = useQuery({
    queryKey: ['stream', streamId],
    queryFn: () => api.get(`/api/v1/streams/${streamId}/`).then((r) => r.data),
    enabled: !!streamId,
    refetchInterval,
  });

  const { data: deviceType, isLoading: dtLoading } = useQuery({
    queryKey: ['device-types', deviceTypeId],
    queryFn: () => api.get(`/api/v1/device-types/${deviceTypeId}/`).then((r) => r.data),
    enabled: !!deviceTypeId,
  });

  const { data: readings, isLoading: readingsLoading } = useQuery({
    queryKey: ['stream-readings', streamId, { limit: 1 }],
    queryFn: () =>
      api
        .get(`/api/v1/streams/${streamId}/readings/`, { params: { limit: 1 } })
        .then((r) => r.data),
    enabled: !!streamId,
    refetchInterval,
  });

  const isLoading = streamLoading || dtLoading || readingsLoading;

  if (!streamId || !deviceTypeId) {
    return (
      <div className={styles.card}>
        {canEdit && (
          <div className={styles.actions}>
            {onEdit && <button type="button" className={styles.editBtn} onClick={onEdit} title="Edit widget">✎</button>}
            <button type="button" className={styles.removeBtn} onClick={onRemove} title="Remove widget">×</button>
          </div>
        )}
        <span className={styles.statusMsg}>Widget not configured.</span>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className={styles.card}>
        <span className={styles.statusMsg}>Loading…</span>
      </div>
    );
  }

  const streamKey = stream?.key || '';
  const mappings = deviceType?.status_indicator_mappings?.[streamKey] || [];
  const latestReading = Array.isArray(readings) ? readings[0] : null;
  const currentValue = latestReading?.value;
  const currentValueStr = currentValue != null ? String(currentValue) : null;
  const match = currentValueStr != null
    ? mappings.find((m) => String(m.value) === currentValueStr)
    : null;

  const displayColor = match?.color ?? '#9CA3AF';
  const displayLabel = match?.label ?? (currentValueStr != null ? currentValueStr : 'No data');
  const streamLabel = stream?.label || streamKey;

  return (
    <div className={styles.card}>
      {canEdit && (
        <div className={styles.actions}>
          {onEdit && <button type="button" className={styles.editBtn} onClick={onEdit} title="Edit widget">✎</button>}
          <button type="button" className={styles.removeBtn} onClick={onRemove} title="Remove widget">×</button>
        </div>
      )}
      <span className={styles.streamLabel}>{streamLabel}</span>
      <div className={styles.indicator} style={{ backgroundColor: displayColor }}>
        <span className={styles.indicatorLabel}>{displayLabel}</span>
      </div>
      {currentValueStr != null && !match && mappings.length > 0 && (
        <span className={styles.unmapped}>Unmapped value: {currentValueStr}</span>
      )}
    </div>
  );
}

StatusIndicatorWidget.propTypes = {
  config: PropTypes.object.isRequired,
  refetchInterval: PropTypes.number,
  canEdit: PropTypes.bool,
  onRemove: PropTypes.func.isRequired,
  onEdit: PropTypes.func,
};

export default StatusIndicatorWidget;
