"""Sprint 32 — Invoice Rendering, Delivery & Audit tests.

Covers:
  * allocate_invoice_number — atomic, concurrent, format fallback.
  * render_pdf_bytes / render_and_upload_pdf — context built correctly,
    WeasyPrint called, PDF uploaded to correct object key.
  * generate_pdf_signed_url — boto3 called with correct params + expiry.
  * finalize_billing_run task — creates invoices, dispatches email tasks,
    marks run finalized; no-ops on wrong status.
  * send_invoice_email task — attaches PDF, updates delivery_status on
    success and failure; single retry.
  * send_void_notification_email task — sends void notice.
  * Finalize API endpoint — 202 accepted; 400 on wrong status;
    Tenant Admin only; cross-tenant 404.
  * Void API endpoint — 200 with run+invoices voided; silent_void
    suppresses notification emails; 400 on wrong status.
  * Invoice list / detail / pdf / resend endpoints — permissions +
    cross-tenant isolation.
  * Line-items CSV export — correct columns, streaming, Admin only.
  * Post-finalize immutability — finalized run rejects recompute.

Ref: SPEC.md § Feature: Billing Runs & Invoicing
     ROADMAP Sprint 32
"""
from __future__ import annotations

import threading
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.billing.invoice_renderer import allocate_invoice_number
from apps.billing.models import (
    BillingAccount,
    BillingInvoice,
    BillingLineItem,
    BillingRun,
)
from apps.billing.tasks import (
    finalize_billing_run,
    send_invoice_email,
    send_void_notification_email,
)
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import ReferenceDataset
from apps.readings.models import Stream

# ---------------------------------------------------------------------------
# Fixtures (reuse patterns from test_sprint31_engine)
# ---------------------------------------------------------------------------


def make_tenant(name='Acme', tz='Australia/Sydney'):
    return Tenant.objects.create(
        name=name, slug=slugify(name), timezone=tz,
        gst_rate=Decimal('0.10'),
        invoice_number_format='INV-{YYYY}-{seq:04d}',
    )


def make_user(tenant, role=TenantUser.Role.ADMIN, email=None):
    email = email or f'{role}@{tenant.slug}.test'
    user = User.objects.create_user(email=email, password='pass')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': 'pass'})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_site(tenant, name='Site'):
    return Site.objects.create(tenant=tenant, name=name)


def make_device(tenant, site, serial='D-1'):
    dt, _ = DeviceType.objects.get_or_create(
        slug='s32-meter',
        defaults={
            'name': 'S32Meter', 'connection_type': 'mqtt',
            'is_push': True, 'stream_type_definitions': [], 'commands': [],
        },
    )
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name=f'Dev {serial}', serial_number=serial,
        status=Device.Status.ACTIVE, topic_format='that_place_v1',
    )


def make_stream(device, key='gen_kwh', billing_role=Stream.BillingRole.GENERATION):
    return Stream.objects.create(
        device=device, key=key, label=key, unit='kWh',
        data_type='numeric', billing_role=billing_role,
        aggregation_kind_default=Stream.AggregationKind.SUM,
    )


def make_account(tenant, *, name='Host', account_type=BillingAccount.AccountType.PPA_HOST,
                 recipients=None, activated=None):
    return BillingAccount.objects.create(
        tenant=tenant, name=name, account_type=account_type,
        invoice_email_recipients=recipients if recipients is not None else ['billing@host.example'],
        activated_at=activated or timezone.now(),
    )


def make_ppa_dataset():
    return ReferenceDataset.objects.create(
        slug='ppa-s32', name='PPA S32',
        dimension_schema={'plan_code': {'type': 'string'}, 'period_name': {'type': 'string'}},
        value_schema={
            'rate_cents_per_kwh': {'type': 'numeric', 'unit': 'c/kWh'},
            'supply_charge_cents_per_day': {'type': 'numeric', 'unit': 'c/day'},
        },
        scope=ReferenceDataset.Scope.TENANT,
        has_time_of_use=False,
        has_version=True,
    )


