"""Invoice rendering pipeline — Sprint 32.

Responsible for:
  - Atomic per-tenant invoice-number allocation (SELECT FOR UPDATE).
  - Building the template context dict from a BillingRun + BillingAccount.
  - Rendering HTML via Django's template engine (supports Django template tags
    in the stored HTML content).
  - Converting HTML to PDF bytes via WeasyPrint.
  - Uploading the PDF to object storage.
  - Generating short-lived signed download URLs.

The finalize pathway (apps.billing.tasks.finalize_billing_run) calls the
three public helpers:
    allocate_invoice_number(tenant)
    render_and_upload_pdf(invoice, run, account, line_items, tenant)
    generate_pdf_signed_url(object_key, expiry_seconds)

Ref: SPEC.md § Feature: Billing Runs & Invoicing
     ROADMAP Sprint 32
"""
from __future__ import annotations

import logging
import os

import boto3
from django.conf import settings
from django.template import Context, Template
from django.utils import timezone

try:
    from weasyprint import HTML
except ImportError:  # WeasyPrint not installed (e.g. test runner without OS deps)
    HTML = None

logger = logging.getLogger(__name__)

DEFAULT_DISCLAIMER = (
    "This invoice is produced from interval meter data processed by the That Place "
    "metering platform. It is invoice-grade billing output only and is not "
    "AEMO-MDP-accredited settlement data. Readings are subject to revision if a "
    "meter exchange, data recovery, or comms-loss substitution is applied in a "
    "subsequent billing period."
)


# ---------------------------------------------------------------------------
# Invoice number allocation
# ---------------------------------------------------------------------------


def allocate_invoice_number(tenant) -> str:
    """Atomically increment Tenant.invoice_number_sequence and return the
    formatted invoice number.

    Must be called inside an open DB transaction (the finalize step already
    wraps the whole finalize operation in one).
    """
    from apps.accounts.models import Tenant

    # SELECT FOR UPDATE locks the tenant row so concurrent finalizes for the
    # same tenant cannot produce duplicate sequence numbers.
    locked = Tenant.objects.select_for_update().get(pk=tenant.pk)
    locked.invoice_number_sequence += 1
    locked.save(update_fields=['invoice_number_sequence'])

    fmt = locked.invoice_number_format or 'INV-{YYYY}-{seq:06d}'
    year = timezone.now().year
    try:
        number = fmt.format(YYYY=year, seq=locked.invoice_number_sequence)
    except (KeyError, ValueError):
        # Malformed format string — fall back to a safe default so finalize
        # doesn't blow up entirely; admin can correct the format later.
        number = f'INV-{year}-{locked.invoice_number_sequence:06d}'
        logger.warning(
            'Tenant %s has an invalid invoice_number_format %r; '
            'used fallback %s',
            tenant.slug,
            fmt,
            number,
        )
    return number


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------


def _load_template_html(tenant) -> str:
    """Return the HTML template string for this tenant.

    If tenant.invoice_pdf_template_id is set and the record exists, use its
    html_content. Otherwise fall back to the bundled default.html.
    """
    if tenant.invoice_pdf_template_id:
        from apps.billing.models import InvoicePDFTemplate
        try:
            tmpl = InvoicePDFTemplate.objects.get(
                pk=tenant.invoice_pdf_template_id,
                is_active=True,
            )
            return tmpl.html_content
        except InvoicePDFTemplate.DoesNotExist:
            logger.warning(
                'Tenant %s references missing InvoicePDFTemplate id=%s; '
                'falling back to default',
                tenant.slug,
                tenant.invoice_pdf_template_id,
            )

    default_path = os.path.join(
        os.path.dirname(__file__),
        'templates', 'invoices', 'default.html',
    )
    with open(default_path, 'r', encoding='utf-8') as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------


class _LineItemProxy:
    """Thin wrapper over BillingLineItem adding display helpers."""

    def __init__(self, item):
        self._item = item

    def __getattr__(self, name):
        return getattr(self._item, name)

    @property
    def line_kind_display(self):
        return self._item.get_line_kind_display()

    @property
    def amount_dollars(self):
        return f'${self._item.amount_cents / 100:,.2f}'

    @property
    def gst_dollars(self):
        return f'${self._item.gst_cents / 100:,.2f}'

    @property
    def total_dollars(self):
        total = self._item.amount_cents + self._item.gst_cents
        return f'${total / 100:,.2f}'


