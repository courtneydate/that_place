/**
 * Data Sources — Tenant Admin page.
 *
 * Lists connected data sources. Tenant Admin can add a new data source via
 * the two-phase connection wizard (credentials → discover → select devices
 * → configure streams → connect) and manage connected devices.
 *
 * Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { useSites } from '../../hooks/useSites';
import {
  useConnectDevices,
  useDataSourceDevices,
  useDataSources,
  useDeactivateDataSourceDevice,
  useDeleteDataSource,
  useDiscoverDevices,
  useProviders,
} from '../../hooks/useIntegrations';
import { useCreateDataSource } from '../../hooks/useIntegrations';
import styles from '../admin/AdminPage.module.css';

const POLL_STATUS_LABELS = {
  ok: 'OK',
  error: 'Error',
  auth_failure: 'Auth failure',
};

const POLL_STATUS_COLORS = {
  ok: 'var(--success)',
  error: 'var(--danger)',
  auth_failure: 'var(--danger)',
};

// ---------------------------------------------------------------------------
// Wizard — Step 1: pick provider + enter credentials
// ---------------------------------------------------------------------------

function WizardStep1({ providers, onNext, onCancel }) {
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [dsName, setDsName] = useState('');
  const [creds, setCreds] = useState({});
  const [error, setError] = useState('');
  const createDataSource = useCreateDataSource();

  const provider = providers.find((p) => p.id === Number(selectedProviderId));

  const handleNext = async (e) => {
    e.preventDefault();
    setError('');
    if (!provider) { setError('Please select a provider.'); return; }
    if (!dsName.trim()) { setError('Please enter a name for this connection.'); return; }

    // Validate required credential fields
    const missing = (provider.auth_param_schema || []).filter(
      (f) => f.required && !creds[f.key]?.trim(),
    );
    if (missing.length) {
      setError(`Missing required credentials: ${missing.map((f) => f.label).join(', ')}`);
      return;
    }

    try {
      const ds = await createDataSource.mutateAsync({
        provider: provider.id,
        name: dsName,
        credentials: creds,
      });
      onNext(ds, provider);
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Failed to create data source.');
    }
  };

  return (
    <div>
      <h3>Step 1 of 3 — Connect a provider</h3>
      <form onSubmit={handleNext} className={styles.form} noValidate>
        <div className={styles.field}>
          <label className={styles.label}>Provider *</label>
          <select
            value={selectedProviderId}
            onChange={(e) => { setSelectedProviderId(e.target.value); setCreds({}); }}
            className={styles.input}
            disabled={createDataSource.isPending}
          >
            <option value="">— Select a provider —</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        {provider && provider.description && (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '0.75rem' }}>
            {provider.description}
          </p>
        )}
        <div className={styles.field}>
          <label className={styles.label}>Connection name *</label>
          <input
            type="text"
            value={dsName}
            onChange={(e) => setDsName(e.target.value)}
            className={styles.input}
            placeholder={provider ? `My ${provider.name} account` : 'e.g. Farm North sensors'}
            disabled={createDataSource.isPending}
          />
        </div>

        {provider && (provider.auth_param_schema || []).length > 0 && (
          <>
            <p className={styles.label} style={{ marginBottom: '0.5rem', fontWeight: 600 }}>
              {provider.name} credentials
            </p>
            {provider.auth_param_schema.map((field) => (
              <div key={field.key} className={styles.field}>
                <label className={styles.label}>
                  {field.label}
                  {field.required && ' *'}
                </label>
                <input
                  type={field.type === 'password' ? 'password' : 'text'}
                  value={creds[field.key] || ''}
                  onChange={(e) => setCreds((c) => ({ ...c, [field.key]: e.target.value }))}
                  className={styles.input}
                  disabled={createDataSource.isPending}
                />
              </div>
            ))}
          </>
        )}

        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={createDataSource.isPending || !provider}
          >
            {createDataSource.isPending ? 'Connecting…' : 'Next: Discover devices →'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onCancel}>
            Cancel
          </button>
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </div>
  );
}

WizardStep1.propTypes = {
  providers: PropTypes.arrayOf(PropTypes.object).isRequired,
  onNext: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Wizard — Step 2: discover devices + select + assign sites
// ---------------------------------------------------------------------------

function WizardStep2({ ds, provider, sites, onNext, onBack }) {
  const discover = useDiscoverDevices(ds.id);
  const [discovered, setDiscovered] = useState(null);
  const [selected, setSelected] = useState({});
  const [siteAssignments, setSiteAssignments] = useState({});
  const [defaultSiteId, setDefaultSiteId] = useState('');
  const [error, setError] = useState('');

  const handleDiscover = async () => {
    setError('');
    try {
      const result = await discover.mutateAsync();
      const available = (result.devices || []).filter((d) => !d.already_connected);
      setDiscovered(result.devices || []);
      // Pre-select all non-connected devices
      const sel = {};
      available.forEach((d) => { sel[d.external_device_id] = true; });
      setSelected(sel);
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Discovery failed.');
    }
  };

  const handleDefaultSiteChange = (siteId) => {
    setDefaultSiteId(siteId);
    // Apply to all unassigned
    setSiteAssignments((prev) => {
      const next = { ...prev };
      (discovered || []).forEach((d) => {
        if (!prev[d.external_device_id]) next[d.external_device_id] = siteId;
      });
      return next;
    });
  };

  const toggleAll = (checked) => {
    const next = {};
    (discovered || []).filter((d) => !d.already_connected).forEach((d) => {
      next[d.external_device_id] = checked;
    });
    setSelected(next);
  };

  const selectedDevices = (discovered || []).filter(
    (d) => !d.already_connected && selected[d.external_device_id],
  );

  const handleNext = () => {
    if (!selectedDevices.length) { setError('Select at least one device.'); return; }
    const missingSite = selectedDevices.find(
      (d) => !siteAssignments[d.external_device_id] && !defaultSiteId,
    );
    if (missingSite) { setError('Assign a site to all selected devices.'); return; }
    setError('');
    onNext(selectedDevices.map((d) => ({
      ...d,
      site_id: Number(siteAssignments[d.external_device_id] || defaultSiteId),
    })));
  };

  const availableCount = (discovered || []).filter((d) => !d.already_connected).length;
  const allSelected = availableCount > 0 && selectedDevices.length === availableCount;

  return (
    <div>
      <h3>Step 2 of 3 — Discover &amp; select devices</h3>

      {!discovered && (
        <div>
          <p style={{ color: 'var(--text-muted)', marginBottom: '1rem' }}>
            Click below to connect to {provider.name} and fetch the list of devices on your account.
          </p>
          <button
            className={styles.primaryButton}
            onClick={handleDiscover}
            disabled={discover.isPending}
          >
            {discover.isPending ? 'Discovering…' : 'Discover devices'}
          </button>
          {error && <p className={styles.error} style={{ marginTop: '0.5rem' }}>{error}</p>}
        </div>
      )}

      {discovered && (
        <>
          <div className={styles.inlineFields} style={{ marginBottom: '1rem', alignItems: 'flex-end' }}>
            <div className={styles.field}>
              <label className={styles.label}>Default site (applies to all)</label>
              <select
                value={defaultSiteId}
                onChange={(e) => handleDefaultSiteChange(e.target.value)}
                className={styles.input}
              >
                <option value="">— Select a site —</option>
                {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          </div>

          <table className={styles.table}>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={(e) => toggleAll(e.target.checked)}
                    disabled={availableCount === 0}
                  />
                </th>
                <th>Device name</th>
                <th>External ID</th>
                <th>Site</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {discovered.map((d) => (
                <tr key={d.external_device_id} style={{ opacity: d.already_connected ? 0.5 : 1 }}>
                  <td>
                    <input
                      type="checkbox"
                      checked={!d.already_connected && !!selected[d.external_device_id]}
                      onChange={(e) =>
                        setSelected((s) => ({ ...s, [d.external_device_id]: e.target.checked }))
                      }
                      disabled={d.already_connected}
                    />
                  </td>
                  <td>{d.external_device_name || '—'}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>{d.external_device_id}</td>
                  <td>
                    {d.already_connected ? (
                      <span style={{ color: 'var(--text-muted)' }}>Already connected</span>
                    ) : (
                      <select
                        value={siteAssignments[d.external_device_id] || defaultSiteId}
                        onChange={(e) =>
                          setSiteAssignments((a) => ({
                            ...a,
                            [d.external_device_id]: e.target.value,
                          }))
                        }
                        className={styles.input}
                        style={{ padding: '0.2rem 0.4rem', fontSize: '0.85rem' }}
                        disabled={!selected[d.external_device_id]}
                      >
                        <option value="">— Site —</option>
                        {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    )}
                  </td>
                  <td>
                    {d.already_connected && (
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Connected</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.5rem' }}>
            {selectedDevices.length} of {availableCount} device(s) selected.
          </p>
          {error && <p className={styles.error}>{error}</p>}

          <div className={styles.actions} style={{ marginTop: '1rem' }}>
            <button className={styles.primaryButton} onClick={handleNext}>
              Next: Configure streams →
            </button>
            <button className={styles.secondaryButton} onClick={onBack}>
              ← Back
            </button>
          </div>
        </>
      )}

      {!discovered && (
        <button className={styles.secondaryButton} onClick={onBack} style={{ marginTop: '0.5rem' }}>
          ← Back
        </button>
      )}
    </div>
  );
}

WizardStep2.propTypes = {
  ds: PropTypes.object.isRequired,
  provider: PropTypes.object.isRequired,
  sites: PropTypes.arrayOf(PropTypes.object).isRequired,
  onNext: PropTypes.func.isRequired,
  onBack: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Wizard — Step 3: configure streams (batch)
// ---------------------------------------------------------------------------

function WizardStep3({ ds, provider, selectedDevices, onDone, onBack }) {
  const connect = useConnectDevices(ds.id);
  const availableStreams = provider.available_streams || [];

  const [streamConfig, setStreamConfig] = useState(
    availableStreams.reduce((acc, s) => ({
      ...acc,
      [s.key]: { active: true, label: s.label, unit: s.unit },
    }), {}),
  );
  const [error, setError] = useState('');

  const activeKeys = Object.entries(streamConfig)
    .filter(([, v]) => v.active)
    .map(([k]) => k);

  const handleConnect = async () => {
    if (!activeKeys.length) { setError('Activate at least one stream.'); return; }
    setError('');

    const payload = selectedDevices.map((d) => ({
      external_device_id: d.external_device_id,
      external_device_name: d.external_device_name,
      site_id: d.site_id,
      active_stream_keys: activeKeys,
      stream_overrides: activeKeys.reduce((acc, key) => {
        const cfg = streamConfig[key];
        const def = availableStreams.find((s) => s.key === key) || {};
        if (cfg.label !== def.label || cfg.unit !== def.unit) {
          acc[key] = { label: cfg.label, unit: cfg.unit };
        }
        return acc;
      }, {}),
    }));

    try {
      await connect.mutateAsync(payload);
      onDone();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Failed to connect devices.');
    }
  };

  return (
    <div>
      <h3>Step 3 of 3 — Configure streams</h3>
      <p style={{ color: 'var(--text-muted)', marginBottom: '1rem', fontSize: '0.9rem' }}>
        These settings apply to all {selectedDevices.length} selected device(s).
        You can adjust individual devices later from the Streams tab.
      </p>

      {availableStreams.length === 0 ? (
        <p className={styles.empty}>No streams defined for this provider.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Activate</th>
              <th>Stream key</th>
              <th>Label</th>
              <th>Unit</th>
              <th>Data type</th>
            </tr>
          </thead>
          <tbody>
            {availableStreams.map((s) => {
              const cfg = streamConfig[s.key] || { active: false, label: s.label, unit: s.unit };
              return (
                <tr key={s.key}>
                  <td>
                    <input
                      type="checkbox"
                      checked={cfg.active}
                      onChange={(e) =>
                        setStreamConfig((prev) => ({
                          ...prev,
                          [s.key]: { ...prev[s.key], active: e.target.checked },
                        }))
                      }
                    />
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>{s.key}</td>
                  <td>
                    <input
                      type="text"
                      value={cfg.label}
                      onChange={(e) =>
                        setStreamConfig((prev) => ({
                          ...prev,
                          [s.key]: { ...prev[s.key], label: e.target.value },
                        }))
                      }
                      className={styles.input}
                      style={{ padding: '0.2rem 0.4rem', fontSize: '0.85rem' }}
                      disabled={!cfg.active}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      value={cfg.unit}
                      onChange={(e) =>
                        setStreamConfig((prev) => ({
                          ...prev,
                          [s.key]: { ...prev[s.key], unit: e.target.value },
                        }))
                      }
                      className={styles.input}
                      style={{ padding: '0.2rem 0.4rem', fontSize: '0.85rem' }}
                      disabled={!cfg.active}
                    />
                  </td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{s.data_type}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.actions} style={{ marginTop: '1rem' }}>
        <button
          className={styles.primaryButton}
          onClick={handleConnect}
          disabled={connect.isPending}
        >
          {connect.isPending
            ? 'Connecting…'
            : `Connect ${selectedDevices.length} device(s)`}
        </button>
        <button className={styles.secondaryButton} onClick={onBack} disabled={connect.isPending}>
          ← Back
        </button>
      </div>
    </div>
  );
}

WizardStep3.propTypes = {
  ds: PropTypes.object.isRequired,
  provider: PropTypes.object.isRequired,
  selectedDevices: PropTypes.arrayOf(PropTypes.object).isRequired,
  onDone: PropTypes.func.isRequired,
  onBack: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Wizard wrapper
// ---------------------------------------------------------------------------

/**
 * Re-discovery flow for an existing DataSource.
 * Skips Step 1 (credential entry — credentials already saved on the DataSource)
 * and starts directly at Step 2 (discover + select) → Step 3 (streams + connect).
 */
