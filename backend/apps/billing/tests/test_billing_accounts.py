"""Sprint 30 — BillingAccount + nested meter/tariff + audit log + bulk import.

Test surface covers every Sprint 30 invariant the Phase B2 billing engine
will rely on:

  * CRUD permissions (Tenant Admin write, others read or 403)
  * Cross-tenant isolation
  * Bulk CSV upsert (incl. per-row errors)
  * Audit log auto-write on created / updated / deactivated
  * Audit log immutability (no API to mutate)
  * Stream-billing_role guard on BillingAccountMeter
  * scope=tenant constraint on tariff assignment
  * Tenant invoicing fields (gst_rate, invoice_number_format)

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
"""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.billing.models import (
    BillingAccount,
    BillingAccountAuditLog,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
)
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import ReferenceDataset
from apps.readings.models import Stream

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(tenant, role=TenantUser.Role.ADMIN, email=None):
    email = email or f'{role}@{tenant.slug}.test'
    user = User.objects.create_user(email=email, password='pass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': 'pass123'})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_device_type():
    dt, _ = DeviceType.objects.get_or_create(
        slug='meter-b30',
        defaults={
            'name': 'Meter',
            'connection_type': 'mqtt',
            'is_push': True,
            'stream_type_definitions': [],
            'commands': [],
        },
    )
    return dt


def make_site(tenant, name='Site'):
    return Site.objects.create(tenant=tenant, name=name)


def make_device(tenant, site=None, serial='B30-D-001'):
    site = site or make_site(tenant)
    return Device.objects.create(
        tenant=tenant, site=site, device_type=make_device_type(),
        name=f'Dev {serial}', serial_number=serial,
        status=Device.Status.ACTIVE, topic_format='that_place_v1',
    )


def make_stream(device, *, key='kwh_import', billing_role=None):
    return Stream.objects.create(
        device=device, key=key, label=key, unit='kWh',
        data_type='numeric', billing_role=billing_role,
    )


def make_tenant_dataset(slug='ppa-test-tariff'):
    return ReferenceDataset.objects.create(
        slug=slug,
        name='PPA Test Tariff',
        dimension_schema={'plan_code': {'type': 'string'}},
        value_schema={'rate_cents_per_kwh': {'type': 'numeric'}},
        scope=ReferenceDataset.Scope.TENANT,
        has_version=True,
    )


URL = '/api/v1/billing-accounts/'


