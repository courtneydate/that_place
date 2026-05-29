/**
 * Billing Account detail — Sprint 30.
 *
 * Four tabs: Info, Meters, Tariffs, Audit log. Tenant Admin write, others
 * read-only.
 *
 * Ref: SPEC.md § Feature: Billing Accounts & Tariffs
 *      ROADMAP.md § Sprint 30
 */
import { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  useBillingAccount,
  useBillingAccountAuditLog,
  useBillingAccountMeters,
  useBillingAccountTariffs,
  useCreateBillingAccountMeter,
  useCreateBillingAccountTariff,
  useDeleteBillingAccountMeter,
  useDeleteBillingAccountTariff,
  usePatchBillingAccount,
} from '../../hooks/useBillingAccounts';
import { useDevices } from '../../hooks/useDevices';
import { useDeviceStreams } from '../../hooks/useStreams';
import { useReferenceDatasets } from '../../hooks/useFeeds';
import styles from '../admin/AdminPage.module.css';
import detailStyles from './DeviceDetail.module.css';

const ACCOUNT_TYPE_LABELS = {
  ppa_host: 'PPA host',
  en_tenant: 'EN tenant',
  internal: 'Internal',
};

const AUDIT_ACTION_LABELS = {
  created: 'Created',
  updated: 'Updated',
  deactivated: 'Deactivated',
};

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function TabBar({ active, onChange }) {
  const tabs = ['Info', 'Meters', 'Tariffs', 'Audit log'];
  return (
    <div className={detailStyles.tabBar}>
      {tabs.map((tab) => (
        <button
          key={tab}
          className={`${detailStyles.tab} ${active === tab ? detailStyles.tabActive : ''}`}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

TabBar.propTypes = {
  active: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Info tab — read + edit basic fields
// ---------------------------------------------------------------------------

function InfoTab({ account, canEdit }) {
  const patch = usePatchBillingAccount(account.id);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(account);
  const [error, setError] = useState('');

  const handleStart = () => {
    setForm(account);
    setEditing(true);
    setError('');
  };

  const handleCancel = () => {
    setEditing(false);
    setError('');
  };

  const handleSave = async () => {
    setError('');
    try {
      await patch.mutateAsync({
        name: form.name,
        contact_email: form.contact_email || '',
        contact_phone: form.contact_phone || '',
        abn: form.abn || '',
        account_type: form.account_type,
        floor_area_sqm: form.floor_area_sqm === '' ? null : form.floor_area_sqm,
        invoice_email_recipients: form.invoice_email_recipients || [],
        billing_address: form.billing_address || {},
        activated_at: form.activated_at || null,
        deactivated_at: form.deactivated_at || null,
      });
      setEditing(false);
    } catch (err) {
      const details = err.response?.data?.error?.details;
      if (details) {
        const first = Object.entries(details)[0];
        setError(`${first[0]}: ${Array.isArray(first[1]) ? first[1].join(' ') : first[1]}`);
      } else {
        setError(err.response?.data?.error?.message || 'Save failed.');
      }
    }
  };

  const display = editing ? form : account;

  return (
    <div>
      {canEdit && (
        <div style={{ marginBottom: '0.75rem' }}>
          {editing ? (
            <>
              <button
                className={styles.primaryButton}
                onClick={handleSave}
                disabled={patch.isPending}
              >
                {patch.isPending ? 'Saving…' : 'Save'}
              </button>
              <button
                className={styles.secondaryButton}
                onClick={handleCancel}
                disabled={patch.isPending}
                style={{ marginLeft: '0.5rem' }}
              >
                Cancel
              </button>
            </>
          ) : (
            <button className={styles.secondaryButton} onClick={handleStart}>
              Edit
            </button>
          )}
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}

      <div className={detailStyles.infoGrid}>
        <Field label="Name">
          {editing ? (
            <input
              className={styles.input}
              value={display.name || ''}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          ) : (display.name || '—')}
        </Field>
        <Field label="Customer reference">
          <span className={styles.mono}>{display.customer_reference || '—'}</span>
        </Field>
        <Field label="Account type">
          {editing ? (
            <select
              className={styles.input}
              value={display.account_type}
              onChange={(e) => setForm({ ...form, account_type: e.target.value })}
            >
              <option value="ppa_host">PPA host</option>
              <option value="en_tenant">EN tenant</option>
              <option value="internal">Internal</option>
            </select>
          ) : (ACCOUNT_TYPE_LABELS[display.account_type] || display.account_type)}
        </Field>
        <Field label="Contact email">
          {editing ? (
            <input
              type="email"
              className={styles.input}
              value={display.contact_email || ''}
              onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
            />
          ) : (display.contact_email || '—')}
        </Field>
        <Field label="Contact phone">
          {editing ? (
            <input
              type="tel"
              className={styles.input}
              value={display.contact_phone || ''}
              onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
            />
          ) : (display.contact_phone || '—')}
        </Field>
        <Field label="ABN">
          {editing ? (
            <input
              className={styles.input}
              value={display.abn || ''}
              onChange={(e) => setForm({ ...form, abn: e.target.value })}
            />
          ) : (<span className={styles.mono}>{display.abn || '—'}</span>)}
        </Field>
        <Field label="Floor area (sqm)">
          {editing ? (
            <input
              type="number"
              step="0.01"
              className={styles.input}
              value={display.floor_area_sqm ?? ''}
              onChange={(e) => setForm({ ...form, floor_area_sqm: e.target.value })}
            />
          ) : (display.floor_area_sqm ?? '—')}
        </Field>
        <Field label="Activated">
          {editing ? (
            <input
              type="datetime-local"
              className={styles.input}
              value={display.activated_at ? display.activated_at.slice(0, 16) : ''}
              onChange={(e) => setForm({ ...form, activated_at: e.target.value })}
            />
          ) : formatDateTime(display.activated_at)}
        </Field>
        <Field label="Deactivated">
          {editing ? (
            <input
              type="datetime-local"
              className={styles.input}
              value={display.deactivated_at ? display.deactivated_at.slice(0, 16) : ''}
              onChange={(e) => setForm({ ...form, deactivated_at: e.target.value })}
            />
          ) : formatDateTime(display.deactivated_at)}
        </Field>
        <Field label="Created">
          {formatDateTime(display.created_at)}
        </Field>
      </div>
    </div>
  );
}

InfoTab.propTypes = {
  account: PropTypes.object.isRequired,
  canEdit: PropTypes.bool.isRequired,
};

function Field({ label, children }) {
  return (
    <div className={detailStyles.infoItem}>
      <span className={detailStyles.infoLabel}>{label}</span>
      <span className={detailStyles.infoValue}>{children}</span>
    </div>
  );
}

Field.propTypes = {
  label: PropTypes.string.isRequired,
  children: PropTypes.node,
};

// ---------------------------------------------------------------------------
// Meters tab — list + add stream link
// ---------------------------------------------------------------------------

function StreamPicker({ onPick, excludeStreamIds = [] }) {
  const { data: devices = [] } = useDevices();
  const [deviceId, setDeviceId] = useState('');
  const { data: streams = [] } = useDeviceStreams(deviceId);

  const eligible = streams.filter(
    (s) => s.billing_role && !excludeStreamIds.includes(s.id),
  );

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
      <select
        value={deviceId}
        onChange={(e) => setDeviceId(e.target.value)}
        className={styles.input}
      >
        <option value="">— Select device —</option>
        {devices.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} ({d.serial_number})
          </option>
        ))}
      </select>
      <select
        value=""
        disabled={!deviceId}
        onChange={(e) => {
          if (e.target.value) onPick(Number(e.target.value));
        }}
        className={styles.input}
      >
        <option value="">
          {deviceId
            ? (eligible.length ? '— Select stream with billing role —' : 'No eligible streams on this device')
            : 'Select a device first'}
        </option>
        {eligible.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label || s.key} · {s.billing_role}
          </option>
        ))}
      </select>
    </div>
  );
}