def build_invoice_context(invoice, run, account, line_items, tenant) -> dict:
    """Build the template rendering context dict."""
    subtotal = invoice.subtotal_cents / 100
    gst = invoice.gst_cents / 100
    total = invoice.total_cents / 100
    gst_rate_pct = float(tenant.gst_rate * 100)

    has_quality_issues = any(
        item.quality_summary.get('gap') or item.quality_summary.get('estimated')
        for item in line_items
        if item.quality_summary
    )

    show_disclaimer = account.account_type == 'en_tenant'
    disclaimer_text = tenant.invoice_settlement_disclaimer or DEFAULT_DISCLAIMER

    return {
        'tenant': tenant,
        'invoice': invoice,
        'run': run,
        'account': account,
        'line_items': [_LineItemProxy(item) for item in line_items],
        'subtotal_display': f'${subtotal:,.2f}',
        'gst_display': f'${gst:,.2f}',
        'total_display': f'${total:,.2f}',
        'gst_rate_pct': f'{gst_rate_pct:.0f}',
        'has_quality_issues': has_quality_issues,
        'show_disclaimer': show_disclaimer,
        'disclaimer_text': disclaimer_text,
    }


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------


def render_pdf_bytes(invoice, run, account, line_items, tenant) -> bytes:
    """Render the invoice as a PDF and return raw bytes.

    Uses Django's template engine to process the HTML (so Django template tags
    work in stored templates), then passes the rendered HTML to WeasyPrint.
    """
    html_source = _load_template_html(tenant)
    context = build_invoice_context(invoice, run, account, line_items, tenant)

    # Django Template renders the HTML string with context.
    template = Template(html_source)
    rendered_html = template.render(Context(context))

    if HTML is None:
        raise RuntimeError(
            'WeasyPrint is not installed. Install it with the required OS '
            'dependencies (libpango, libgdk-pixbuf2.0) to render PDFs.'
        )
    pdf_bytes = HTML(string=rendered_html).write_pdf()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Object storage upload
# ---------------------------------------------------------------------------


def _get_s3_client():
    """Return a boto3 S3 client configured for the active storage backend."""
    kwargs = {
        'aws_access_key_id': getattr(settings, 'AWS_ACCESS_KEY_ID', None),
        'aws_secret_access_key': getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
        'region_name': getattr(settings, 'AWS_S3_REGION_NAME', 'ap-southeast-2'),
    }
    endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
    if endpoint:
        kwargs['endpoint_url'] = endpoint
    return boto3.client('s3', **kwargs)


def upload_pdf(pdf_bytes: bytes, tenant_slug: str, year: int, invoice_number: str) -> str:
    """Upload PDF bytes to object storage and return the object key.

    Key format: invoices/{tenant_slug}/{YYYY}/{invoice_number}.pdf
    """
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    object_key = f'invoices/{tenant_slug}/{year}/{invoice_number}.pdf'

    client = _get_s3_client()
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=pdf_bytes,
        ContentType='application/pdf',
        ContentDisposition=f'attachment; filename="{invoice_number}.pdf"',
    )
    return object_key


def render_and_upload_pdf(invoice, run, account, line_items, tenant) -> str:
    """Render the invoice PDF and upload it; return the object key.

    Sets invoice.pdf_object_key but does NOT save — caller is responsible
    for saving within the surrounding transaction.
    """
    pdf_bytes = render_pdf_bytes(invoice, run, account, line_items, tenant)
    year = invoice.issued_at.year if invoice.issued_at else timezone.now().year
    object_key = upload_pdf(pdf_bytes, tenant.slug, year, invoice.invoice_number)
    invoice.pdf_object_key = object_key
    return object_key


# ---------------------------------------------------------------------------
# Signed URL generation
# ---------------------------------------------------------------------------


def generate_pdf_signed_url(object_key: str, expiry_seconds: int = 900) -> str:
    """Generate a short-lived pre-signed GET URL for the invoice PDF.

    Default expiry is 15 minutes (900 s) for in-app preview.
    Email delivery uses 14 days (1_209_600 s).
    """
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    client = _get_s3_client()
    url = client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': object_key},
        ExpiresIn=expiry_seconds,
    )
    return url