def make_run_at_draft(tenant, site, account, stream, *, n_intervals=2, rate=20.0) -> BillingRun:
    """Create a BillingRun already in draft status with line items."""
    import datetime as _dt
    period_start = _dt.datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    period_end = _dt.datetime(2026, 1, 2, tzinfo=dt_timezone.utc)

    run = BillingRun.objects.create(
        tenant=tenant, site=site,
        period_start=period_start, period_end=period_end,
        timezone_snapshot='Australia/Sydney',
        aggregate_period=BillingRun.AggregatePeriod.THIRTY_MIN,
        status=BillingRun.Status.DRAFT,
    )
    BillingLineItem.objects.create(
        billing_run=run, billing_account=account, stream=stream,
        line_kind=BillingLineItem.LineKind.ENERGY,
        period_name='flat',
        kwh=Decimal('10.0'), rate_cents_per_kwh=Decimal(str(rate)),
        amount_cents=int(10.0 * rate),
        gst_cents=int(10.0 * rate * 0.10),
        quality_summary={'measured': n_intervals},
    )
    BillingLineItem.objects.create(
        billing_run=run, billing_account=account, stream=None,
        line_kind=BillingLineItem.LineKind.SUPPLY,
        period_name='', kwh=None, rate_cents_per_kwh=None,
        amount_cents=100, gst_cents=10,
        quality_summary={},
    )
    return run


# ---------------------------------------------------------------------------
# Invoice number allocation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_allocate_invoice_number_increments():
    tenant = make_tenant(name='NumTenant')
    tenant.invoice_number_format = 'INV-{YYYY}-{seq:04d}'
    tenant.save()

    n1 = allocate_invoice_number(tenant)
    n2 = allocate_invoice_number(tenant)

    year = timezone.now().year
    assert n1 == f'INV-{year}-0001'
    assert n2 == f'INV-{year}-0002'


@pytest.mark.django_db
def test_allocate_invoice_number_bad_format_fallback():
    tenant = make_tenant(name='BadFmtTenant')
    tenant.invoice_number_format = 'BROKEN-{unknown_token}'
    tenant.save()

    number = allocate_invoice_number(tenant)
    year = timezone.now().year
    assert number == f'INV-{year}-000001'


@pytest.mark.django_db(transaction=True)
def test_allocate_invoice_number_concurrent_no_duplicates():
    """Two threads allocating invoice numbers for the same tenant must not
    produce duplicates (SELECT FOR UPDATE serialises them)."""
    tenant = make_tenant(name='ConcTenant')

    results = []
    errors = []

    def _allocate():
        try:
            from django.db import transaction
            with transaction.atomic():
                n = allocate_invoice_number(tenant)
                results.append(n)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=_allocate)
    t2 = threading.Thread(target=_allocate)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f'Unexpected errors: {errors}'
    assert len(results) == 2
    assert results[0] != results[1], 'Duplicate invoice numbers allocated!'


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_render_pdf_bytes_calls_weasyprint():
    tenant = make_tenant(name='PDFTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)

    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-2026-0001',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=300, gst_cents=30, total_cents=330,
    )
    line_items = list(run.line_items.all())

    with patch('apps.billing.invoice_renderer.HTML') as mock_html:
        mock_html.return_value.write_pdf.return_value = b'%PDF-fake'
        from apps.billing.invoice_renderer import render_pdf_bytes
        result = render_pdf_bytes(invoice, run, account, line_items, tenant)

    assert result == b'%PDF-fake'
    mock_html.assert_called_once()


@pytest.mark.django_db
def test_render_and_upload_pdf_sets_object_key():
    tenant = make_tenant(name='UploadTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)

    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-2026-0099',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=200, gst_cents=20, total_cents=220,
    )
    line_items = list(run.line_items.all())

    with (
        patch('apps.billing.invoice_renderer.HTML') as mock_html,
        patch('apps.billing.invoice_renderer._get_s3_client') as mock_s3,
    ):
        mock_html.return_value.write_pdf.return_value = b'%PDF-upload-test'
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        from apps.billing.invoice_renderer import render_and_upload_pdf
        key = render_and_upload_pdf(invoice, run, account, line_items, tenant)

    assert key.startswith('invoices/')
    assert 'INV-2026-0099' in key
    assert key.endswith('.pdf')
    mock_client.put_object.assert_called_once()
    put_kwargs = mock_client.put_object.call_args.kwargs
    assert put_kwargs['ContentType'] == 'application/pdf'


