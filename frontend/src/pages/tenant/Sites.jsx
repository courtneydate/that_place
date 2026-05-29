/**
 * Sites — list, create, edit, and delete sites for the tenant.
 *
 * Tenant Admins see create, edit, and delete controls.
 * All users see the site table.
 * Ref: SPEC.md § Feature: Sites
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import { useAuth } from '../../context/AuthContext';
import {
  useSites,
  useCreateSite,
  useUpdateSite,
  useDeleteSite,
} from '../../hooks/useSites';
import styles from '../admin/AdminPage.module.css';

function formatCoord(value) {
  if (value === null || value === undefined || value === '') return '—';
  return Number(value).toFixed(5);
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/** Inline create form shown above the table when toggled. */
function CreateSiteForm({ onDone }) {
  const createSite = useCreateSite();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) { setError('Name is required.'); return; }
    try {
      const payload = { name: name.trim(), description: description.trim() };
      if (latitude !== '') payload.latitude = latitude;
      if (longitude !== '') payload.longitude = longitude;
      await createSite.mutateAsync(payload);
      onDone();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Failed to create site.');
    }
  };

  return (
    <section className={styles.section}>
      <h2>New site</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="create-name">Name *</label>
          <input
            id="create-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={styles.input}
            placeholder="e.g. North Reservoir"
            disabled={createSite.isPending}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="create-description">Description</label>
          <input
            id="create-description"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className={styles.input}
            placeholder="Optional description"
            disabled={createSite.isPending}
          />
        </div>
        <div className={styles.inlineFields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="create-lat">Latitude</label>
            <input
              id="create-lat"
              type="number"
              step="any"
              value={latitude}
              onChange={(e) => setLatitude(e.target.value)}
              className={styles.input}
              placeholder="e.g. -33.8688"
              disabled={createSite.isPending}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="create-lng">Longitude</label>
            <input
              id="create-lng"
              type="number"
              step="any"
              value={longitude}
              onChange={(e) => setLongitude(e.target.value)}
              className={styles.input}
              placeholder="e.g. 151.2093"
              disabled={createSite.isPending}
            />
          </div>
        </div>
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={createSite.isPending}
          >
            {createSite.isPending ? 'Creating…' : 'Create site'}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onDone}
            disabled={createSite.isPending}
          >
            Cancel
          </button>
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </section>
  );
}

CreateSiteForm.propTypes = {
  onDone: PropTypes.func.isRequired,
};

