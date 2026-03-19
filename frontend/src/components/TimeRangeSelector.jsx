/**
 * TimeRangeSelector — preset time range buttons plus custom date inputs.
 *
 * Calls onChange({ preset, from, to, dateFrom, dateTo }) on every change.
 * `from` and `to` are ISO strings, or null when custom is selected but dates
 * are not yet complete.
 */
import styles from './TimeRangeSelector.module.css';

export const TIME_RANGE_PRESETS = [
  { label: 'Last hour', value: '1h' },
  { label: '24h', value: '24h' },
  { label: '7 days', value: '7d' },
  { label: '30 days', value: '30d' },
  { label: 'Custom', value: 'custom' },
];

/** Convert a non-custom preset to { from, to } ISO strings relative to now. */
export function presetToRange(preset) {
  const to = new Date();
  const from = new Date(to);
  if (preset === '1h') from.setHours(from.getHours() - 1);
  else if (preset === '24h') from.setDate(from.getDate() - 1);
  else if (preset === '7d') from.setDate(from.getDate() - 7);
  else if (preset === '30d') from.setDate(from.getDate() - 30);
  return { from: from.toISOString(), to: to.toISOString() };
}

function toDateInputValue(date) {
  return new Date(date).toISOString().slice(0, 10);
}

/**
 * @param {object}   props
 * @param {string}   props.preset    - Active preset: '1h'|'24h'|'7d'|'30d'|'custom'.
 * @param {string}   [props.dateFrom] - YYYY-MM-DD, used when preset is 'custom'.
 * @param {string}   [props.dateTo]   - YYYY-MM-DD, used when preset is 'custom'.
 * @param {function} props.onChange  - Called with { preset, from, to, dateFrom, dateTo }.
 */
function TimeRangeSelector({ preset, dateFrom, dateTo, onChange }) {
  const today = toDateInputValue(new Date());

  const handlePreset = (p) => {
    if (p === 'custom') {
      onChange({
        preset: 'custom',
        from: null,
        to: null,
        dateFrom: dateFrom || today,
        dateTo: dateTo || today,
      });
      return;
    }
    onChange({ preset: p, ...presetToRange(p), dateFrom: '', dateTo: '' });
  };

  const handleDate = (field, val) => {
    const newFrom = field === 'from' ? val : (dateFrom || '');
    const newTo = field === 'to' ? val : (dateTo || '');
    const bothSet = newFrom && newTo;
    onChange({
      preset: 'custom',
      from: bothSet ? new Date(newFrom).toISOString() : null,
      to: bothSet ? new Date(newTo + 'T23:59:59').toISOString() : null,
      dateFrom: newFrom,
      dateTo: newTo,
    });
  };

  return (
    <div className={styles.container}>
      <div className={styles.presets}>
        {TIME_RANGE_PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            className={`${styles.btn} ${preset === p.value ? styles.active : ''}`}
            onClick={() => handlePreset(p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>
      {preset === 'custom' && (
        <div className={styles.customRange}>
          <input
            type="date"
            className={styles.dateInput}
            value={dateFrom || ''}
            max={dateTo || today}
            onChange={(e) => handleDate('from', e.target.value)}
          />
          <span className={styles.sep}>to</span>
          <input
            type="date"
            className={styles.dateInput}
            value={dateTo || ''}
            min={dateFrom || ''}
            max={today}
            onChange={(e) => handleDate('to', e.target.value)}
          />
        </div>
      )}
    </div>
  );
}

export default TimeRangeSelector;