StreamPicker.propTypes = {
  onPick: PropTypes.func.isRequired,
  excludeStreamIds: PropTypes.array,
};

function MetersTab({ accountId, canEdit }) {
  const { data: links = [], isLoading } = useBillingAccountMeters(accountId);
  const createLink = useCreateBillingAccountMeter(accountId);
  const deleteLink = useDeleteBillingAccountMeter(accountId);
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [error, setError] = useState('');

  const linkedStreamIds = useMemo(() => links.map((l) => l.stream), [links]);

  const handleAdd = async (streamId) => {
    setError('');
    if (!effectiveFrom) {
      setError('Set an effective from date first.');
      return;
    }
    try {
      await createLink.mutateAsync({
        stream: streamId,
        effective_from: effectiveFrom,
      });
    } catch (err) {
      const details = err.response?.data?.error?.details;
      if (details?.stream) {
        setError(Array.isArray(details.stream) ? details.stream.join(' ') : details.stream);
      } else {
        setError(err.response?.data?.error?.message || 'Failed to link stream.');
      }
    }
  };

  const handleDelete = async (linkId) => {
    if (!window.confirm('Remove this meter link?')) return;
    try {
      await deleteLink.mutateAsync(linkId);
    } catch (err) {
      window.alert(err.response?.data?.error?.message || 'Failed to remove.');
    }
  };

  return (
    <div>
      {canEdit && (
        <section className={styles.section} style={{ marginTop: 0 }}>
          <h3 style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem' }}>Link a billable stream</h3>
          <p style={{ fontSize: '0.8125rem', color: '#6B7280', margin: '0 0 0.5rem' }}>
            Only streams tagged with a billing role (Sprint 29) appear here. Set the
            effective from date, then pick a device + stream — the link is created on
            selection.
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-end', marginBottom: '0.5rem' }}>
            <div className={styles.field} style={{ marginBottom: 0 }}>
              <label className={styles.label}>Effective from *</label>
              <input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
                className={styles.input}
              />
            </div>
          </div>
          <StreamPicker onPick={handleAdd} excludeStreamIds={linkedStreamIds} />
          {error && <p className={styles.error}>{error}</p>}
        </section>
      )}

      {isLoading ? (
        <p className={styles.loading}>Loading…</p>
      ) : links.length === 0 ? (
        <p className={styles.empty}>No streams linked yet.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Device</th>
              <th>Stream</th>
              <th>Billing role</th>
              <th>Effective from</th>
              <th>Effective to</th>
              {canEdit && <th></th>}
            </tr>
          </thead>
          <tbody>
            {links.map((link) => (
              <tr key={link.id}>
                <td>{link.device_name} <span className={styles.mono} style={{ color: '#9CA3AF' }}>({link.device_serial})</span></td>
                <td>{link.stream_label}</td>
                <td>{link.stream_billing_role}</td>
                <td>{formatDate(link.effective_from)}</td>
                <td>{formatDate(link.effective_to)}</td>
                {canEdit && (
                  <td>
                    <button
                      className={styles.dangerButton}
                      onClick={() => handleDelete(link.id)}
                      disabled={deleteLink.isPending}
                    >
                      Remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

MetersTab.propTypes = {
  accountId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  canEdit: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Tariffs tab — list + add tariff assignment
// ---------------------------------------------------------------------------

function TariffsTab({ accountId, canEdit }) {
  const { data: assignments = [], isLoading } = useBillingAccountTariffs(accountId);
  const { data: datasets = [] } = useReferenceDatasets();
  const createAssignment = useCreateBillingAccountTariff(accountId);
  const deleteAssignment = useDeleteBillingAccountTariff(accountId);

  const tenantDatasets = datasets.filter((d) => d.scope === 'tenant');

  const [datasetId, setDatasetId] = useState('');
  const [filterText, setFilterText] = useState('{}');
  const [version, setVersion] = useState('');
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [error, setError] = useState('');

  const handleAdd = async () => {
    setError('');
    if (!datasetId) {
      setError('Select a tariff dataset.');
      return;
    }
    if (!effectiveFrom) {
      setError('Set an effective from date.');
      return;
    }
    let filter = {};
    if (filterText.trim()) {
      try {
        filter = JSON.parse(filterText);
        if (typeof filter !== 'object' || Array.isArray(filter)) {
          throw new Error('not an object');
        }
      } catch {
        setError('dimension_filter must be a JSON object.');
        return;
      }
    }
    try {
      await createAssignment.mutateAsync({
        dataset: Number(datasetId),
        dimension_filter: filter,
        version: version || null,
        effective_from: effectiveFrom,
      });
      setDatasetId('');
      setFilterText('{}');
      setVersion('');
      setEffectiveFrom('');
    } catch (err) {
      const details = err.response?.data?.error?.details;
      if (details) {
        const first = Object.entries(details)[0];
        setError(`${first[0]}: ${Array.isArray(first[1]) ? first[1].join(' ') : first[1]}`);
      } else {
        setError(err.response?.data?.error?.message || 'Failed to add tariff.');
      }
    }
  };

  const handleDelete = async (assignmentId) => {
    if (!window.confirm('Remove this tariff assignment?')) return;
    try {
      await deleteAssignment.mutateAsync(assignmentId);
    } catch (err) {
      window.alert(err.response?.data?.error?.message || 'Failed to remove.');
    }
  };

  return (
    <div>
      {canEdit && (
        <section className={styles.section} style={{ marginTop: 0 }}>
          <h3 style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem' }}>Assign a tariff</h3>
          <p style={{ fontSize: '0.8125rem', color: '#6B7280', margin: '0 0 0.75rem' }}>
            Only scope=tenant Reference Datasets (PPA / retail tariff templates) can be
            assigned to a billing account.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 1fr 1fr', gap: '0.5rem', alignItems: 'flex-end' }}>
            <div className={styles.field} style={{ marginBottom: 0 }}>
              <label className={styles.label}>Tariff dataset *</label>
              <select
                value={datasetId}
                onChange={(e) => setDatasetId(e.target.value)}
                className={styles.input}
              >
                <option value="">— Select dataset —</option>
                {tenantDatasets.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div className={styles.field} style={{ marginBottom: 0 }}>
              <label className={styles.label}>dimension_filter (JSON)</label>
              <input
                type="text"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                className={styles.input}
                placeholder='{"plan_code": "stage1-2026"}'
              />
            </div>
            <div className={styles.field} style={{ marginBottom: 0 }}>
              <label className={styles.label}>Version</label>
              <input
                type="text"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                className={styles.input}
                placeholder="latest"
              />
            </div>
            <div className={styles.field} style={{ marginBottom: 0 }}>
              <label className={styles.label}>Effective from *</label>
              <input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
                className={styles.input}
              />
            </div>
          </div>
          <button
            className={styles.primaryButton}
            onClick={handleAdd}
            disabled={createAssignment.isPending}
            style={{ marginTop: '0.5rem' }}
          >
            {createAssignment.isPending ? 'Adding…' : 'Add tariff assignment'}
          </button>
          {error && <p className={styles.error}>{error}</p>}
        </section>
      )}

      {isLoading ? (
        <p className={styles.loading}>Loading…</p>
      ) : assignments.length === 0 ? (
        <p className={styles.empty}>No tariffs assigned yet.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Tariff</th>
              <th>Dimension filter</th>
              <th>Version</th>
              <th>Stream scope</th>
              <th>Effective from</th>
              <th>Effective to</th>
              {canEdit && <th></th>}
            </tr>
          </thead>
          <tbody>
            {assignments.map((a) => (
              <tr key={a.id}>
                <td>{a.dataset_name}</td>
                <td className={styles.mono} style={{ fontSize: '0.8125rem' }}>
                  {JSON.stringify(a.dimension_filter || {})}
                </td>
                <td>{a.version || <em style={{ color: '#9CA3AF' }}>latest</em>}</td>
                <td>{a.stream_label || <em style={{ color: '#9CA3AF' }}>all</em>}</td>
                <td>{formatDate(a.effective_from)}</td>
                <td>{formatDate(a.effective_to)}</td>
                {canEdit && (
                  <td>
                    <button
                      className={styles.dangerButton}
                      onClick={() => handleDelete(a.id)}
                      disabled={deleteAssignment.isPending}
                    >
                      Remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

TariffsTab.propTypes = {
  accountId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  canEdit: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Audit log tab
// ---------------------------------------------------------------------------

function AuditLogTab({ accountId }) {
  const { data: entries = [], isLoading, isError } = useBillingAccountAuditLog(accountId);

  if (isLoading) return <p className={styles.loading}>Loading…</p>;
  if (isError) return <p className={styles.error}>Failed to load audit log.</p>;
  if (entries.length === 0) return <p className={styles.empty}>No audit entries yet.</p>;

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>When</th>
          <th>Action</th>
          <th>Actor</th>
          <th>Changes</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.id}>
            <td>{formatDateTime(entry.occurred_at)}</td>
            <td>
              <span style={{
                color: entry.action === 'deactivated' ? '#EF4444' : '#1A6B4A',
                fontWeight: 600,
              }}>
                {AUDIT_ACTION_LABELS[entry.action] || entry.action}
              </span>
            </td>
            <td>{entry.actor_email || <em>system</em>}</td>
            <td className={styles.mono} style={{ fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(entry.changed_fields, null, 2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

AuditLogTab.propTypes = {
  accountId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function BillingAccountDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  const { data: account, isLoading, isError } = useBillingAccount(id);
  const [activeTab, setActiveTab] = useState('Info');

  return (
    <div>
      <div className={styles.pageHeader}>
        <Link to="/app/billing-accounts" className={styles.link}>← Billing Accounts</Link>
        <h1 style={{ margin: '0 0 0 1rem', fontSize: '1.5rem', fontWeight: 700 }}>
          {isLoading ? 'Loading…' : (account?.name || `Account #${id}`)}
        </h1>
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} />

      <section className={styles.section}>
        {isError && <p className={styles.error}>Failed to load billing account.</p>}
        {!isLoading && !account && !isError && (
          <p className={styles.empty}>Billing account not found.</p>
        )}
        {account && activeTab === 'Info' && <InfoTab account={account} canEdit={isAdmin} />}
        {account && activeTab === 'Meters' && <MetersTab accountId={account.id} canEdit={isAdmin} />}
        {account && activeTab === 'Tariffs' && <TariffsTab accountId={account.id} canEdit={isAdmin} />}
        {account && activeTab === 'Audit log' && <AuditLogTab accountId={account.id} />}
      </section>
    </div>
  );
}

export default BillingAccountDetail;
