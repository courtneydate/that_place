/**
 * Dataset Assignments — Tenant Admin page.
 *
 * Allows Tenant Admins to assign reference datasets to their tenant (or a
 * specific site), configure dimension filters (e.g. DNSP + tariff type), pin
 * a version, and preview the currently resolved values.
 *
 * Ref: SPEC.md § Feature: Reference Datasets — Tenant Dataset Assignments
 */
import { useState } from 'react';
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

const EMPTY_FORM = {
  dataset: '',
  site: '',
  dimension_filter: '{}',
  version: '',
  effective_from: '',
  effective_to: '',
};

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

  return (
    <div style={{ marginTop: '0.5rem', padding: '0.75rem', background: '#F0FDF4', borderRadius: '6px', border: '1px solid #BBF7D0' }}>
      <p style={{ margin: '0 0 0.5rem', fontSize: '0.8125rem', fontWeight: 600, color: '#166534' }}>
        Currently resolved values
      </p>
      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.25rem 1rem' }}>
        {Object.entries(data).map(([k, v]) => (
          <>
            <dt key={`k-${k}`} style={{ fontSize: '0.8125rem', color: '#6B7280', margin: 0 }}>{k}</dt>
            <dd key={`v-${k}`} style={{ fontSize: '0.8125rem', color: '#111827', margin: 0, fontFamily: 'monospace' }}>{String(v)}</dd>
          </>
        ))}
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assignment form
// ---------------------------------------------------------------------------

function AssignmentForm({ initial, datasets, sites, onSave, onCancel, saving, error }) {
  const [form, setForm] = useState(
    initial
      ? {
          dataset: initial.dataset,
          site: initial.site ?? '',
          dimension_filter: JSON.stringify(initial.dimension_filter ?? {}, null, 2),
          version: initial.version ?? '',
          effective_from: initial.effective_from ?? '',
          effective_to: initial.effective_to ?? '',
        }
      : EMPTY_FORM
  );
  const [filterError, setFilterError] = useState('');

  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  const selectedDataset = datasets.find((d) => String(d.id) === String(form.dataset));

  const handleSubmit = (e) => {
    e.preventDefault();
    let dimension_filter = {};
    try {
      dimension_filter = JSON.parse(form.dimension_filter || '{}');
      setFilterError('');
    } catch {
      setFilterError('Dimension filter is not valid JSON.');
      return;
    }
    onSave({
      dataset: Number(form.dataset),
      site: form.site ? Number(form.site) : null,
      dimension_filter,
      version: form.version || null,
      effective_from: form.effective_from || null,
      effective_to: form.effective_to || null,
    });
  };

  return (
    <form onSubmit={handleSubmit} className={styles.form} style={{ maxWidth: '600px' }}>
      <div className={styles.field}>
        <label className={styles.label}>Dataset</label>
        <select
          className={styles.input}
          value={form.dataset}
          onChange={(e) => set('dataset', e.target.value)}
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
          value={form.site}
          onChange={(e) => set('site', e.target.value)}
        >
          <option value="">Tenant-wide</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>

      <div className={styles.field}>
        <label className={styles.label}>
          Dimension filter (JSON)
          {selectedDataset && (
            <span style={{ fontWeight: 400, color: '#6B7280', marginLeft: '0.5rem' }}>
              Keys: {Object.keys(selectedDataset.dimension_schema || {}).join(', ')}
            </span>
          )}
        </label>
        <textarea
          className={styles.input}
          style={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}
          value={form.dimension_filter}
          onChange={(e) => set('dimension_filter', e.target.value)}
          rows={4}
          placeholder='{"state": "QLD", "dnsp": "Energex", "tariff_type": "residential_tou"}'
        />
        {filterError && <p className={styles.error}>{filterError}</p>}
      </div>

      {selectedDataset?.has_version && (
        <div className={styles.field}>
          <label className={styles.label}>Version pin (leave blank to use latest)</label>
          <input
            className={styles.input}
            value={form.version}
            onChange={(e) => set('version', e.target.value)}
            placeholder="2025-26"
          />
        </div>
      )}

      <div className={styles.inlineFields}>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Effective from</label>
          <input
            type="date"
            className={styles.input}
            value={form.effective_from}
            onChange={(e) => set('effective_from', e.target.value)}
            required
          />
        </div>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label}>Effective to (optional)</label>
          <input
            type="date"
            className={styles.input}
            value={form.effective_to}
            onChange={(e) => set('effective_to', e.target.value)}
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
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.8125rem', color: '#6B7280' }}>
            Filter: <span className={styles.mono}>{JSON.stringify(assignment.dimension_filter)}</span>
            {assignment.version && <> · Version: <span className={styles.mono}>{assignment.version}</span></>}
            {' · '}
            From: <span className={styles.mono}>{assignment.effective_from}</span>
            {assignment.effective_to && (
              <> → <span className={styles.mono}>{assignment.effective_to}</span></>
            )}
          </p>
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
        Rules with <strong>reference_value</strong> conditions will use these assignments to look up
        current values.
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