function AddDevicesFlow({ ds, provider, sites, onDone }) {
  const [step, setStep] = useState(2);
  const [selectedDevices, setSelectedDevices] = useState([]);

  if (step === 2) {
    return (
      <WizardStep2
        ds={ds}
        provider={provider}
        sites={sites}
        onNext={(devices) => { setSelectedDevices(devices); setStep(3); }}
        onBack={onDone}
      />
    );
  }

  return (
    <WizardStep3
      ds={ds}
      provider={provider}
      selectedDevices={selectedDevices}
      onDone={onDone}
      onBack={() => setStep(2)}
    />
  );
}

AddDevicesFlow.propTypes = {
  ds: PropTypes.object.isRequired,
  provider: PropTypes.object.isRequired,
  sites: PropTypes.arrayOf(PropTypes.object).isRequired,
  onDone: PropTypes.func.isRequired,
};

function AddDataSourceWizard({ providers, sites, onDone }) {
  const [step, setStep] = useState(1);
  const [ds, setDs] = useState(null);
  const [provider, setProvider] = useState(null);
  const [selectedDevices, setSelectedDevices] = useState([]);

  if (step === 1) {
    return (
      <WizardStep1
        providers={providers}
        onNext={(newDs, newProvider) => {
          setDs(newDs);
          setProvider(newProvider);
          setStep(2);
        }}
        onCancel={onDone}
      />
    );
  }

  if (step === 2) {
    return (
      <WizardStep2
        ds={ds}
        provider={provider}
        sites={sites}
        onNext={(devices) => { setSelectedDevices(devices); setStep(3); }}
        onBack={() => setStep(1)}
      />
    );
  }

  return (
    <WizardStep3
      ds={ds}
      provider={provider}
      selectedDevices={selectedDevices}
      onDone={onDone}
      onBack={() => setStep(2)}
    />
  );
}

