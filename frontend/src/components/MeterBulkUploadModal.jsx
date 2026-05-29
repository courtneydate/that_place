/**
 * MeterBulkUploadModal — Sprint 29.
 *
 * Drag-and-drop CSV upload for MeterProfile bulk upsert. Mirrors the
 * reference-dataset bulk-import UX: drop a CSV, see import summary, see
 * per-row errors in a scrollable list. Tenant Admin only.
 *
 * Backend endpoint: POST /api/v1/meter-profiles/bulk/
 *
 * Ref: ROADMAP.md § Sprint 29 — Bulk MeterProfile CSV upload UI
 */
import { useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useBulkUploadMeterProfiles } from '../hooks/useMeterProfiles';
import styles from '../pages/admin/AdminPage.module.css';

const CSV_TEMPLATE = (
  'device_serial,meter_role,nmi,parent_meter_serial,phases,pattern_approval,install_date,serial_number_secondary\n'
  + 'GATE-001,gate,,,3,NMI-M6,2026-01-15,\n'
  + 'CHILD-001,child,6203456789,GATE-001,1,NMI-M6,2026-01-15,\n'
);

function MeterBulkUploadModal({ onClose }) {
  const upload = useBulkUploadMeterProfiles();
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

  const handleDragLeave = () => setDragOver(false);

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
    link.download = 'meter-profiles-template.csv';
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
          <h2 style={{ margin: 0 }}>Bulk import meter profiles</h2>
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
          Upload a CSV to create or update meter profiles. The match key is
          <code style={{ background: '#F3F4F6', padding: '0 0.25rem' }}>device_serial</code>;
          rows for unknown serials are reported as errors.
        </p>

        <details style={{ marginBottom: '1rem' }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.875rem' }}>
            CSV column reference
          </summary>
          <ul style={{ marginTop: '0.5rem', fontSize: '0.8125rem', color: '#374151' }}>
            <li><code>device_serial</code> — required, must already exist in this tenant</li>
            <li><code>meter_role</code> — required (gate / child / generation / storage / consumption / common_area / sub_check)</li>
            <li><code>nmi</code> — optional, unique per tenant when set</li>
            <li><code>parent_meter_serial</code> — required for child/common_area on a hierarchical site</li>
            <li><code>phases</code> — 1 or 3, defaults to 1</li>
            <li><code>pattern_approval</code>, <code>install_date</code>, <code>serial_number_secondary</code> — optional</li>
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
          onDragLeave={handleDragLeave}
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

MeterBulkUploadModal.propTypes = {
  onClose: PropTypes.func.isRequired,
};

export default MeterBulkUploadModal;