/** Inline edit form that replaces a table row when editing. */
function EditSiteRow({ site, onDone }) {
  const updateSite = useUpdateSite(site.id);
  const [name, setName] = useState(site.name || '');
  const [description, setDescription] = useState(site.description || '');
  const [latitude, setLatitude] = useState(
    site.latitude !== null && site.latitude !== undefined ? String(site.latitude) : ''
  );
  const [longitude, setLongitude] = useState(
    site.longitude !== null && site.longitude !== undefined ? String(site.longitude) : ''
  );
  const [isHierarchical, setIsHierarchical] = useState(!!site.is_hierarchical);
  const [tolerance, setTolerance] = useState(
    site.reconciliation_tolerance_percent ?? '1.5',
  );
  const [apportionment, setApportionment] = useState(
    site.common_area_apportionment_method || 'pro_rata_consumption',
  );
  const [exemptionId, setExemptionId] = useState(site.embedded_network_exemption_id || '');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) { setError('Name is required.'); return; }
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        latitude: latitude !== '' ? latitude : null,
        longitude: longitude !== '' ? longitude : null,
        is_hierarchical: isHierarchical,
        reconciliation_tolerance_percent: tolerance,
        common_area_apportionment_method: apportionment,
        embedded_network_exemption_id: exemptionId.trim(),
      };
      await updateSite.mutateAsync(payload);
      onDone();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Failed to update site.');
    }
  };

  return (
    <tr>
      <td colSpan={5}>
        <form onSubmit={handleSubmit} className={styles.form} noValidate>
          <div className={styles.inlineFields}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`edit-name-${site.id}`}>Name *</label>
              <input
                id={`edit-name-${site.id}`}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={styles.input}
                disabled={updateSite.isPending}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`edit-desc-${site.id}`}>Description</label>
              <input
                id={`edit-desc-${site.id}`}
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className={styles.input}
                disabled={updateSite.isPending}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`edit-lat-${site.id}`}>Latitude</label>
              <input
                id={`edit-lat-${site.id}`}
                type="number"
                step="any"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
                className={styles.input}
                disabled={updateSite.isPending}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`edit-lng-${site.id}`}>Longitude</label>
              <input
                id={`edit-lng-${site.id}`}
                type="number"
                step="any"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
                className={styles.input}
                disabled={updateSite.isPending}
              />
            </div>
          </div>
          <fieldset style={{ border: '1px solid #E5E7EB', borderRadius: 6, padding: '0.75rem 1rem', marginTop: '0.5rem' }}>
            <legend style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#374151', padding: '0 0.4rem' }}>
              Embedded-network / hierarchical metering
            </legend>
            <div className={styles.inlineFields}>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`edit-hier-${site.id}`}>
                  <input
                    id={`edit-hier-${site.id}`}
                    type="checkbox"
                    checked={isHierarchical}
                    onChange={(e) => setIsHierarchical(e.target.checked)}
                    disabled={updateSite.isPending}
                    style={{ marginRight: '0.4rem' }}
                  />
                  Hierarchical site
                </label>
                <small style={{ color: '#6B7280' }}>
                  Enables gate / child / common-area meter roles.
                </small>
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`edit-tol-${site.id}`}>Reconciliation tolerance %</label>
                <input
                  id={`edit-tol-${site.id}`}
                  type="number"
                  step="0.1"
                  min="0"
                  max="100"
                  value={tolerance}
                  onChange={(e) => setTolerance(e.target.value)}
                  className={styles.input}
                  disabled={updateSite.isPending}
                />
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`edit-app-${site.id}`}>Common-area apportionment</label>
                <select
                  id={`edit-app-${site.id}`}
                  value={apportionment}
                  onChange={(e) => setApportionment(e.target.value)}
                  className={styles.input}
                  disabled={updateSite.isPending}
                >
                  <option value="pro_rata_consumption">Pro-rata by consumption</option>
                  <option value="equal_share">Equal share</option>
                  <option value="by_floor_area">By floor area (NLA)</option>
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={`edit-exempt-${site.id}`}>AER exemption / registration ID</label>
                <input
                  id={`edit-exempt-${site.id}`}
                  type="text"
                  value={exemptionId}
                  onChange={(e) => setExemptionId(e.target.value)}
                  className={styles.input}
                  placeholder="Optional reference"
                  disabled={updateSite.isPending}
                />
              </div>
            </div>
          </fieldset>
          <div className={styles.actions}>
            <button
              type="submit"
              className={styles.primaryButton}
              disabled={updateSite.isPending}
            >
              {updateSite.isPending ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={onDone}
              disabled={updateSite.isPending}
            >
              Cancel
            </button>
          </div>
          {error && <p className={styles.error}>{error}</p>}
        </form>
      </td>
    </tr>
  );
}

EditSiteRow.propTypes = {
  site: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string,
    description: PropTypes.string,
    latitude: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    longitude: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    is_hierarchical: PropTypes.bool,
    reconciliation_tolerance_percent: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    common_area_apportionment_method: PropTypes.string,
    embedded_network_exemption_id: PropTypes.string,
  }).isRequired,
  onDone: PropTypes.func.isRequired,
};

function Sites() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  const { data: sites = [], isLoading, isError } = useSites();
  const deleteSite = useDeleteSite();

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const handleDelete = async (siteId, siteName) => {
    if (!window.confirm(`Delete site "${siteName}"? This cannot be undone.`)) return;
    try {
      await deleteSite.mutateAsync(siteId);
      if (editingId === siteId) setEditingId(null);
    } catch (err) {
      alert(err.response?.data?.error?.message || 'Failed to delete site.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Sites</h1>
        {isAdmin && (
          <button
            className={styles.primaryButton}
            onClick={() => setShowCreateForm((v) => !v)}
          >
            {showCreateForm ? 'Cancel' : '+ New site'}
          </button>
        )}
      </div>

      {isAdmin && showCreateForm && (
        <CreateSiteForm onDone={() => setShowCreateForm(false)} />
      )}

      <section className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load sites.</p>}
        {!isLoading && !isError && sites.length === 0 && (
          <p className={styles.empty}>No sites yet.</p>
        )}
        {!isLoading && !isError && sites.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Latitude</th>
                <th>Longitude</th>
                <th>Created</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {sites.map((site) =>
                editingId === site.id ? (
                  <EditSiteRow
                    key={site.id}
                    site={site}
                    onDone={() => setEditingId(null)}
                  />
                ) : (
                  <tr key={site.id}>
                    <td>{site.name}</td>
                    <td>{site.description || '—'}</td>
                    <td>{formatCoord(site.latitude)}</td>
                    <td>{formatCoord(site.longitude)}</td>
                    <td>{formatDate(site.created_at)}</td>
                    {isAdmin && (
                      <td>
                        <div className={styles.actions} style={{ marginTop: 0 }}>
                          <button
                            className={styles.secondaryButton}
                            onClick={() => setEditingId(site.id)}
                          >
                            Edit
                          </button>
                          <button
                            className={styles.dangerButton}
                            onClick={() => handleDelete(site.id, site.name)}
                            disabled={deleteSite.isPending}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                )
              )}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default Sites;
