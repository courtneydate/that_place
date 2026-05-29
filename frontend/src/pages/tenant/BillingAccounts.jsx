/**
 * Billing Accounts — Tenant Admin / Operator page (Sprint 30).
 *
 * Lists the customer accounts the operator-tenant invoices. Tenant Admin
 * can create, deactivate, and bulk-import; Operators read-only.
 *
 * Ref: SPEC.md § Feature: Billing Accounts & Tariffs
 *      ROADMAP.md § Sprint 30
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  useBillingAccounts,
  useCreateBillingAccount,
  useDeleteBillingAccount,
} from '../../hooks/useBillingAccounts';
import BillingAccountBulkUploadModal from '../../components/BillingAccountBulkUploadModal';
import styles from '../admin/AdminPage.module.css';

const ACCOUNT_TYPE_LABELS = {
  ppa_host: 'PPA host',
  en_tenant: 'EN tenant',
  internal: 'Internal',
};

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function CreateAccountForm({ onDone }) {
  const createAccount = useCreateBillingAccount();
  const [name, setName] = useState('');
  const [customerReference, setCustomerReference] = useState('');
  const [accountType, setAccountType] = useState('ppa_host');
  const [contactEmail, setContactEmail] = useState('');
  const [abn, setAbn] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) {
      setError('Account name is required.');
      return;
    }
    try {
      await createAccount.mutateAsync({
        name: name.trim(),
        customer_reference: customerReference.trim(),
        account_type: accountType,
        contact_email: contactEmail.trim(),
        abn: abn.trim(),
      });
      onDone();
    } catch (err) {
      const details = err.response?.data?.error?.details;
      if (details) {
        const first = Object.entries(details)[0];
        setError(`${first[0]}: ${Array.isArray(first[1]) ? first[1].join(' ') : first[1]}`);
      } else {
        setError(err.response?.data?.error?.message || 'Failed to create billing account.');
      }
    }
  };

  return (
    <section className={styles.section}>
      <h2>New billing account</h2>
      <form onSubmit={handleSubmit} className={styles.form} noValidate>
        <div className={styles.inlineFields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ba-name">Name *</label>
            <input
              id="ba-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={styles.input}
              placeholder="e.g. Apt 12 Body Corporate"
              disabled={createAccount.isPending}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ba-ref">Customer reference</label>
            <input
              id="ba-ref"
              type="text"
              value={customerReference}
              onChange={(e) => setCustomerReference(e.target.value)}
              className={styles.input}
              placeholder="e.g. BC-001"
              disabled={createAccount.isPending}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ba-type">Account type *</label>
            <select
              id="ba-type"
              value={accountType}
              onChange={(e) => setAccountType(e.target.value)}
              className={styles.input}
              disabled={createAccount.isPending}
            >
              <option value="ppa_host">PPA host</option>
              <option value="en_tenant">Embedded-network tenant</option>
              <option value="internal">Internal</option>
            </select>
          </div>
        </div>
        <div className={styles.inlineFields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ba-email">Contact email</label>
            <input
              id="ba-email"
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              className={styles.input}
              disabled={createAccount.isPending}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="ba-abn">ABN</label>
            <input
              id="ba-abn"
              type="text"
              value={abn}
              onChange={(e) => setAbn(e.target.value)}
              className={styles.input}
              placeholder="11 digits"
              disabled={createAccount.isPending}
            />
          </div>
        </div>
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={createAccount.isPending}
          >
            {createAccount.isPending ? 'Creating…' : 'Create account'}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onDone}
            disabled={createAccount.isPending}
          >
            Cancel
          </button>
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </section>
  );
}

function BillingAccounts() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  const [filter, setFilter] = useState({});
  const [showCreate, setShowCreate] = useState(false);
  const [showBulk, setShowBulk] = useState(false);

  const { data: accounts = [], isLoading, isError } = useBillingAccounts(filter);
  const deleteAccount = useDeleteBillingAccount();

  const handleDeactivate = async (accountId, name) => {
    if (!window.confirm(`Deactivate billing account "${name}"? It can be reactivated later.`)) {
      return;
    }
    try {
      await deleteAccount.mutateAsync(accountId);
    } catch (err) {
      window.alert(err.response?.data?.error?.message || 'Failed to deactivate account.');
    }
  };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1>Billing Accounts</h1>
        {isAdmin && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className={styles.secondaryButton}
              onClick={() => setShowBulk(true)}
            >
              Bulk import
            </button>
            <button
              className={styles.primaryButton}
              onClick={() => setShowCreate((v) => !v)}
            >
              {showCreate ? 'Cancel' : '+ New billing account'}
            </button>
          </div>
        )}
      </div>

      {isAdmin && showBulk && (
        <BillingAccountBulkUploadModal onClose={() => setShowBulk(false)} />
      )}
      {isAdmin && showCreate && (
        <CreateAccountForm onDone={() => setShowCreate(false)} />
      )}

      <section className={styles.section}>
        <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem' }}>
          <select
            value={filter.account_type || ''}
            onChange={(e) => setFilter((f) => ({ ...f, account_type: e.target.value || undefined }))}
            className={styles.input}
            style={{ width: 'auto' }}
          >
            <option value="">All types</option>
            <option value="ppa_host">PPA host</option>
            <option value="en_tenant">EN tenant</option>
            <option value="internal">Internal</option>
          </select>
          <select
            value={filter.is_active === undefined ? '' : String(filter.is_active)}
            onChange={(e) => {
              const v = e.target.value;
              setFilter((f) => ({
                ...f,
                is_active: v === '' ? undefined : v === 'true',
              }));
            }}
            className={styles.input}
            style={{ width: 'auto' }}
          >
            <option value="">All states</option>
            <option value="true">Active</option>
            <option value="false">Deactivated</option>
          </select>
        </div>

        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load billing accounts.</p>}
        {!isLoading && !isError && accounts.length === 0 && (
          <p className={styles.empty}>
            No billing accounts yet.{isAdmin ? ' Create one to start invoicing customers.' : ''}
          </p>
        )}
        {!isLoading && !isError && accounts.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Customer ref</th>
                <th>Type</th>
                <th>Contact</th>
                <th>Status</th>
                <th>Created</th>
                {isAdmin && <th></th>}
              </tr>
            </thead>
            <tbody>
              {accounts.map((acct) => (
                <tr
                  key={acct.id}
                  style={{ opacity: acct.is_active ? 1 : 0.6 }}
                >
                  <td>
                    <Link to={`/app/billing-accounts/${acct.id}`} className={styles.link}>
                      {acct.name}
                    </Link>
                  </td>
                  <td className={styles.mono}>{acct.customer_reference || '—'}</td>
                  <td>{ACCOUNT_TYPE_LABELS[acct.account_type] || acct.account_type}</td>
                  <td>{acct.contact_email || '—'}</td>
                  <td>
                    {acct.is_active
                      ? <span style={{ color: '#22C55E', fontWeight: 600 }}>Active</span>
                      : <span style={{ color: '#9CA3AF' }}>Deactivated</span>}
                  </td>
                  <td>{formatDate(acct.created_at)}</td>
                  {isAdmin && (
                    <td>
                      {acct.is_active && (
                        <button
                          className={styles.dangerButton}
                          onClick={() => handleDeactivate(acct.id, acct.name)}
                          disabled={deleteAccount.isPending}
                        >
                          Deactivate
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default BillingAccounts;