AddDataSourceWizard.propTypes = {
  providers: PropTypes.arrayOf(PropTypes.object).isRequired,
  sites: PropTypes.arrayOf(PropTypes.object).isRequired,
  onDone: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Connected devices panel for an expanded DataSource row
// ---------------------------------------------------------------------------

function ConnectedDevicesPanel({ ds }) {
  const { data: devices = [], isLoading } = useDataSourceDevices(ds.id);
  const deactivate = useDeactivateDataSourceDevice(ds.id);
  const [deactivateError, setDeactivateError] = useState('');

  const handleDeactivate = async (dsd) => {
    if (!window.confirm(`Remove "${dsd.external_device_name || dsd.external_device_id}" from this data source? Polling will stop but history is kept.`)) return;
    setDeactivateError('');
    try {
      await deactivate.mutateAsync(dsd.id);
    } catch (err) {
      setDeactivateError(err.response?.data?.error?.message || 'Failed to remove device.');
    }
  };

  if (isLoading) return <p className={styles.loading} style={{ padding: '0.5rem 1rem' }}>Loading devices…</p>;

  const active = devices.filter((d) => d.is_active);

  return (
    <div style={{ padding: '0.75rem 1rem', background: 'var(--surface-raised, #f9f9f9)', borderTop: '1px solid var(--border)' }}>
      {deactivateError && <p className={styles.error}>{deactivateError}</p>}
      {active.length === 0 ? (
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No active devices connected.</p>
      ) : (
        <table className={styles.table} style={{ margin: 0 }}>
          <thead>
            <tr>
              <th>Device name</th>
              <th>Site</th>
              <th>Last polled</th>
              <th>Poll status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {active.map((dsd) => (
              <tr key={dsd.id}>
                <td>{dsd.virtual_device_detail?.name || dsd.external_device_name || dsd.external_device_id}</td>
                <td>{dsd.virtual_device_detail?.site_name || '—'}</td>
                <td style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  {dsd.last_polled_at
                    ? new Date(dsd.last_polled_at).toLocaleString()
                    : 'Never'}
                </td>
                <td>
                  {dsd.last_poll_status ? (
                    <span style={{ color: POLL_STATUS_COLORS[dsd.last_poll_status] || 'inherit' }}>
                      {POLL_STATUS_LABELS[dsd.last_poll_status] || dsd.last_poll_status}
                      {dsd.consecutive_poll_failures > 0 && ` (${dsd.consecutive_poll_failures} fails)`}
                    </span>
                  ) : '—'}
                </td>
                <td>
                  <button
                    className={styles.dangerButton}
                    style={{ fontSize: '0.8rem', padding: '0.2rem 0.5rem' }}
                    onClick={() => handleDeactivate(dsd)}
                    disabled={deactivate.isPending}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

ConnectedDevicesPanel.propTypes = {
  ds: PropTypes.object.isRequired,
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function DataSources() {
  const { data: dataSources = [], isLoading, isError } = useDataSources();
  const { data: providers = [] } = useProviders();
  const { data: sites = [] } = useSites();
  const deleteDs = useDeleteDataSource();

  const [showWizard, setShowWizard] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [addingDevicesForId, setAddingDevicesForId] = useState(null);
  const [deleteError, setDeleteError] = useState('');

  const handleDelete = async (ds) => {
    if (!window.confirm(`Delete data source "${ds.name}"? All connected devices will also be removed.`)) return;
    setDeleteError('');
    try {
      await deleteDs.mutateAsync(ds.id);
      if (expandedId === ds.id) setExpandedId(null);
    } catch (err) {
      setDeleteError(err.response?.data?.error?.message || 'Failed to delete data source.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Data Sources</h1>
        <button
          className={styles.primaryButton}
          onClick={() => setShowWizard((v) => !v)}
          disabled={providers.length === 0}
        >
          {showWizard ? 'Cancel' : '+ Add data source'}
        </button>
      </div>

      {providers.length === 0 && !isLoading && (
        <p style={{ color: 'var(--text-muted)', marginBottom: '1rem' }}>
          No API providers are configured yet. Ask your That Place Admin to add a provider.
        </p>
      )}

      {deleteError && <p className={styles.error}>{deleteError}</p>}

      {showWizard && (
        <section className={styles.section}>
          <AddDataSourceWizard
            providers={providers}
            sites={sites}
            onDone={() => setShowWizard(false)}
          />
        </section>
      )}

      <section className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load data sources.</p>}
        {!isLoading && !isError && dataSources.length === 0 && (
          <p className={styles.empty}>No data sources connected yet.</p>
        )}
        {!isLoading && !isError && dataSources.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Provider</th>
                <th>Devices</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {dataSources.map((ds) => (
                <React.Fragment key={ds.id}>
                  <tr>
                    <td>{ds.name}</td>
                    <td>{ds.provider_name}</td>
                    <td>{ds.connected_device_count}</td>
                    <td>
                      <span style={{ color: ds.is_active ? 'var(--success)' : 'var(--text-muted)' }}>
                        {ds.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td style={{ display: 'flex', gap: '0.4rem' }}>
                      <button
                        className={styles.secondaryButton}
                        onClick={() => setExpandedId(expandedId === ds.id ? null : ds.id)}
                        style={{ fontSize: '0.85rem' }}
                      >
                        {expandedId === ds.id ? 'Hide devices' : 'Devices'}
                      </button>
                      <button
                        className={styles.secondaryButton}
                        onClick={() => {
                          setAddingDevicesForId(ds.id);
                          setShowWizard(false);
                        }}
                        style={{ fontSize: '0.85rem' }}
                        disabled={addingDevicesForId === ds.id}
                      >
                        Add devices
                      </button>
                      <button
                        className={styles.dangerButton}
                        onClick={() => handleDelete(ds)}
                        disabled={deleteDs.isPending}
                        style={{ fontSize: '0.85rem' }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                  {addingDevicesForId === ds.id && (() => {
                    const dsProvider = providers.find((p) => p.id === ds.provider);
                    if (!dsProvider) return (
                      <tr>
                        <td colSpan={5} style={{ padding: '1rem', color: 'var(--danger)' }}>
                          Provider data not yet loaded — please try again in a moment.
                        </td>
                      </tr>
                    );
                    return (
                      <tr>
                        <td colSpan={5} style={{ padding: 0 }}>
                          <div style={{ padding: '1rem', background: 'var(--surface-raised, #f9f9f9)', borderTop: '1px solid var(--border)' }}>
                            <AddDevicesFlow
                              ds={ds}
                              provider={dsProvider}
                              sites={sites}
                              onDone={() => setAddingDevicesForId(null)}
                            />
                          </div>
                        </td>
                      </tr>
                    );
                  })()}
                  {expandedId === ds.id && (
                    <tr>
                      <td colSpan={5} style={{ padding: 0 }}>
                        <ConnectedDevicesPanel ds={ds} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default DataSources;
