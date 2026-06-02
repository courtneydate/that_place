/**
 * Invoice detail page (Sprint 32).
 *
 * Route: /app/invoices/:id
 * Shows PDF preview (via 15-min signed URL in an iframe), status badges,
 * resend button (Admin only), void indicator.
 *
 * Ref: SPEC.md § Feature: Billing Runs & Invoicing
 *      ROADMAP.md § Sprint 32
 */
import PropTypes from 'prop-types';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  useBillingInvoice,
  useInvoicePdfUrl,
  useResendInvoice,
} from '../../hooks/useBillingRuns';
import styles from '../admin/AdminPage.module.css';

function fmt(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function fmtCents(cents) {
  if (cents == null) return '—';
  return `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

const STATUS_BADGE = {
  draft:     styles.badgeWarning,
  delivered: styles.badgeActive,
  void:      styles.badgeInactive,
};

const DELIVERY_BADGE = {
  pending:   styles.badgeWarning,
  sent:      styles.badgeActive,
  delivered: styles.badgeActive,
  failed:    styles.badgeDanger,
};

function StatusBadge({ value, map }) {
  return <span className={map[value] || styles.badgeInactive}>{value}</span>;
}
StatusBadge.propTypes = { value: PropTypes.string, map: PropTypes.object };

// ---------------------------------------------------------------------------
// PDF preview frame
// ---------------------------------------------------------------------------

function PdfPreview({ invoiceId }) {
  const { data, isLoading, isError } = useInvoicePdfUrl(invoiceId);

  if (isLoading) {
    return (
      <div style={{
        height: 480, background: '#F9FAFB', borderRadius: 6,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#6B7280', fontSize: '0.875rem',
      }}>
        Loading PDF preview…
      </div>
    );
  }

  if (isError || !data?.url) {
    return (
      <div style={{
        height: 200, background: '#F9FAFB', borderRadius: 6,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#6B7280', fontSize: '0.875rem',
      }}>
        PDF not yet available.
      </div>
    );
  }

  return (
    <iframe
      src={data.url}
      title="Invoice PDF preview"
      style={{
        width: '100%', height: 640, border: '1px solid #E5E7EB',
        borderRadius: 6, display: 'block',
      }}
    />
  );
}
PdfPreview.propTypes = { invoiceId: PropTypes.string.isRequired };

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function InvoiceDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const { data: invoice, isLoading, isError } = useBillingInvoice(id);
  const resend = useResendInvoice(id);

  if (isLoading) return <p className={styles.loading}>Loading…</p>;
  if (isError || !invoice) return <p className={styles.error}>Invoice not found.</p>;

  const isVoid = invoice.status === 'void';
  const canResend = isAdmin && !isVoid;

  return (
    <div>
      <div className={styles.pageHeader}>
        <div>
          <Link
            to={`/app/billing-runs/${invoice.billing_run}`}
            className={styles.link}
            style={{ fontSize: '0.875rem' }}
          >
            ← Billing Run
          </Link>
          <h1 className={styles.pageTitle} style={{ marginTop: '0.25rem' }}>
            Invoice {invoice.invoice_number}
          </h1>
        </div>

        {canResend && (
          <button
            className={styles.secondaryButton}
            disabled={resend.isPending}
            onClick={() => resend.mutate()}
          >
            {resend.isPending ? 'Sending…' : 'Resend'}
          </button>
        )}
      </div>

      {isVoid && (
        <div style={{
          marginBottom: '1.25rem', padding: '0.875rem 1rem',
          background: '#F3F4F6', borderRadius: 6,
          fontSize: '0.875rem', color: '#6B7280',
        }}>
          This invoice has been voided and is no longer payable.
        </div>
      )}

      {resend.isSuccess && (
        <p className={styles.success} style={{ marginBottom: '1rem' }}>
          Resend queued — email will be delivered shortly.
        </p>
      )}
      {resend.isError && (
        <p className={styles.error} style={{ marginBottom: '1rem' }}>
          {resend.error?.response?.data?.error?.message || 'Resend failed.'}
        </p>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: '1.5rem' }}>
        {/* Left — PDF preview */}
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Invoice PDF</h2>
          <PdfPreview invoiceId={id} />
        </div>

        {/* Right — metadata */}
        <div className={styles.section} style={{ height: 'fit-content' }}>
          <h2 className={styles.sectionTitle}>Details</h2>
          <dl style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            {[
              ['Account', invoice.billing_account_name || invoice.billing_account],
              ['Period', `${fmtDate(invoice.billing_run_period_start)} – ${fmtDate(invoice.billing_run_period_end)}`],
              ['Subtotal', fmtCents(invoice.subtotal_cents)],
              ['GST', fmtCents(invoice.gst_cents)],
              ['Total', fmtCents(invoice.total_cents)],
              ['Status', <StatusBadge key="s" value={invoice.status} map={STATUS_BADGE} />],
              ['Delivery', <StatusBadge key="d" value={invoice.delivery_status} map={DELIVERY_BADGE} />],
              ['Issued', fmt(invoice.issued_at)],
              ['Delivered', fmt(invoice.delivered_at)],
              ['Voided', fmt(invoice.voided_at)],
            ].map(([label, val]) => (
              <div key={label}>
                <dt style={{
                  fontSize: '0.75rem', fontWeight: 600,
                  textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280',
                  marginBottom: '0.25rem',
                }}>{label}</dt>
                <dd style={{ fontSize: '0.875rem', color: '#111827', margin: 0 }}>{val}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
