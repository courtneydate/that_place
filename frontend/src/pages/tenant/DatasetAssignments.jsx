/**
 * Dataset Assignments — Tenant Admin page.
 *
 * Allows Tenant Admins to assign reference datasets to their tenant (or a
 * specific site), configure dimension filters via per-key dropdowns (values
 * sourced from the dataset's actual rows), pin a version, and preview the
 * currently resolved values.
 *
 * Ref: SPEC.md § Feature: Reference Datasets — Tenant Dataset Assignments
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import DimensionFilterInputs from '../../components/DimensionFilterInputs';
import { useSites } from '../../hooks/useSites';
import {
  useCreateDatasetAssignment,
  useDatasetAssignments,
  useDeleteDatasetAssignment,
  useReferenceDatasets,
  useResolveAssignment,
  useUpdateDatasetAssignment,
} from '../../hooks/useFeeds';
import styles from '../admin/AdminPage.module.css';

// ---------------------------------------------------------------------------
// Resolve preview — shows the currently resolved row values
// ---------------------------------------------------------------------------

function ResolvePreview({ assignmentId }) {
  const { data, isLoading, isError, error } = useResolveAssignment(assignmentId);

  if (isLoading) return <p className={styles.loading}>Resolving…</p>;
  if (isError) {
    const msg = error?.response?.data?.error?.message ?? 'Resolution failed.';
    return <p className={styles.error}>Could not resolve: {msg}</p>;
  }
  if (!data) return null;

  // Endpoint returns { resolved_values: { key: value, ... } }
  const values = data.resolved_values ?? data;

  return (
    <div style={{
      marginTop: '0.5rem', padding: '0.75rem', background: '#F0FDF4',
      borderRadius: '6px', border: '1px solid #BBF7D0',
    }}>
      <p style={{ margin: '0 0 0.5rem', fontSize: '0.8125rem', fontWeight: 600, color: '#166534' }}>
        Currently resolved values
      </p>
      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.25rem 1rem' }}>
        {Object.entries(values).map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <dt style={{ fontSize: '0.8125rem', color: '#6B7280', margin: 0 }}>{k}</dt>
            <dd style={{ fontSize: '0.8125rem', color: '#111827', margin: 0, fontFamily: 'monospace' }}>
              {typeof v === 'object' ? JSON.stringify(v) : String(v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
ResolvePreview.propTypes = { assignmentId: PropTypes.number.isRequired };

// ---------------------------------------------------------------------------
// Assignment form (create + edit)
// ---------------------------------------------------------------------------

function AssignmentForm({ initial, datasets, sites, onSave, onCancel, saving, error }) {
  const [dataset, setDataset] = useState(initial ? String(initial.dataset) : '');
  const [site, setSite] = useState(initial?.site ? String(initial.site) : '');
  const [dimFilter, setDimFilter] = useState(initial?.dimension_filter ?? {});
  const [version, setVersion] = useState(initial?.version ?? '');
  const [effectiveFrom, setEffectiveFrom] = useState(initial?.effective_from ?? '');
  const [effectiveTo, setEffectiveTo] = useState(initial?.effective_to ?? '');

  const selectedDataset = datasets.find((d) => String(d.id) === dataset);
  const dimSchema = selectedDataset?.dimension_schema ?? {};
  const hasVersion = selectedDataset?.has_version ?? false;

  const handleDatasetChange = (val) => {
    setDataset(val);
    setDimFilter({}); // reset filter when dataset changes
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave({
      dataset: Number(dataset),
      site: site ? Number(site) : null,
      dimension_filter: dimFilter,
      version: version || null,
      effective_from: effectiveFrom || null,
      effective_to: effectiveTo || null,
    });
  };

  return (
    <form onSubmit={handleSubmit} className={styles.form} style={{ maxWidth: '600px' }}>
      <div className={styles.field}>
        <label className={styles.label}>Dataset</label>
        <select
          className={styles.input}
          value={dataset}
          onChange={(e) => handleDatasetChange(e.target.value)}
          required
          disabled={!!initial}
        >
          <option value="">— select a dataset —</option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
        {selectedDataset?.description && (
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.8125rem', color: '#6B7280' }}>
            {selectedDataset.description}
          </p>
        )}
      </div>

      <div className={styles.field}>
        <label className={styles.label}>Site (leave blank for tenant-wide)</label>
        <select
          className={styles.input}
          value={site}
          onChange={(e) => setSite(e.target.value)}
        >
          <option value="">Tenant-wide</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>

      {dataset && Object.keys(dimSchema).length > 0 && (
        <div className={styles.field}>
          <label className={styles.label}>Dimension filter</label>
          <p style={{ margin: '0 0 0.5rem', fontSize: '0.8125rem', color: '#6B7280' }}>
            Select the values that identify the correct rows for this site.
          </p>
          <DimensionFilterInputs
            datasetId={dataset}
            dimSchema={dimSchema}
            value={dimFilter}
            onChange={setDimFilter}
          />
        </div>
      )}

      {hasVersion && (
        <div className={styles.field}>
          <label className={styles.label}>Version pin (leave blank to always use latest)</label>
          <input
            className={styles.input}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="e.g. 2025-26"
          />
        </div>
      )}

      <div className={styles.inlineFields}>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Effective from</label>
          <input
            type="date"
            className={styles.input}
            value={effectiveFrom}
            onChange={(e) => setEffectiveFrom(e.target.value)}
            required
          />
        </div>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Effective to (optional)</label>
          <input
            type="date"
            className={styles.input}
            value={effectiveTo}
            onChange={(e) => setEffectiveTo(e.target.value)}
          />
        </div>
      </div>

      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <button type="submit" className={styles.primaryButton} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className={styles.secondaryButton} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

AssignmentForm.propTypes = {
  initial: PropTypes.object,
  datasets: PropTypes.array.isRequired,
  sites: PropTypes.array.isRequired,
  onSave: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
  saving: PropTypes.bool,
  error: PropTypes.string,
};

// ---------------------------------------------------------------------------
// Single assignment card
// ---------------------------------------------------------------------------

function AssignmentCard({ assignment, datasets, sites, onEdit, onDelete }) {
  const [showResolve, setShowResolve] = useState(false);
  const dataset = datasets.find((d) => d.id === assignment.dataset);
  const site = sites.find((s) => s.id === assignment.site);

  return (
    <div className={styles.section}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
        <div style={{ flex: 1 }}>
          <span className={styles.sectionTitle} style={{ display: 'inline' }}>
            {dataset?.name ?? `Dataset ${assignment.dataset}`}
          </span>
          {' · '}
          <span style={{ fontSize: '0.875rem', color: '#6B7280' }}>
            {site ? site.name : 'Tenant-wide'}
          </span>
          <div style={{ marginTop: '0.375rem', fontSize: '0.8125rem', color: '#6B7280' }}>
            {Object.entries(assignment.dimension_filter || {}).map(([k, v]) => (
              <span key={k} style={{
                display: 'inline-block', marginRight: '0.5rem',
                background: '#F3F4F6', borderRadius: '4px', padding: '0.125rem 0.5rem',
              }}>
                <span style={{ fontWeight: 500 }}>{k}:</span>{' '}
                <span className={styles.mono}>{String(v)}</span>
              </span>
            ))}
            {assignment.version && (
              <span style={{
                display: 'inline-block', marginRight: '0.5rem',
                background: '#EFF6FF', color: '#1D4ED8',
                borderRadius: '4px', padding: '0.125rem 0.5rem',
              }}>
                v{assignment.version}
              </span>
            )}
            {assignment.effective_from && (
              <span>From {assignment.effective_from}</span>
            )}
            {assignment.effective_to && (
              <span> → {assignment.effective_to}</span>
            )}
          </div>
        </div>
        <button
          className={styles.secondaryButton}
          onClick={() => setShowResolve((v) => !v)}
          style={{ whiteSpace: 'nowrap' }}
        >
          {showResolve ? 'Hide preview' : 'Preview'}
        </button>
        <button className={styles.secondaryButton} onClick={onEdit}>Edit</button>
        <button className={styles.dangerButton} onClick={onDelete}>Remove</button>
      </div>
      {showResolve && <ResolvePreview assignmentId={assignment.id} />}
    </div>
  );
}

AssignmentCard.propTypes = {
  assignment: PropTypes.object.isRequired,
  datasets: PropTypes.array.isRequired,
  sites: PropTypes.array.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function DatasetAssignments() {
  const { data: assignmentsData, isLoading, isError } = useDatasetAssignments();
  const { data: datasetsData } = useReferenceDatasets();
  const { data: sitesData } = useSites();
  const createMutation = useCreateDatasetAssignment();
  const updateMutation = useUpdateDatasetAssignment();
  const deleteMutation = useDeleteDatasetAssignment();

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formError, setFormError] = useState('');

  const assignments = Array.isArray(assignmentsData)
    ? assignmentsData
    : (assignmentsData?.results ?? []);
  const datasets = Array.isArray(datasetsData)
    ? datasetsData
    : (datasetsData?.results ?? []);
  const sites = Array.isArray(sitesData) ? sitesData : (sitesData?.results ?? []);

  const handleCreate = (formData) => {
    setFormError('');
    createMutation.mutate(formData, {
      onSuccess: () => setCreating(false),
      onError: (err) =>
        setFormError(err.response?.data?.error?.message ?? 'Failed to create assignment.'),
    });
  };

  const handleUpdate = (id, formData) => {
    setFormError('');
    updateMutation.mutate(
      { id, ...formData },
      {
        onSuccess: () => setEditingId(null),
        onError: (err) =>
          setFormError(err.response?.data?.error?.message ?? 'Failed to update assignment.'),
      }
    );
  };

  const handleDelete = (id) => {
    if (!window.confirm('Remove this dataset assignment?')) return;
    deleteMutation.mutate(id);
  };

  if (isLoading) return <p className={styles.loading}>Loading dataset assignments…</p>;
  if (isError) return <p className={styles.error}>Failed to load dataset assignments.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Dataset Assignments</h1>
        {!creating && (
          <button className={styles.primaryButton} onClick={() => setCreating(true)}>
            + New Assignment
          </button>
        )}
      </div>

      <p style={{ marginBottom: '1.5rem', color: '#6B7280', fontSize: '0.875rem' }}>
        Assign reference datasets (tariffs, CO2 factors, etc.) to this tenant or specific sites.
        Rules with <strong>reference_value</strong> conditions and the billing engine use these
        assignments to look up current values.
      </p>

      {creating && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>New Dataset Assignment</h2>
          <AssignmentForm
            datasets={datasets}
            sites={sites}
            onSave={handleCreate}
            onCancel={() => { setCreating(false); setFormError(''); }}
            saving={createMutation.isPending}
            error={formError}
          />
        </div>
      )}

      {assignments.length === 0 && !creating && (
        <p className={styles.empty}>No dataset assignments yet.</p>
      )}

      {assignments.map((assignment) =>
        editingId === assignment.id ? (
          <div key={assignment.id} className={styles.section}>
            <h2 className={styles.sectionTitle}>Edit assignment</h2>
            <AssignmentForm
              initial={assignment}
              datasets={datasets}
              sites={sites}
              onSave={(data) => handleUpdate(assignment.id, data)}
              onCancel={() => { setEditingId(null); setFormError(''); }}
              saving={updateMutation.isPending}
              error={formError}
            />
          </div>
        ) : (
          <AssignmentCard
            key={assignment.id}
            assignment={assignment}
            datasets={datasets}
            sites={sites}
            onEdit={() => setEditingId(assignment.id)}
            onDelete={() => handleDelete(assignment.id)}
          />
        )
      )}
    </div>
  );
}

export default DatasetAssignments;