# ---------------------------------------------------------------------------
# CRUD + permissions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBillingAccountCRUD:

    def test_admin_can_create_ppa_host_account(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).post(URL, {
            'name': 'Acme Apartments Body Corporate',
            'customer_reference': 'BC-001',
            'contact_email': 'bc@acme.test',
            'account_type': 'ppa_host',
            'abn': '11122233344',
        })
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['name'] == 'Acme Apartments Body Corporate'
        assert BillingAccount.objects.filter(tenant=tenant).count() == 1

    def test_admin_can_list_accounts(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        BillingAccount.objects.create(tenant=tenant, name='A', account_type='ppa_host')
        BillingAccount.objects.create(tenant=tenant, name='B', account_type='en_tenant')
        resp = auth_client(admin).get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_operator_can_read_but_not_write(self):
        tenant = make_tenant()
        make_user(tenant)
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@a.test')
        client = auth_client(op)
        assert client.get(URL).status_code == status.HTTP_200_OK
        assert client.post(URL, {'name': 'X', 'account_type': 'ppa_host'}).status_code == 403

    def test_abn_validation_strips_spaces_and_rejects_bad_shape(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        client = auth_client(admin)
        ok = client.post(URL, {
            'name': 'OK', 'account_type': 'ppa_host', 'abn': '111 222 333 44',
        })
        assert ok.status_code == 201
        assert ok.data['abn'] == '11122233344'
        bad = client.post(URL, {
            'name': 'Bad', 'account_type': 'ppa_host', 'abn': '1234',
        })
        assert bad.status_code == 400
        assert 'abn' in bad.data['error']['details']

    def test_billing_address_must_be_object(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).post(URL, {
            'name': 'X', 'account_type': 'ppa_host',
            'billing_address': 'just a string',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_destroy_marks_inactive_and_sets_deactivated_at(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        account = BillingAccount.objects.create(
            tenant=tenant, name='To kill', account_type='ppa_host',
        )
        resp = auth_client(admin).delete(f'{URL}{account.pk}/')
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        account.refresh_from_db()
        assert account.is_active is False
        assert account.deactivated_at is not None

    def test_customer_reference_unique_per_tenant(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        client = auth_client(admin)
        first = client.post(URL, {
            'name': 'A', 'account_type': 'ppa_host', 'customer_reference': 'BC-200',
        })
        assert first.status_code == 201
        dup = client.post(URL, {
            'name': 'B', 'account_type': 'ppa_host', 'customer_reference': 'BC-200',
        })
        assert dup.status_code == status.HTTP_400_BAD_REQUEST
        assert 'customer_reference' in dup.data['error']['details']


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossTenantIsolation:

    def test_list_does_not_leak_other_tenant_accounts(self):
        a = make_tenant('A')
        b = make_tenant('B')
        admin_a = make_user(a, email='a@a.test')
        BillingAccount.objects.create(tenant=b, name='B-secret', account_type='ppa_host')
        resp = auth_client(admin_a).get(URL)
        names = [r['name'] for r in resp.data]
        assert 'B-secret' not in names

    def test_get_other_tenant_account_returns_404(self):
        a = make_tenant('A')
        b = make_tenant('B')
        admin_a = make_user(a, email='a@a.test')
        b_account = BillingAccount.objects.create(tenant=b, name='B', account_type='ppa_host')
        resp = auth_client(admin_a).get(f'{URL}{b_account.pk}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Audit log auto-write + immutability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuditLog:

    def test_create_writes_audit_log(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).post(URL, {
            'name': 'Audit me', 'account_type': 'ppa_host',
        })
        account_id = resp.data['id']
        log = BillingAccountAuditLog.objects.filter(billing_account_id=account_id)
        assert log.count() == 1
        entry = log.first()
        assert entry.action == 'created'
        assert entry.actor_user.email == admin.email
        assert 'name' in entry.changed_fields
        assert entry.changed_fields['name']['after'] == 'Audit me'

    def test_update_writes_diff_only(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        client = auth_client(admin)
        created = client.post(URL, {'name': 'Old', 'account_type': 'ppa_host'})
        account_id = created.data['id']
        client.patch(f'{URL}{account_id}/', {'name': 'New'})
        logs = list(BillingAccountAuditLog.objects.filter(billing_account_id=account_id).order_by('occurred_at'))
        assert len(logs) == 2
        update = logs[1]
        assert update.action == 'updated'
        assert update.changed_fields == {'name': {'before': 'Old', 'after': 'New'}}

    def test_destroy_writes_deactivated_action(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        account = BillingAccount.objects.create(
            tenant=tenant, name='Kill', account_type='ppa_host',
        )
        auth_client(admin).delete(f'{URL}{account.pk}/')
        log = BillingAccountAuditLog.objects.filter(
            billing_account=account, action='deactivated',
        )
        assert log.count() == 1

    def test_audit_log_is_immutable_on_save(self):
        tenant = make_tenant()
        account = BillingAccount.objects.create(
            tenant=tenant, name='Audit-immutable', account_type='ppa_host',
        )
        entry = BillingAccountAuditLog.objects.filter(billing_account=account).first()
        entry.changed_fields = {'tampered': True}
        with pytest.raises(RuntimeError):
            entry.save()

    def test_no_log_when_nothing_changed(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        account = BillingAccount.objects.create(
            tenant=tenant, name='Quiet', account_type='ppa_host',
        )
        prior_count = BillingAccountAuditLog.objects.filter(billing_account=account).count()
        # Send a no-op PATCH (same values)
        auth_client(admin).patch(
            f'{URL}{account.pk}/', {'name': 'Quiet'},
        )
        assert BillingAccountAuditLog.objects.filter(
            billing_account=account,
        ).count() == prior_count

    def test_audit_log_endpoint_returns_entries(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        client = auth_client(admin)
        resp = client.post(URL, {'name': 'Logged', 'account_type': 'ppa_host'})
        account_id = resp.data['id']
        client.patch(f'{URL}{account_id}/', {'contact_phone': '0400000000'})
        log_resp = client.get(f'{URL}{account_id}/audit-log/')
        assert log_resp.status_code == status.HTTP_200_OK
        actions = [e['action'] for e in log_resp.data]
        assert 'created' in actions and 'updated' in actions


# ---------------------------------------------------------------------------
# Nested meter endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBillingAccountMeter:

    def test_link_stream_with_billing_role(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        device = make_device(tenant)
        stream = make_stream(device, billing_role='grid_import')
        account = BillingAccount.objects.create(
            tenant=tenant, name='X', account_type='en_tenant',
        )
        resp = auth_client(admin).post(
            f'{URL}{account.pk}/meters/',
            {'stream': stream.id, 'effective_from': '2026-05-01'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert BillingAccountMeter.objects.filter(billing_account=account).count() == 1

    def test_link_stream_without_billing_role_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        device = make_device(tenant)
        stream = make_stream(device, billing_role=None)
        account = BillingAccount.objects.create(
            tenant=tenant, name='X', account_type='en_tenant',
        )
        resp = auth_client(admin).post(
            f'{URL}{account.pk}/meters/',
            {'stream': stream.id, 'effective_from': '2026-05-01'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'stream' in resp.data['error']['details']

    def test_link_cross_tenant_stream_rejected(self):
        t_a = make_tenant('A')
        t_b = make_tenant('B')
        admin_a = make_user(t_a, email='a@a.test')
        device_b = make_device(t_b, serial='B-CT-001')
        stream_b = make_stream(device_b, billing_role='consumption')
        account_a = BillingAccount.objects.create(
            tenant=t_a, name='A', account_type='ppa_host',
        )
        resp = auth_client(admin_a).post(
            f'{URL}{account_a.pk}/meters/',
            {'stream': stream_b.id, 'effective_from': '2026-05-01'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_operator_cannot_link_meter(self):
        tenant = make_tenant()
        make_user(tenant)
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@m.test')
        device = make_device(tenant)
        stream = make_stream(device, billing_role='grid_import')
        account = BillingAccount.objects.create(
            tenant=tenant, name='X', account_type='en_tenant',
        )
        resp = auth_client(op).post(
            f'{URL}{account.pk}/meters/',
            {'stream': stream.id, 'effective_from': '2026-05-01'},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Nested tariff endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBillingAccountTariff:

    def test_admin_can_assign_tenant_scope_dataset(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        dataset = make_tenant_dataset()
        account = BillingAccount.objects.create(
            tenant=tenant, name='X', account_type='ppa_host',
        )
        resp = auth_client(admin).post(
            f'{URL}{account.pk}/tariffs/',
            {
                'dataset': dataset.id,
                'dimension_filter': {'plan_code': 'stage1-2026'},
                'effective_from': '2026-05-01',
            },
            format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert BillingAccountTariffAssignment.objects.filter(
            billing_account=account,
        ).count() == 1

    def test_system_scope_dataset_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        # network-tariffs and co2-factors are scope=system per Sprint 15a
        sys_ds = ReferenceDataset.objects.create(
            slug='sys-ds',
            name='System dataset',
            dimension_schema={'a': {'type': 'string'}},
            value_schema={'b': {'type': 'numeric'}},
            scope=ReferenceDataset.Scope.SYSTEM,
        )
        account = BillingAccount.objects.create(
            tenant=tenant, name='X', account_type='ppa_host',
        )
        resp = auth_client(admin).post(
            f'{URL}{account.pk}/tariffs/',
            {'dataset': sys_ds.id, 'effective_from': '2026-05-01'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'dataset' in resp.data['error']['details']


# ---------------------------------------------------------------------------
# Bulk CSV import
# ---------------------------------------------------------------------------


def _csv_upload(text: str):
    return SimpleUploadedFile(
        'accounts.csv', text.encode('utf-8'), content_type='text/csv',
    )


@pytest.mark.django_db
class TestBulkImport:

    def test_bulk_create_upserts(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        csv_text = (
            'name,customer_reference,account_type,contact_email,abn\n'
            'Bld 1,B1,en_tenant,b1@x.test,11122233344\n'
            'Bld 2,B2,en_tenant,b2@x.test,22233344455\n'
            'Bld 3,B3,en_tenant,b3@x.test,33344455566\n'
        )
        client = auth_client(admin)
        resp = client.post(
            f'{URL}bulk/', {'file': _csv_upload(csv_text)}, format='multipart',
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data['imported'] == 3
        assert resp.data['errors'] == []
        assert BillingAccount.objects.filter(tenant=tenant).count() == 3

    def test_bulk_update_via_customer_reference(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        existing = BillingAccount.objects.create(
            tenant=tenant, name='Original', customer_reference='UPD-001',
            account_type='ppa_host',
        )
        csv_text = (
            'name,customer_reference,account_type\n'
            'Renamed,UPD-001,ppa_host\n'
        )
        client = auth_client(admin)
        resp = client.post(
            f'{URL}bulk/', {'file': _csv_upload(csv_text)}, format='multipart',
        )
        assert resp.data['imported'] == 1
        existing.refresh_from_db()
        assert existing.name == 'Renamed'

    def test_bulk_import_reports_per_row_errors(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        csv_text = (
            'name,customer_reference,account_type,abn\n'
            'Good,G-1,en_tenant,11122233344\n'
            ',G-2,en_tenant,11122233344\n'         # row 3 — missing name
            'Bad role,G-3,not_a_type,11122233344\n'  # row 4 — bad type
            'Bad abn,G-4,en_tenant,not-a-number\n'   # row 5 — bad ABN
        )
        client = auth_client(admin)
        resp = client.post(
            f'{URL}bulk/', {'file': _csv_upload(csv_text)}, format='multipart',
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['imported'] == 1
        rows = sorted(e['row'] for e in resp.data['errors'])
        assert rows == [3, 4, 5]

    def test_operator_blocked_from_bulk_import(self):
        tenant = make_tenant()
        make_user(tenant)
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@b.test')
        client = auth_client(op)
        resp = client.post(
            f'{URL}bulk/',
            {'file': _csv_upload('name,account_type\n')},
            format='multipart',
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Tenant invoicing fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTenantInvoicingSettings:

    def test_settings_payload_includes_invoicing_fields(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).get('/api/v1/settings/')
        assert resp.status_code == status.HTTP_200_OK
        for key in (
            'gst_rate', 'invoice_number_format',
            'invoice_number_sequence', 'invoice_settlement_disclaimer',
        ):
            assert key in resp.data
        assert resp.data['invoice_number_format'] == 'INV-{YYYY}-{seq:06d}'
        assert str(resp.data['gst_rate']) in ('0.1000', '0.1')

    def test_admin_can_patch_gst_rate(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).patch(
            '/api/v1/settings/',
            {'gst_rate': '0.05'},
            format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert str(tenant.gst_rate) == '0.0500'

    def test_gst_rate_outside_0_1_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).patch(
            '/api/v1/settings/',
            {'gst_rate': '1.5'},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invoice_number_format_must_contain_seq_token(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        resp = auth_client(admin).patch(
            '/api/v1/settings/',
            {'invoice_number_format': 'INV-{YYYY}'},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_sequence_is_read_only(self):
        tenant = make_tenant()
        tenant.invoice_number_sequence = 42
        tenant.save(update_fields=['invoice_number_sequence'])
        admin = make_user(tenant)
        resp = auth_client(admin).patch(
            '/api/v1/settings/',
            {'invoice_number_sequence': 9999},
            format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.invoice_number_sequence == 42
