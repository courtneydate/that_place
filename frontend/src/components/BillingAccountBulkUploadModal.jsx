/**
 * BillingAccountBulkUploadModal — Sprint 30.
 *
 * CSV upsert UI for billing accounts. Match key is `customer_reference`;
 * rows without one create new accounts every upload. Mirrors the
 * MeterBulkUploadModal pattern from Sprint 29.
 */
import { useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useBulkUploadBillingAccounts } from '../hooks/useBillingAccounts';
import styles from '../pages/admin/AdminPage.module.css';

const CSV_TEMPLATE = (
  'name,customer_reference,account_type,contact_email,contact_phone,abn,'
  + 'address_street,address_suburb,address_state,address_postcode,address_country,'
  + 'invoice_email_recipients,floor_area_sqm,activated_at,deactivated_at,'
  + 'parent_customer_reference\n'
  + 'Apt 12 BC,BC-012,en_tenant,bc12@example.test,0400000000,11122233344,'
  + '12 Smith St,Newtown,NSW,2042,AU,'
  + '"billing@example.test,owner@example.test",78.50,2026-05-01,,SITE-WC\n'
);

function BillingAccountBulkUploadModal({ onClose }) {
  const upload = useBulkUploadBillingAccounts();
  const fileInput = useRef(null);
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    if (!dragOver) setDragOver(true);
  };

  const handleSelectFile = (e) => {
    const selected = e.target.files?.[0];
    if (selected) setFile(selected);
  };

  const handleUpload = async () => {
    setError('');
    setResult(null);
    if (!file) {
      setError('Choose a CSV file first.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Only .csv files are accepted.');
      return;
    }
    try {
      const summary = await upload.mutateAsync(file);
      setResult(summary);
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Upload failed.');
    }
  };

  const handleTemplateDownload = () => {
    const blob = new Blob([CSV_TEMPLATE], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'billing-accounts-template.csv';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(15, 23, 42, 0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#fff', borderRadius: 8, padding: '1.5rem',
          width: 'min(640px, 92vw)', maxHeight: '90vh', overflowY: 'auto',
          boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '0.75rem' }}>
          <h2 style={{ margin: 0 }}>Bulk import billing accounts</h2>
          <button
            className={styles.secondaryButton}
            onClick={onClose}
            type="button"
            style={{ padding: '0.25rem 0.5rem' }}
          >
            Close
          </button>
        </div>

        <p style={{ fontSize: '0.875rem', color: '#374151', marginBottom: '0.75rem' }}>
          Upload a CSV to create or update billing accounts. The match key is
          <code style={{ background: '#F3F4F6', padding: '0 0.25rem' }}>customer_reference</code> —
          rows without one always create a new account.
        </p>

        <details style={{ marginBottom: '1rem' }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.875rem' }}>
            CSV column reference
          </summary>
          <ul style={{ marginTop: '0.5rem', fontSize: '0.8125rem', color: '#374151' }}>
            <li><code>name</code> — required</li>
            <li><code>customer_reference</code> — upsert key; unique per tenant when set</li>
            <li><code>account_type</code> — required (ppa_host / en_tenant / internal)</li>
            <li><code>contact_email</code>, <code>contact_phone</code>, <code>abn</code> — optional</li>
            <li><code>address_street</code>, <code>address_suburb</code>, <code>address_state</code>, <code>address_postcode</code>, <code>address_country</code> — flattened into billing_address</li>
            <li><code>invoice_email_recipients</code> — comma-separated emails</li>
            <li><code>floor_area_sqm</code>, <code>activated_at</code>, <code>deactivated_at</code> — optional</li>
            <li><code>parent_customer_reference</code> — references another account in this CSV / tenant</li>
          </ul>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={handleTemplateDownload}
            style={{ marginTop: '0.5rem', fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
          >
            Download template
          </button>
        </details>

        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInput.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? '#1A6B4A' : '#D1D5DB'}`,
            background: dragOver ? '#F0FDF4' : '#FAFAFA',
            borderRadius: 8,
            padding: '2rem 1rem',
            textAlign: 'center',
            cursor: 'pointer',
            marginBottom: '1rem',
          }}
        >
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            onChange={handleSelectFile}
            style={{ display: 'none' }}
          />
          {file ? (
            <>
              <p style={{ margin: 0, fontWeight: 600 }}>{file.name}</p>
              <small style={{ color: '#6B7280' }}>
                {(file.size / 1024).toFixed(1)} KB · click to choose another
              </small>
            </>
          ) : (
            <>
              <p style={{ margin: 0, fontWeight: 600, color: '#374151' }}>
                Drop your CSV here, or click to choose
              </p>
              <small style={{ color: '#6B7280' }}>Max 10 MB · 50,000 rows</small>
            </>
          )}
        </div>

        <div className={styles.actions} style={{ marginBottom: '1rem' }}>
          <button
            className={styles.primaryButton}
            onClick={handleUpload}
            disabled={!file || upload.isPending}
            type="button"
          >
            {upload.isPending ? 'Uploading…' : 'Upload CSV'}
          </button>
          {file && (
            <button
              className={styles.secondaryButton}
              onClick={() => { setFile(null); setResult(null); setError(''); }}
              disabled={upload.isPending}
              type="button"
            >
              Clear
            </button>
          )}
        </div>

        {error && <p className={styles.error}>{error}</p>}

        {result && (
          <div style={{ marginTop: '1rem' }}>
            <p style={{ fontWeight: 600, margin: '0 0 0.5rem' }}>
              Imported {result.imported} row{result.imported === 1 ? '' : 's'}
              {result.errors.length > 0 && (
                <>, {result.errors.length} error{result.errors.length === 1 ? '' : 's'}</>
              )}.
            </p>
            {result.errors.length > 0 && (
              <div style={{
                maxHeight: '14rem', overflowY: 'auto',
                background: '#FEF2F2', border: '1px solid #FCA5A5',
                borderRadius: 6, padding: '0.5rem 0.75rem',
              }}>
                {result.errors.map((e, idx) => (
                  <div
                    key={`${e.row}-${idx}`}
                    style={{
                      padding: '0.25rem 0', fontSize: '0.8125rem',
                      borderBottom: idx === result.errors.length - 1 ? 'none' : '1px solid #FECACA',
                    }}
                  >
                    <strong>Row {e.row}:</strong> {e.error}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

BillingAccountBulkUploadModal.propTypes = {
  onClose: PropTypes.func.isRequired,
};

export default BillingAccountBulkUploadModal;
