/**
 * DimensionFilterInputs — per-key dropdowns for a reference dataset's
 * dimension filter.
 *
 * Fetches distinct values for each dimension key from the dataset's rows
 * (GET /api/v1/reference-datasets/:id/dimension-values/) and renders one
 * dropdown per key. Falls back to a plain text input if no rows exist yet.
 *
 * Used by DatasetAssignments and BillingAccountDetail (Tariffs tab).
 */
import PropTypes from 'prop-types';
import { useDatasetDimensionValues } from '../hooks/useFeeds';
import styles from '../pages/admin/AdminPage.module.css';

export default function DimensionFilterInputs({ datasetId, dimSchema, value, onChange }) {
  const { data: dimValues = {}, isLoading } = useDatasetDimensionValues(datasetId);
  const keys = Object.keys(dimSchema || {});

  if (!keys.length) return null;

  const handleKeyChange = (key, val) => {
    onChange({ ...value, [key]: val });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {keys.map((key) => {
        const options = dimValues[key] ?? [];
        const current = value[key] ?? '';
        return (
          <div key={key} className={styles.field}>
            <label className={styles.label}>{key}</label>
            {isLoading ? (
              <select className={styles.input} disabled>
                <option>Loading…</option>
              </select>
            ) : options.length > 0 ? (
              <select
                className={styles.input}
                value={current}
                onChange={(e) => handleKeyChange(key, e.target.value)}
                required
              >
                <option value="">— select {key} —</option>
                {options.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : (
              <input
                className={styles.input}
                value={current}
                onChange={(e) => handleKeyChange(key, e.target.value)}
                placeholder={`Enter ${key}`}
                required
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

DimensionFilterInputs.propTypes = {
  datasetId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  dimSchema: PropTypes.object,
  value: PropTypes.object.isRequired,
  onChange: PropTypes.func.isRequired,
};