# ---------------------------------------------------------------------------
# Signed URL generation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_generate_pdf_signed_url():
    with patch('apps.billing.invoice_renderer._get_s3_client') as mock_s3:
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = 'https://s3.example/invoices/INV-001.pdf?sig=abc'
        mock_s3.return_value = mock_client

        from apps.billing.invoice_renderer import generate_pdf_signed_url
        url = generate_pdf_signed_url('invoices/acme/2026/INV-001.pdf', expiry_seconds=900)

    assert 's3.example' in url
    call_kwargs = mock_client.generate_presigned_url.call_args
    assert call_kwargs.args[0] == 'get_object'
    assert call_kwargs.kwargs['Params']['Key'] == 'invoices/acme/2026/INV-001.pdf'
    assert call_kwargs.kwargs['ExpiresIn'] == 900


def test_generate_pdf_signed_url_14_day_expiry():
    """Email delivery uses 14-day expiry (1 209 600 s)."""
    from apps.billing.tasks import EMAIL_SIGNED_URL_EXPIRY
    assert EMAIL_SIGNED_URL_EXPIRY == 14 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# finalize_billing_run task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finalize_task_creates_invoices():
    tenant = make_tenant(name='FinalizeTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)

    with (
        patch('apps.billing.tasks.render_and_upload_pdf', return_value='invoices/t/2026/INV.pdf'),
        patch('apps.billing.tasks.send_invoice_email') as mock_email_task,
    ):
        finalize_billing_run(run.id, None)

    run.refresh_from_db()
    assert run.status == BillingRun.Status.FINALIZED
    assert run.finalized_at is not None

    invoices = BillingInvoice.objects.filter(billing_run=run)
    assert invoices.count() == 1
    invoice = invoices.first()
    assert invoice.status == BillingInvoice.Status.DRAFT
    assert invoice.subtotal_cents == 300  # 10 kWh × 20c + 100c supply
    assert invoice.gst_cents == 30
    assert invoice.total_cents == 330

    mock_email_task.delay.assert_called_once_with(invoice.id)


@pytest.mark.django_db
def test_finalize_task_no_op_on_wrong_status():
    tenant = make_tenant(name='FinalizeNoOpTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    run.status = BillingRun.Status.FINALIZED
    run.save()

    finalize_billing_run(run.id, None)

    # Should not create any invoices.
    assert BillingInvoice.objects.filter(billing_run=run).count() == 0


@pytest.mark.django_db
def test_finalize_task_skips_email_when_no_recipients():
    tenant = make_tenant(name='NoRecipTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant, recipients=[])
    run = make_run_at_draft(tenant, site, account, stream)

    with (
        patch('apps.billing.tasks.render_and_upload_pdf', return_value='k'),
        patch('apps.billing.tasks.send_invoice_email') as mock_email_task,
    ):
        finalize_billing_run(run.id, None)

    mock_email_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Finalized run immutability
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finalized_run_rejects_recompute():
    tenant = make_tenant(name='ImmutTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    run.status = BillingRun.Status.FINALIZED
    run.save()

    admin = make_user(tenant)
    client = auth_client(admin)
    resp = client.post(f'/api/v1/billing-runs/{run.id}/recompute/')
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert 'invalid_status' in resp.data['error']['code']


# ---------------------------------------------------------------------------
# send_invoice_email task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_invoice_email_success():
    tenant = make_tenant(name='EmailSuccessTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant, recipients=['cust@example.com'])
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-2026-SEND',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=300, gst_cents=30, total_cents=330,
        pdf_object_key='invoices/acme/2026/INV-2026-SEND.pdf',
    )

    with (
        patch('apps.billing.tasks.generate_pdf_signed_url', return_value='https://s3/presigned'),
        patch('boto3.client') as mock_boto3_client,
        patch('apps.billing.tasks.EmailMessage') as mock_email_class,
    ):
        mock_boto3_client.return_value.get_object.return_value = {
            'Body': BytesIO(b'%PDF-bytes'),
        }
        mock_email_instance = MagicMock()
        mock_email_class.return_value = mock_email_instance

        send_invoice_email(invoice.id)

    invoice.refresh_from_db()
    assert invoice.delivery_status == BillingInvoice.DeliveryStatus.SENT
    assert invoice.status == BillingInvoice.Status.DELIVERED
    assert invoice.delivered_at is not None
    mock_email_instance.send.assert_called_once()


@pytest.mark.django_db
def test_send_invoice_email_smtp_failure_sets_failed():
    tenant = make_tenant(name='EmailFailTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant, recipients=['cust@fail.example'])
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-2026-FAIL',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
    )

    with (
        patch('apps.billing.tasks.generate_pdf_signed_url', return_value=''),
        patch('apps.billing.tasks.EmailMessage') as mock_email_class,
    ):
        mock_email_instance = MagicMock()
        mock_email_instance.send.side_effect = Exception('SMTP down')
        mock_email_class.return_value = mock_email_instance

        # apply() runs synchronously; after max_retries exhausted the final
        # except branch sets FAILED without raising.
        send_invoice_email.apply(args=[invoice.id])

    invoice.refresh_from_db()
    assert invoice.delivery_status == BillingInvoice.DeliveryStatus.FAILED


# ---------------------------------------------------------------------------
# Void notification email task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_void_notification_email():
    tenant = make_tenant(name='VoidNotifTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant, recipients=['cust@void.example'])
    run = make_run_at_draft(tenant, site, account, stream)
    run.void_reason = 'Correcting meter read'
    run.save()
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-2026-VOID',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=200, gst_cents=20, total_cents=220,
        status=BillingInvoice.Status.VOID,
    )

    with patch('apps.billing.tasks.send_mail') as mock_send:
        send_void_notification_email(invoice.id)

    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    subject = kwargs.get('subject', '')
    message = kwargs.get('message', '')
    assert 'VOID' in subject
    assert 'INV-2026-VOID' in subject
    assert 'Correcting meter read' in message


# ---------------------------------------------------------------------------
# Finalize API endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finalize_endpoint_202():
    tenant = make_tenant(name='FinalizeAPI')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    admin = make_user(tenant)
    client = auth_client(admin)

    with patch('apps.billing.views.finalize_billing_run') as mock_task:
        resp = client.post(f'/api/v1/billing-runs/{run.id}/finalize/')

    assert resp.status_code == status.HTTP_202_ACCEPTED
    mock_task.delay.assert_called_once_with(run.id, admin.id)


@pytest.mark.django_db
def test_finalize_endpoint_400_on_wrong_status():
    tenant = make_tenant(name='FinalizeWrong')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    run.status = BillingRun.Status.FAILED
    run.save()
    admin = make_user(tenant)
    client = auth_client(admin)

    resp = client.post(f'/api/v1/billing-runs/{run.id}/finalize/')
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_finalize_endpoint_403_for_operator():
    tenant = make_tenant(name='FinalizeOp')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    operator = make_user(tenant, role=TenantUser.Role.OPERATOR)
    client = auth_client(operator)

    resp = client.post(f'/api/v1/billing-runs/{run.id}/finalize/')
    assert resp.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED)


@pytest.mark.django_db
def test_finalize_endpoint_cross_tenant_404():
    tenant_a = make_tenant(name='FinalizeTA')
    tenant_b = make_tenant(name='FinalizeTB')
    site = make_site(tenant_a)
    device = make_device(tenant_a, site)
    stream = make_stream(device)
    account = make_account(tenant_a)
    run = make_run_at_draft(tenant_a, site, account, stream)

    admin_b = make_user(tenant_b)
    client_b = auth_client(admin_b)

    resp = client_b.post(f'/api/v1/billing-runs/{run.id}/finalize/')
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Void API endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_void_endpoint_voids_run_and_invoices():
    tenant = make_tenant(name='VoidAPI')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    run.status = BillingRun.Status.FINALIZED
    run.save()
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-VOID-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=300, gst_cents=30, total_cents=330,
        status=BillingInvoice.Status.DELIVERED,
    )

    admin = make_user(tenant)
    client = auth_client(admin)

    with patch('apps.billing.views.send_void_notification_email') as mock_notif:
        resp = client.post(
            f'/api/v1/billing-runs/{run.id}/void/',
            {'reason': 'Test void', 'silent_void': False},
            format='json',
        )

    assert resp.status_code == status.HTTP_200_OK
    run.refresh_from_db()
    assert run.status == BillingRun.Status.VOIDED
    assert run.void_reason == 'Test void'

    invoice.refresh_from_db()
    assert invoice.status == BillingInvoice.Status.VOID
    assert invoice.voided_at is not None

    mock_notif.delay.assert_called_once_with(invoice.id)


@pytest.mark.django_db
def test_void_endpoint_silent_void_suppresses_email():
    tenant = make_tenant(name='SilentVoidTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    run.status = BillingRun.Status.FINALIZED
    run.save()
    BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-SILENT-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
        status=BillingInvoice.Status.DELIVERED,
    )

    admin = make_user(tenant)
    client = auth_client(admin)

    with patch('apps.billing.views.send_void_notification_email') as mock_notif:
        resp = client.post(
            f'/api/v1/billing-runs/{run.id}/void/',
            {'silent_void': True},
            format='json',
        )

    assert resp.status_code == status.HTTP_200_OK
    mock_notif.delay.assert_not_called()


@pytest.mark.django_db
def test_void_endpoint_400_on_non_finalized():
    tenant = make_tenant(name='VoidDraftTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)  # status=draft

    admin = make_user(tenant)
    client = auth_client(admin)

    resp = client.post(f'/api/v1/billing-runs/{run.id}/void/', {}, format='json')
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_void_endpoint_403_for_operator():
    tenant = make_tenant(name='VoidOpTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    run.status = BillingRun.Status.FINALIZED
    run.save()
    operator = make_user(tenant, role=TenantUser.Role.OPERATOR)
    client = auth_client(operator)

    resp = client.post(f'/api/v1/billing-runs/{run.id}/void/', {}, format='json')
    assert resp.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED)


@pytest.mark.django_db
def test_void_endpoint_cross_tenant_404():
    tenant_a = make_tenant(name='VoidTA')
    tenant_b = make_tenant(name='VoidTB')
    site = make_site(tenant_a)
    device = make_device(tenant_a, site)
    stream = make_stream(device)
    account = make_account(tenant_a)
    run = make_run_at_draft(tenant_a, site, account, stream)
    run.status = BillingRun.Status.FINALIZED
    run.save()

    admin_b = make_user(tenant_b)
    client_b = auth_client(admin_b)

    resp = client_b.post(f'/api/v1/billing-runs/{run.id}/void/', {}, format='json')
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Invoice list / detail / pdf / resend endpoints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_invoice_list_scoped_to_tenant():
    tenant_a = make_tenant(name='InvListTA')
    tenant_b = make_tenant(name='InvListTB')
    site_a = make_site(tenant_a)
    device_a = make_device(tenant_a, site_a)
    stream_a = make_stream(device_a)
    account_a = make_account(tenant_a)
    run_a = make_run_at_draft(tenant_a, site_a, account_a, stream_a)
    run_a.status = BillingRun.Status.FINALIZED
    run_a.save()
    BillingInvoice.objects.create(
        billing_run=run_a, billing_account=account_a,
        invoice_number='INV-A-1',
        period_start=run_a.period_start, period_end=run_a.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
    )

    admin_b = make_user(tenant_b)
    client_b = auth_client(admin_b)
    resp = client_b.get('/api/v1/invoices/')

    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.data) == 0


@pytest.mark.django_db
def test_invoice_pdf_endpoint_returns_signed_url():
    tenant = make_tenant(name='InvPDFTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-PDF-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
        pdf_object_key='invoices/acme/2026/INV-PDF-1.pdf',
    )

    admin = make_user(tenant)
    client = auth_client(admin)

    with patch('apps.billing.views.generate_pdf_signed_url', return_value='https://s3/pdf') as mock_url:
        resp = client.get(f'/api/v1/invoices/{invoice.id}/pdf/')

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data['url'] == 'https://s3/pdf'
    assert resp.data['expires_in'] == 900
    mock_url.assert_called_once_with(invoice.pdf_object_key, expiry_seconds=900)


@pytest.mark.django_db
def test_invoice_pdf_endpoint_404_when_no_pdf():
    tenant = make_tenant(name='InvNoPDFTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-NOPDF-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
        pdf_object_key='',
    )

    admin = make_user(tenant)
    client = auth_client(admin)
    resp = client.get(f'/api/v1/invoices/{invoice.id}/pdf/')
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_invoice_resend_resets_delivery_status():
    tenant = make_tenant(name='ResendTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-RESEND-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
        delivery_status=BillingInvoice.DeliveryStatus.FAILED,
        status=BillingInvoice.Status.DRAFT,
    )

    admin = make_user(tenant)
    client = auth_client(admin)

    with patch('apps.billing.views.send_invoice_email') as mock_task:
        resp = client.post(f'/api/v1/invoices/{invoice.id}/resend/')

    assert resp.status_code == status.HTTP_202_ACCEPTED
    invoice.refresh_from_db()
    assert invoice.delivery_status == BillingInvoice.DeliveryStatus.PENDING
    mock_task.delay.assert_called_once_with(invoice.id)


@pytest.mark.django_db
def test_invoice_resend_blocked_on_void():
    tenant = make_tenant(name='ResendVoidTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-RESEND-VOID',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
        status=BillingInvoice.Status.VOID,
    )

    admin = make_user(tenant)
    client = auth_client(admin)
    resp = client.post(f'/api/v1/invoices/{invoice.id}/resend/')
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_invoice_detail_cross_tenant_404():
    tenant_a = make_tenant(name='InvDetailTA')
    tenant_b = make_tenant(name='InvDetailTB')
    site_a = make_site(tenant_a)
    device_a = make_device(tenant_a, site_a)
    stream_a = make_stream(device_a)
    account_a = make_account(tenant_a)
    run_a = make_run_at_draft(tenant_a, site_a, account_a, stream_a)
    invoice = BillingInvoice.objects.create(
        billing_run=run_a, billing_account=account_a,
        invoice_number='INV-XTEN-1',
        period_start=run_a.period_start, period_end=run_a.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
    )

    admin_b = make_user(tenant_b)
    client_b = auth_client(admin_b)
    resp = client_b.get(f'/api/v1/invoices/{invoice.id}/')
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_invoice_viewonly_can_read():
    tenant = make_tenant(name='InvViewTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-VIEW-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
    )
    viewer = make_user(tenant, role=TenantUser.Role.VIEWER)
    client = auth_client(viewer)

    resp = client.get(f'/api/v1/invoices/{invoice.id}/')
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_invoice_resend_forbidden_for_operator():
    tenant = make_tenant(name='InvResendOpTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)
    invoice = BillingInvoice.objects.create(
        billing_run=run, billing_account=account,
        invoice_number='INV-OP-1',
        period_start=run.period_start, period_end=run.period_end,
        subtotal_cents=100, gst_cents=10, total_cents=110,
        status=BillingInvoice.Status.DRAFT,
    )
    operator = make_user(tenant, role=TenantUser.Role.OPERATOR)
    client = auth_client(operator)

    resp = client.post(f'/api/v1/invoices/{invoice.id}/resend/')
    assert resp.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Line-items CSV export
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_line_items_csv_format():
    tenant = make_tenant(name='CSVTenant')
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    account = make_account(tenant)
    run = make_run_at_draft(tenant, site, account, stream)

    admin = make_user(tenant)
    client = auth_client(admin)
    resp = client.get(f'/api/v1/billing-runs/{run.id}/line-items-csv/')

    assert resp.status_code == status.HTTP_200_OK
    assert 'text/csv' in resp.get('Content-Type', '')

    # Read streamed content.
    content = b''.join(resp.streaming_content).decode('utf-8')
    lines = [ln for ln in content.splitlines() if ln]

    # Header row
    header = lines[0]
    assert 'account_name' in header
    assert 'line_kind' in header
    assert 'amount_cents' in header

    # Data rows (energy + supply)
    assert len(lines) >= 3  # header + 2 line items


@pytest.mark.django_db
def test_line_items_csv_cross_tenant_404():
    tenant_a = make_tenant(name='CSVTA')
    tenant_b = make_tenant(name='CSVTB')
    site_a = make_site(tenant_a)
    device_a = make_device(tenant_a, site_a)
    stream_a = make_stream(device_a)
    account_a = make_account(tenant_a)
    run_a = make_run_at_draft(tenant_a, site_a, account_a, stream_a)

    admin_b = make_user(tenant_b)
    client_b = auth_client(admin_b)
    resp = client_b.get(f'/api/v1/billing-runs/{run_a.id}/line-items-csv/')
    assert resp.status_code == status.HTTP_404_NOT_FOUND
