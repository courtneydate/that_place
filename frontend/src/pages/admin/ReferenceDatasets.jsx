/**
 * Reference Datasets — That Place Admin page.
 *
 * Lists all ReferenceDatasets. ThatPlaceAdmin can:
 *   - Create/edit/delete datasets with schema builder
 *   - Browse rows with version filter
 *   - Upload a CSV for bulk upsert
 *
 * Ref: SPEC.md § Feature: Reference Datasets
 */
import { useRef, useState } from 'react';
import {
  useBulkImportRows,
  useCreateReferenceDataset,
  useDatasetRows,
  useDeleteReferenceDataset,
  useReferenceDatasets,
  useUpdateReferenceDataset,
} from '../../hooks/useFeeds';
import styles from './AdminPage.module.css';

const EMPTY_FORM = {
  slug: '',
  name: '',
  description: '',
  scope: 'system',
  has_time_of_use: false,
  has_version: false,
  dimension_schema: {},
  value_schema: {},
};

// ---------------------------------------------------------------------------
// Schema editor — generic key→{type,label,unit?} builder
// ---------------------------------------------------------------------------

function SchemaEditor({ label, value, onChange }) {
  /**
   * Edits a JSONB schema dict: { key: { type, label, unit? } }
   * Rendered as an ordered list of rows.
   */
  const entries = Object.entries(value || {});

  const update = (key, field, v) =>
    onChange({ ...value, [key]: { ...(value[key] || {}), [field]: v } });

  const addKey = () => {
    const key = `field_${Object.keys(value || {}).length + 1}`;
    onChange({ ...(value || {}), [key]: { type: 'numeric', label: '' } });
  };

  const removeKey = (key) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };

  const renameKey = (oldKey, newKey) => {
    if (!newKey || newKey === oldKey) return;
    const next = {};
    for (const [k, v] of Object.entries(value || {})) {
      next[k === oldKey ? newKey : k] = v;
    }
    onChange(next);
  };

  return (
    <div>
      <p className={styles.label} style={{ marginBottom: '0.5rem' }}>{label}</p>
      {entries.map(([key, def]) => (
        <div key={key} className={styles.inlineFields} style={{ marginBottom: '0.5rem', flexWrap: 'wrap' }}>
          <input
            className={styles.input}
            style={{ width: '140px' }}
            placeholder="key"
            defaultValue={key}
            onBlur={(e) => renameKey(key, e.target.value.trim())}
          />
          <input
            className={styles.input}
            style={{ flex: 1 }}
            placeholder="label"
            value={def.label || ''}
            onChange={(e) => update(key, 'label', e.target.value)}
          />
          <select
            className={styles.input}
            value={def.type || 'numeric'}
            onChange={(e) => update(key, 'type', e.target.value)}
            style={{ width: '100px' }}
          >
            <option value="numeric">numeric</option>
            <option value="string">string</option>
            <option value="boolean">boolean</option>
          </select>
          <input
            className={styles.input}
            style={{ width: '100px' }}
            placeholder="unit"
            value={def.unit || ''}
            onChange={(e) => update(key, 'unit', e.target.value)}
          />
          <button
            type="button"
            className={styles.dangerButton}
            style={{ padding: '0.375rem 0.75rem' }}
            onClick={() => removeKey(key)}
          >
            ✕
          </button>
        </div>
      ))}
      <button type="button" className={styles.secondaryButton} onClick={addKey}>
        + Add field
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dataset form
// ---------------------------------------------------------------------------

function DatasetForm({ initial, onSave, onCancel, saving, error }) {
  const [form, setForm] = useState(initial ?? EMPTY_FORM);
  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave(form);
  };

  return (
    <form onSubmit={handleSubmit} className={styles.form} style={{ maxWidth: '720px' }}>
      <div className={styles.inlineFields}>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Name</label>
          <input
            className={styles.input}
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            required
          />
        </div>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Slug</label>
          <input
            className={styles.input}
            value={form.slug}
            onChange={(e) => set('slug', e.target.value)}
            placeholder="network-tariffs"
            required
          />
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label}>Description</label>
        <textarea
          className={styles.input}
          value={form.description}
          onChange={(e) => set('description', e.target.value)}
          rows={2}
        />
      </div>
      <div className={styles.inlineFields}>
        <div className={styles.field}>
          <label className={styles.label}>Scope</label>
          <select
            className={styles.input}
            value={form.scope}
            onChange={(e) => set('scope', e.target.value)}
          >
            <option value="system">System</option>
            <option value="tenant">Tenant</option>
          </select>
        </div>
        <div className={styles.field} style={{ justifyContent: 'flex-end' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1.5rem' }}>
            <input
              type="checkbox"
              checked={form.has_time_of_use}
              onChange={(e) => set('has_time_of_use', e.target.checked)}
            />
            <span className={styles.label} style={{ margin: 0 }}>Time-of-use (TOU)</span>
          </label>
        </div>
        <div className={styles.field} style={{ justifyContent: 'flex-end' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1.5rem' }}>
            <input
              type="checkbox"
              checked={form.has_version}
              onChange={(e) => set('has_version', e.target.checked)}
            />
            <span className={styles.label} style={{ margin: 0 }}>Versioned (annual)</span>
          </label>
        </div>
      </div>
      <SchemaEditor
        label="Dimension schema (lookup keys)"
        value={form.dimension_schema}
        onChange={(v) => set('dimension_schema', v)}
      />
      <SchemaEditor
        label="Value schema (stored values)"
        value={form.value_schema}
        onChange={(v) => set('value_schema', v)}
      />
      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <button type="submit" className={styles.primaryButton} disabled={saving}>
          {saving ? 'Saving…' : 'Save dataset'}
        </button>
        <button type="button" className={styles.secondaryButton} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Row browser + CSV import panel
// ---------------------------------------------------------------------------

function RowPanel({ dataset }) {
  const [version, setVersion] = useState('');
  const fileRef = useRef(null);
  const { data, isLoading, isError, refetch } = useDatasetRows(dataset.id, version || undefined);
  const bulkImport = useBulkImportRows();
  const [importMsg, setImportMsg] = useState('');

  const rows = Array.isArray(data) ? data : (data?.results ?? []);
  const dimKeys = Object.keys(dataset.dimension_schema || {});
  const valKeys = Object.keys(dataset.value_schema || {});

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportMsg('');
    bulkImport.mutate(
      { datasetId: dataset.id, file },
      {
        onSuccess: (result) => {
          setImportMsg(
            `Imported ${result.imported} row(s)` +
            (result.errors?.length ? ` with ${result.errors.length} error(s).` : '.')
          );
          refetch();
          fileRef.current.value = '';
        },
        onError: (err) => {
          setImportMsg(err.response?.data?.error?.message ?? 'Import failed.');
          fileRef.current.value = '';
        },
      }
    );
  };

  return (
    <div style={{ marginTop: '1rem' }}>
      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        {dataset.has_version && (
          <input
            className={styles.input}
            style={{ width: '120px' }}
            placeholder="Version (e.g. 2025-26)"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label className={styles.label} style={{ margin: 0, whiteSpace: 'nowrap' }}>
            Upload CSV:
          </label>
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={handleImport}
            style={{ fontSize: '0.875rem' }}
          />
          {bulkImport.isPending && <span className={styles.loading}>Importing…</span>}
        </div>
        {importMsg && (
          <span className={importMsg.includes('error') ? styles.error : styles.success}>
            {importMsg}
          </span>
        )}
      </div>

      {isLoading && <p className={styles.loading}>Loading rows…</p>}
      {isError && <p className={styles.error}>Failed to load rows.</p>}
      {!isLoading && !isError && rows.length === 0 && (
        <p className={styles.empty}>No rows yet. Upload a CSV to import data.</p>
      )}
      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.table}>
            <thead>
              <tr>
                {dataset.has_version && <th>Version</th>}
                {dimKeys.map((k) => <th key={k}>{k}</th>)}
                {valKeys.map((k) => <th key={k}>{k}</th>)}
                {dataset.has_time_of_use && <th>Days</th>}
                {dataset.has_time_of_use && <th>Time window</th>}
                <th>Valid from</th>
                <th>Valid to</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  {dataset.has_version && <td className={styles.mono}>{row.version ?? '—'}</td>}
                  {dimKeys.map((k) => (
                    <td key={k} className={styles.mono}>{row.dimensions?.[k] ?? '—'}</td>
                  ))}
                  {valKeys.map((k) => (
                    <td key={k} className={styles.mono}>{row.values?.[k] ?? '—'}</td>
                  ))}
                  {dataset.has_time_of_use && (
                    <td className={styles.mono}>
                      {row.applicable_days?.join(',') ?? 'all'}
                    </td>
                  )}
                  {dataset.has_time_of_use && (
                    <td className={styles.mono}>
                      {row.time_from && row.time_to ? `${row.time_from}–${row.time_to}` : 'all day'}
                    </td>
                  )}
                  <td className={styles.mono}>{row.valid_from ?? '—'}</td>
                  <td className={styles.mono}>{row.valid_to ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function ReferenceDatasets() {
  const { data, isLoading, isError } = useReferenceDatasets();
  const createMutation = useCreateReferenceDataset();
  const updateMutation = useUpdateReferenceDataset();
  const deleteMutation = useDeleteReferenceDataset();

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [formError, setFormError] = useState('');

  const datasets = Array.isArray(data) ? data : (data?.results ?? []);

  const handleCreate = (formData) => {
    setFormError('');
    createMutation.mutate(formData, {
      onSuccess: () => setCreating(false),
      onError: (err) =>
        setFormError(err.response?.data?.error?.message ?? 'Failed to create dataset.'),
    });
  };

  const handleUpdate = (formData) => {
    setFormError('');
    updateMutation.mutate(formData, {
      onSuccess: () => setEditingId(null),
      onError: (err) =>
        setFormError(err.response?.data?.error?.message ?? 'Failed to update dataset.'),
    });
  };

  const handleDelete = (id) => {
    if (!window.confirm('Delete this dataset and all its rows?')) return;
    deleteMutation.mutate(id);
  };

  if (isLoading) return <p className={styles.loading}>Loading reference datasets…</p>;
  if (isError) return <p className={styles.error}>Failed to load reference datasets.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Reference Datasets</h1>
        {!creating && (
          <button className={styles.primaryButton} onClick={() => setCreating(true)}>
            + New Dataset
          </button>
        )}
      </div>

      {creating && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>New Reference Dataset</h2>
          <DatasetForm
            onSave={handleCreate}
            onCancel={() => { setCreating(false); setFormError(''); }}
            saving={createMutation.isPending}
            error={formError}
          />
        </div>
      )}

      {datasets.length === 0 && !creating && (
        <p className={styles.empty}>No reference datasets yet. Run <code>load_reference_data</code> to seed the defaults.</p>
      )}

      {datasets.map((dataset) => (
        <div key={dataset.id} className={styles.section}>
          {editingId === dataset.id ? (
            <>
              <h2 className={styles.sectionTitle}>Edit: {dataset.name}</h2>
              <DatasetForm
                initial={dataset}
                onSave={(data) => handleUpdate({ id: dataset.id, ...data })}
                onCancel={() => { setEditingId(null); setFormError(''); }}
                saving={updateMutation.isPending}
                error={formError}
              />
            </>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                <div style={{ flex: 1 }}>
                  <span className={styles.sectionTitle} style={{ display: 'inline' }}>
                    {dataset.name}
                  </span>
                  {' '}
                  <span className={styles.mono} style={{ color: '#6B7280' }}>
                    {dataset.slug}
                  </span>
                  {dataset.has_time_of_use && (
                    <span className={styles.badgeActive} style={{ marginLeft: '0.5rem' }}>TOU</span>
                  )}
                  {dataset.has_version && (
                    <span className={styles.badgeInactive} style={{ marginLeft: '0.5rem' }}>versioned</span>
                  )}
                </div>
                <button
                  className={styles.secondaryButton}
                  onClick={() => setExpandedId(expandedId === dataset.id ? null : dataset.id)}
                >
                  {expandedId === dataset.id ? 'Hide rows' : 'Rows / Import'}
                </button>
                <button
                  className={styles.secondaryButton}
                  onClick={() => setEditingId(dataset.id)}
                >
                  Edit schema
                </button>
                <button
                  className={styles.dangerButton}
                  onClick={() => handleDelete(dataset.id)}
                >
                  Delete
                </button>
              </div>
              {dataset.description && (
                <p style={{ margin: '0 0 0.25rem', color: '#6B7280', fontSize: '0.875rem' }}>
                  {dataset.description}
                </p>
              )}
              <p style={{ margin: 0, fontSize: '0.8125rem', color: '#6B7280' }}>
                Dimensions: {Object.keys(dataset.dimension_schema || {}).join(', ') || '—'}
                {' · '}
                Values: {Object.keys(dataset.value_schema || {}).join(', ') || '—'}
              </p>
              {expandedId === dataset.id && <RowPanel dataset={dataset} />}
            </>
          )}
        </div>
      ))}
    </div>
  );
}

export default ReferenceDatasets;
