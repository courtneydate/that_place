/**
 * Derived stream builder (Sprint 27).
 *
 * Inline form rendered from the device Streams tab. Lets a Tenant Admin
 * configure a new derived stream — formula, sources, params — and submit.
 * Cross-device source sets cause the backend to host the output on a per-site
 * Site Composite Device (auto-created).
 *
 * Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import { useDevices } from '../hooks/useDevices';
import { useCreateDerivedStream } from '../hooks/useDerivedStreams';
import { useDeviceStreams } from '../hooks/useStreams';
import styles from '../pages/admin/AdminPage.module.css';

const FORMULAS = [
  { value: 'delta',      label: 'Delta (interval from cumulative)', sources: 'one',         defaultKind: 'sum'  },
  { value: 'scale',      label: 'Scale (source × factor)',          sources: 'one',         defaultKind: 'mean' },
  { value: 'sum',        label: 'Sum (Σ at same minute, cross-device OK)', sources: 'one_or_more', defaultKind: 'sum'  },
  { value: 'difference', label: 'Difference (A − B at same minute)', sources: 'exactly_two', defaultKind: 'sum'  },
  { value: 'window_min', label: 'Rolling minimum over N minutes',    sources: 'one',         defaultKind: 'min'  },
  { value: 'window_max', label: 'Rolling maximum over N minutes',    sources: 'one',         defaultKind: 'max'  },
];

const AGG_KIND_OPTIONS = [
  { value: 'sum',  label: 'Sum (energy, kWh)' },
  { value: 'mean', label: 'Mean (instantaneous, e.g. power/voltage)' },
  { value: 'min',  label: 'Min' },
  { value: 'max',  label: 'Max' },
  { value: 'last', label: 'Last (cumulative counter)' },
];

const FORMULA_BY_VALUE = Object.fromEntries(FORMULAS.map((f) => [f.value, f]));

function SourceStreamPicker({ devices, selectedIds, onChange, multiple }) {
  /**
   * Two-step picker — pick a device, then pick a numeric stream on that device.
   * Selected source streams are listed and can be removed individually.
   */
  const [deviceId, setDeviceId] = useState('');
  const { data: streams = [] } = useDeviceStreams(deviceId || null);

  const handleAdd = (streamId) => {
    const id = Number(streamId);
    if (!id || selectedIds.includes(id)) return;
    onChange(multiple ? [...selectedIds, id] : [id]);
  };

  const handleRemove = (id) => onChange(selectedIds.filter((s) => s !== id));

  return (
    <div>
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-end' }}>
        <div className={styles.field} style={{ marginBottom: 0 }}>
          <label className={styles.label} htmlFor="ds-source-device">Device</label>
          <select
            id="ds-source-device"
            className={styles.input}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
          >
            <option value="">— pick a device —</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>
        <div className={styles.field} style={{ marginBottom: 0, flex: 1 }}>
          <label className={styles.label} htmlFor="ds-source-stream">Stream</label>
          <select
            id="ds-source-stream"
            className={styles.input}
            disabled={!deviceId}
            onChange={(e) => { if (e.target.value) handleAdd(e.target.value); }}
            value=""
          >
            <option value="">— pick a stream to add —</option>
            {streams.filter((s) => s.data_type === 'numeric').map((s) => (
              <option key={s.id} value={s.id}>{s.label || s.key}</option>
            ))}
          </select>
        </div>
      </div>
      {selectedIds.length > 0 && (
        <ul style={{ marginTop: '0.5rem', paddingLeft: '1rem' }}>
          {selectedIds.map((id) => (
            <li key={id} style={{ fontSize: '0.875rem', marginBottom: '0.25rem' }}>
              Stream #{id}{' '}
              <button
                type="button"
                onClick={() => handleRemove(id)}
                style={{ marginLeft: '0.5rem', fontSize: '0.75rem', color: '#EF4444', background: 'none', border: 'none', cursor: 'pointer' }}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

SourceStreamPicker.propTypes = {
  devices: PropTypes.array.isRequired,
  selectedIds: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
  multiple: PropTypes.bool.isRequired,
};


function DerivedStreamBuilder({ onDone }) {
  const { data: devices = [] } = useDevices({ status: 'active' });
  const createDerived = useCreateDerivedStream();

  const [formula, setFormula] = useState('delta');
  const [key, setKey] = useState('');
  const [label, setLabel] = useState('');
  const [unit, setUnit] = useState('');
  const [aggregationKind, setAggregationKind] = useState('sum'); // delta → sum by default
  const [sourceIds, setSourceIds] = useState([]);
  const [factor, setFactor] = useState('');
  const [windowMinutes, setWindowMinutes] = useState('');
  const [maxGapMinutes, setMaxGapMinutes] = useState('');
  const [error, setError] = useState('');

  const config = FORMULA_BY_VALUE[formula];
  const sourcesValid =
    (config.sources === 'one' && sourceIds.length === 1) ||
    (config.sources === 'exactly_two' && sourceIds.length === 2) ||
    (config.sources === 'one_or_more' && sourceIds.length >= 1);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!key.trim()) { setError('Stream key is required.'); return; }
    if (!sourcesValid) { setError('Source stream count does not match the selected formula.'); return; }

    const params = {};
    if (formula === 'scale') {
      if (!factor) { setError('Factor is required for scale.'); return; }
      params.factor = Number(factor);
    }
    if (formula === 'window_min' || formula === 'window_max') {
      if (!windowMinutes) { setError('Window minutes is required.'); return; }
      params.window_minutes = Number(windowMinutes);
    }
    if (formula === 'delta' && maxGapMinutes) {
      params.max_gap_minutes = Number(maxGapMinutes);
    }
    if (formula === 'difference' && sourceIds.length === 2) {
      params.source_a_id = sourceIds[0];
      params.source_b_id = sourceIds[1];
    }

    try {
      await createDerived.mutateAsync({
        key: key.trim(),
        label: label.trim(),
        unit: unit.trim(),
        formula,
        aggregation_kind_default: aggregationKind,
        source_stream_ids: sourceIds,
        params,
      });
      onDone();
    } catch (err) {
      const detail = err.response?.data;
      setError(
        typeof detail === 'string'
          ? detail
          : (detail?.non_field_errors?.[0] ||
             detail?.error?.message ||
             JSON.stringify(detail) ||
             'Failed to create derived stream.'),
      );
    }
  };

  return (
    <section className={styles.section}>
      <h3 style={{ fontSize: '1rem', fontWeight: 600, marginTop: 0 }}>New derived stream</h3>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <div className={styles.inlineFields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ds-key">Stream key *</label>
            <input
              id="ds-key" type="text"
              value={key} onChange={(e) => setKey(e.target.value)}
              className={styles.input} placeholder="e.g. interval_kwh"
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ds-label">Label</label>
            <input
              id="ds-label" type="text"
              value={label} onChange={(e) => setLabel(e.target.value)}
              className={styles.input} placeholder="Interval kWh"
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ds-unit">Unit</label>
            <input
              id="ds-unit" type="text"
              value={unit} onChange={(e) => setUnit(e.target.value)}
              className={styles.input} placeholder="kWh"
            />
          </div>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="ds-formula">Formula</label>
          <select
            id="ds-formula"
            value={formula}
            onChange={(e) => {
              const f = FORMULA_BY_VALUE[e.target.value];
              setFormula(e.target.value);
              setSourceIds([]);
              setAggregationKind(f?.defaultKind || 'sum');
            }}
            className={styles.input}
          >
            {FORMULAS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="ds-agg-kind">
            Aggregation kind
            {' '}
            <span style={{ color: '#6B7280', fontWeight: 400, fontSize: '0.8125rem' }}>
              (how the beat task buckets readings — use Sum for energy)
            </span>
          </label>
          <select
            id="ds-agg-kind"
            value={aggregationKind}
            onChange={(e) => setAggregationKind(e.target.value)}
            className={styles.input}
          >
            {AGG_KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label}>
            Source stream(s)
            {' '}
            <span style={{ color: '#6B7280', fontWeight: 400, fontSize: '0.8125rem' }}>
              ({config.sources.replace('_', ' ')})
            </span>
          </label>
          <SourceStreamPicker
            devices={devices}
            selectedIds={sourceIds}
            onChange={setSourceIds}
            multiple={config.sources !== 'one'}
          />
        </div>

        {formula === 'scale' && (
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ds-factor">Factor *</label>
            <input
              id="ds-factor" type="number" step="any"
              value={factor} onChange={(e) => setFactor(e.target.value)}
              className={styles.input}
            />
          </div>
        )}

        {(formula === 'window_min' || formula === 'window_max') && (
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ds-window">Window minutes *</label>
            <input
              id="ds-window" type="number" min="1"
              value={windowMinutes} onChange={(e) => setWindowMinutes(e.target.value)}
              className={styles.input}
            />
          </div>
        )}

        {formula === 'delta' && (
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ds-gap">Max gap minutes (optional)</label>
            <input
              id="ds-gap" type="number" min="1"
              value={maxGapMinutes} onChange={(e) => setMaxGapMinutes(e.target.value)}
              className={styles.input}
              placeholder="Leave blank to never suppress on gap"
            />
          </div>
        )}

        {error && <p className={styles.error}>{error}</p>}

        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={createDerived.isPending}
          >
            {createDerived.isPending ? 'Creating…' : 'Create derived stream'}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onDone}
            disabled={createDerived.isPending}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

DerivedStreamBuilder.propTypes = {
  onDone: PropTypes.func.isRequired,
};

export default DerivedStreamBuilder;
