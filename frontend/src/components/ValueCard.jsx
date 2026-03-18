/**
 * ValueCard widget — displays the latest reading for a single stream,
 * a trend indicator (up / down / stable), and time since last update.
 *
 * Auto-refreshes on the interval supplied by the parent dashboard canvas.
 */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import styles from './ValueCard.module.css';

/** Derive trend by comparing the two most recent readings. */
function deriveTrend(readings) {
  if (!readings || readings.length < 2) return 'stable';
  const latest = Number(readings[0].value);
  const previous = Number(readings[1].value);
  if (isNaN(latest) || isNaN(previous)) return 'stable';
  if (latest > previous) return 'up';
  if (latest < previous) return 'down';
  return 'stable';
}

/** Format a timestamp as a human-readable "N minutes ago" string. */
function timeAgo(isoString) {
  if (!isoString) return '—';
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const TREND_ICON = { up: '↑', down: '↓', stable: '→' };
const TREND_CLASS = { up: styles.trendUp, down: styles.trendDown, stable: styles.trendStable };

/**
 * @param {object}   props
 * @param {number}   props.streamId       - Stream PK to display.
 * @param {object}   [props.config]       - Widget config (optional label override).
 * @param {number}   [props.refetchInterval] - Poll interval in ms (default: 30 000).
 * @param {function} [props.onRemove]     - Called when the remove button is clicked.
 * @param {boolean}  [props.canEdit]      - Show remove button when true.
 */
function ValueCard({ streamId, config = {}, refetchInterval = 30000, onRemove, canEdit }) {
  const { data: stream } = useQuery({
    queryKey: ['stream', streamId],
    queryFn: () => api.get(`/api/v1/streams/${streamId}/`).then((r) => r.data),
    enabled: !!streamId,
    refetchInterval,
  });

  const { data: readings } = useQuery({
    queryKey: ['stream-readings', streamId, { limit: 2 }],
    queryFn: () =>
      api
        .get(`/api/v1/streams/${streamId}/readings/`, { params: { limit: 2 } })
        .then((r) => r.data),
    enabled: !!streamId,
    refetchInterval,
  });

  const label = config.label_override || stream?.label || stream?.key || '—';
  const unit = stream?.unit || '';
  const latestValue = stream?.latest_value ?? readings?.[0]?.value ?? null;
  const lastTimestamp = stream?.latest_timestamp || readings?.[0]?.timestamp;
  const trend = deriveTrend(readings);

  return (
    <div className={styles.card}>
      {canEdit && onRemove && (
        <button className={styles.removeBtn} onClick={onRemove} title="Remove widget">
          ×
        </button>
      )}
      <div className={styles.label}>{label}</div>
      <div className={styles.valueRow}>
        <span className={styles.value}>
          {latestValue !== null ? String(latestValue) : '—'}
        </span>
        {unit && <span className={styles.unit}>{unit}</span>}
        <span className={`${styles.trend} ${TREND_CLASS[trend]}`}>
          {TREND_ICON[trend]}
        </span>
      </div>
      <div className={styles.lastSeen}>{timeAgo(lastTimestamp)}</div>
    </div>
  );
}

export default ValueCard;
