"""Sprint 29 — MeterProfile, hierarchy invariants, and bulk CSV import.

Covers every invariant the billing engine (Phase B) will rely on:
  - role / parent shape rules
  - one gate per site
  - hierarchical-toggle guard on the Site
  - deactivation of a gate while children exist
  - NMI uniqueness per tenant
  - cross-tenant isolation
  - role permissions
  - Stream.billing_role PATCH

Ref: SPEC.md § Feature: Metering Model — Meter Profiles
     ROADMAP.md § Sprint 29
"""
from __future__ import annotations

import io

import pytest
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.metering.models import MeterProfile
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
    """Return a shared DeviceType — created once per test DB to dodge the slug UNIQUE constraint."""
    dt, _ = DeviceType.objects.get_or_create(
        slug='meter',
        defaults={
            'name': 'Meter',
            'connection_type': 'mqtt',
            'is_push': True,
            'stream_type_definitions': [],
            'commands': [],
        },
    )
    return dt


def make_site(tenant, name='Site A', *, hierarchical=False):
    return Site.objects.create(
        tenant=tenant, name=name, is_hierarchical=hierarchical,
    )


def make_device(tenant, site, *, serial, device_type=None, status_=Device.Status.ACTIVE):
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=device_type or make_device_type(),
        name=f'Device {serial}',
        serial_number=serial,
        status=status_,
        topic_format='that_place_v1',
    )


def url_for(device):
    return f'/api/v1/devices/{device.pk}/meter-profile/'


# ---------------------------------------------------------------------------
# Invariants — happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMeterProfileCRUD:

    def test_admin_can_create_simple_consumption_meter(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        device = make_device(tenant, site, serial='M-001')

        resp = auth_client(admin).put(url_for(device), {
            'meter_role': 'consumption',
            'nmi': '6203456789',
            'phases': 1,
        })
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['meter_role'] == 'consumption'
        assert resp.data['nmi'] == '6203456789'
        assert MeterProfile.objects.filter(device=device).exists()

    def test_get_returns_404_when_no_profile(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        device = make_device(tenant, site, serial='M-002')
        resp = auth_client(admin).get(url_for(device))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_admin_can_patch_phases(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        device = make_device(tenant, site, serial='M-003')
        client = auth_client(admin)
        client.put(url_for(device), {'meter_role': 'consumption', 'phases': 1})
        resp = client.patch(url_for(device), {'phases': 3})
        assert resp.status_code == status.HTTP_200_OK
        assert MeterProfile.objects.get(device=device).phases == 3

    def test_operator_cannot_create_meter_profile(self):
        tenant = make_tenant()
        make_user(tenant)
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@x.test')
        site = make_site(tenant)
        device = make_device(tenant, site, serial='M-004')
        resp = auth_client(op).put(url_for(device), {'meter_role': 'consumption'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not MeterProfile.objects.filter(device=device).exists()

    def test_view_only_can_read_but_not_write(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        viewer = make_user(tenant, role=TenantUser.Role.VIEWER, email='v@x.test')
        site = make_site(tenant)
        device = make_device(tenant, site, serial='M-005')
        auth_client(admin).put(url_for(device), {'meter_role': 'consumption'})

        client = auth_client(viewer)
        assert client.get(url_for(device)).status_code == status.HTTP_200_OK
        assert client.put(url_for(device), {'meter_role': 'gate'}).status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Invariants — role / parent shape
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMeterRoleInvariants:

    def test_gate_with_parent_is_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gate_device = make_device(tenant, site, serial='G-001')
        # Establish an existing gate to use as the (illegal) parent
        # for the second gate attempt
        auth_client(admin).put(url_for(gate_device), {'meter_role': 'gate'})
        second = make_device(tenant, site, serial='G-002')
        resp = auth_client(admin).put(url_for(second), {
            'meter_role': 'gate', 'parent_meter': gate_device.id,
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'parent_meter' in resp.data['error']['details']

    def test_child_without_parent_on_hierarchical_site_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        device = make_device(tenant, site, serial='C-001')
        resp = auth_client(admin).put(url_for(device), {'meter_role': 'child'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'parent_meter' in resp.data['error']['details']

    def test_child_with_correct_parent_accepted(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gate_dev = make_device(tenant, site, serial='G-100')
        child_dev = make_device(tenant, site, serial='C-100')
        client = auth_client(admin)
        client.put(url_for(gate_dev), {'meter_role': 'gate'})
        resp = client.put(url_for(child_dev), {
            'meter_role': 'child',
            'parent_meter': gate_dev.id,
        })
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['parent_meter'] == gate_dev.id

    def test_child_parent_on_different_site_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site_a = make_site(tenant, 'A', hierarchical=True)
        site_b = make_site(tenant, 'B', hierarchical=True)
        gate_a = make_device(tenant, site_a, serial='GA-001')
        child_b = make_device(tenant, site_b, serial='CB-001')
        client = auth_client(admin)
        client.put(url_for(gate_a), {'meter_role': 'gate'})
        resp = client.put(url_for(child_b), {
            'meter_role': 'child', 'parent_meter': gate_a.id,
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'parent_meter' in resp.data['error']['details']

    def test_child_parent_is_not_a_gate_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        # Create a non-gate meter to (incorrectly) reference as parent
        gen_dev = make_device(tenant, site, serial='GEN-001')
        child_dev = make_device(tenant, site, serial='C-200')
        client = auth_client(admin)
        client.put(url_for(gen_dev), {'meter_role': 'generation'})
        resp = client.put(url_for(child_dev), {
            'meter_role': 'child', 'parent_meter': gen_dev.id,
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_two_gates_per_site_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        d1 = make_device(tenant, site, serial='G1')
        d2 = make_device(tenant, site, serial='G2')
        client = auth_client(admin)
        client.put(url_for(d1), {'meter_role': 'gate'})
        resp = client.put(url_for(d2), {'meter_role': 'gate'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'meter_role' in resp.data['error']['details']

    def test_common_area_on_hierarchical_site_requires_parent(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gate_dev = make_device(tenant, site, serial='G-CA')
        ca_dev = make_device(tenant, site, serial='CA-001')
        client = auth_client(admin)
        client.put(url_for(gate_dev), {'meter_role': 'gate'})
        no_parent = client.put(url_for(ca_dev), {'meter_role': 'common_area'})
        assert no_parent.status_code == status.HTTP_400_BAD_REQUEST
        with_parent = client.put(url_for(ca_dev), {
            'meter_role': 'common_area', 'parent_meter': gate_dev.id,
        })
        assert with_parent.status_code == status.HTTP_201_CREATED


# ---------------------------------------------------------------------------
# Invariants — deactivation guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGateDeletionGuard:

    def test_cannot_delete_gate_with_children(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gate_dev = make_device(tenant, site, serial='G-DEL')
        child_dev = make_device(tenant, site, serial='C-DEL')
        client = auth_client(admin)
        client.put(url_for(gate_dev), {'meter_role': 'gate'})
        client.put(url_for(child_dev), {
            'meter_role': 'child', 'parent_meter': gate_dev.id,
        })
        resp = client.delete(url_for(gate_dev))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'gate_has_children'

    def test_can_delete_gate_after_removing_children(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gate_dev = make_device(tenant, site, serial='G-DEL2')
        child_dev = make_device(tenant, site, serial='C-DEL2')
        client = auth_client(admin)
        client.put(url_for(gate_dev), {'meter_role': 'gate'})
        client.put(url_for(child_dev), {
            'meter_role': 'child', 'parent_meter': gate_dev.id,
        })
        # Remove the child first…
        client.delete(url_for(child_dev))
        # …then the gate is allowed.
        resp = client.delete(url_for(gate_dev))
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not MeterProfile.objects.filter(device=gate_dev).exists()


# ---------------------------------------------------------------------------
# Site.is_hierarchical toggle guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSiteHierarchicalToggleGuard:

    def test_cannot_disable_hierarchical_while_gate_exists(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gate_dev = make_device(tenant, site, serial='SHG-1')
        auth_client(admin).put(url_for(gate_dev), {'meter_role': 'gate'})
        resp = auth_client(admin).patch(
            f'/api/v1/sites/{site.pk}/', {'is_hierarchical': False},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'is_hierarchical' in resp.data['error']['details']

    def test_can_disable_hierarchical_when_only_flat_role_meters_present(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        gen_dev = make_device(tenant, site, serial='SHG-FLAT')
        auth_client(admin).put(url_for(gen_dev), {'meter_role': 'generation'})
        resp = auth_client(admin).patch(
            f'/api/v1/sites/{site.pk}/', {'is_hierarchical': False},
        )
        assert resp.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# NMI uniqueness per tenant
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNmiUniqueness:

    def test_same_nmi_same_tenant_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        d1 = make_device(tenant, site, serial='N-001')
        d2 = make_device(tenant, site, serial='N-002')
        client = auth_client(admin)
        ok = client.put(url_for(d1), {
            'meter_role': 'consumption', 'nmi': '6203456789',
        })
        assert ok.status_code == status.HTTP_201_CREATED
        dup = client.put(url_for(d2), {
            'meter_role': 'consumption', 'nmi': '6203456789',
        })
        assert dup.status_code == status.HTTP_400_BAD_REQUEST
        assert 'nmi' in dup.data['error']['details']

    def test_same_nmi_different_tenant_allowed(self):
        t1 = make_tenant('A')
        t2 = make_tenant('B')
        a1 = make_user(t1, email='a1@a.test')
        a2 = make_user(t2, email='a2@b.test')
        s1 = make_site(t1)
        s2 = make_site(t2)
        d1 = make_device(t1, s1, serial='N-T1')
        d2 = make_device(t2, s2, serial='N-T2')
        assert auth_client(a1).put(url_for(d1), {
            'meter_role': 'consumption', 'nmi': '6203456789',
        }).status_code == status.HTTP_201_CREATED
        assert auth_client(a2).put(url_for(d2), {
            'meter_role': 'consumption', 'nmi': '6203456789',
        }).status_code == status.HTTP_201_CREATED

    def test_multiple_meters_without_nmi_allowed(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        d1 = make_device(tenant, site, serial='NoNMI-1')
        d2 = make_device(tenant, site, serial='NoNMI-2')
        client = auth_client(admin)
        assert client.put(url_for(d1), {'meter_role': 'sub_check'}).status_code == 201
        assert client.put(url_for(d2), {'meter_role': 'sub_check'}).status_code == 201

    def test_invalid_nmi_format_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        device = make_device(tenant, site, serial='BadNMI')
        resp = auth_client(admin).put(url_for(device), {
            'meter_role': 'consumption', 'nmi': 'abc',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'nmi' in resp.data['error']['details']


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossTenantIsolation:

    def test_cannot_access_other_tenant_meter_profile(self):
        t1 = make_tenant('A')
        t2 = make_tenant('B')
        a1 = make_user(t1, email='a@a.test')
        s2 = make_site(t2)
        d2 = make_device(t2, s2, serial='XT-1')
        resp = auth_client(a1).get(url_for(d2))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_write_meter_profile_on_other_tenant_device(self):
        t1 = make_tenant('A')
        t2 = make_tenant('B')
        a1 = make_user(t1, email='a@a.test')
        s2 = make_site(t2)
        d2 = make_device(t2, s2, serial='XT-2')
        resp = auth_client(a1).put(url_for(d2), {'meter_role': 'consumption'})
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Stream.billing_role
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStreamBillingRolePatch:

    def test_admin_can_set_billing_role_via_patch(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        device = make_device(tenant, site, serial='S-1')
        stream = Stream.objects.create(
            device=device, key='kwh_import', label='kWh import', unit='kWh',
        )
        resp = auth_client(admin).patch(
            f'/api/v1/streams/{stream.pk}/', {'billing_role': 'grid_import'},
        )
        assert resp.status_code == status.HTTP_200_OK
        stream.refresh_from_db()
        assert stream.billing_role == 'grid_import'

    def test_operator_cannot_patch_billing_role(self):
        tenant = make_tenant()
        make_user(tenant)
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@s.test')
        site = make_site(tenant)
        device = make_device(tenant, site, serial='S-2')
        stream = Stream.objects.create(device=device, key='kwh', label='kWh')
        resp = auth_client(op).patch(
            f'/api/v1/streams/{stream.pk}/', {'billing_role': 'grid_import'},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_billing_role_rejected(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        device = make_device(tenant, site, serial='S-3')
        stream = Stream.objects.create(device=device, key='kwh', label='kWh')
        resp = auth_client(admin).patch(
            f'/api/v1/streams/{stream.pk}/', {'billing_role': 'gibberish'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Bulk CSV import
# ---------------------------------------------------------------------------


def _upload_csv(client, csv_text: str):
    return client.post(
        '/api/v1/meter-profiles/bulk/',
        {'file': io.BytesIO(csv_text.encode('utf-8'))},
        format='multipart',
    )


@pytest.mark.django_db
class TestBulkImport:

    def _client_admin_with_devices(self, *, hierarchical=False):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=hierarchical)
        return tenant, admin, site

    def test_bulk_upsert_flat_consumption_meters(self):
        tenant, admin, site = self._client_admin_with_devices()
        for s in ('B-001', 'B-002', 'B-003'):
            make_device(tenant, site, serial=s)
        csv_text = (
            'device_serial,meter_role,nmi,phases\n'
            'B-001,consumption,6203456701,1\n'
            'B-002,consumption,6203456702,1\n'
            'B-003,consumption,6203456703,3\n'
        )
        # Use APIClient with multipart file upload
        client = APIClient()
        resp = client.post('/api/v1/auth/login/', {'email': admin.email, 'password': 'pass123'})
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
        resp = client.post(
            '/api/v1/meter-profiles/bulk/',
            {'file': self._csv_file(csv_text)},
            format='multipart',
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data['imported'] == 3
        assert resp.data['errors'] == []
        assert MeterProfile.objects.filter(tenant=tenant).count() == 3

    def test_bulk_upsert_updates_existing(self):
        tenant, admin, site = self._client_admin_with_devices()
        device = make_device(tenant, site, serial='U-001')
        MeterProfile.objects.create(
            tenant=tenant, device=device,
            meter_role=MeterProfile.MeterRole.CONSUMPTION, phases=1,
        )
        csv_text = (
            'device_serial,meter_role,phases\n'
            'U-001,consumption,3\n'
        )
        client = auth_client(admin)
        resp = client.post(
            '/api/v1/meter-profiles/bulk/',
            {'file': self._csv_file(csv_text)},
            format='multipart',
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['imported'] == 1
        device.refresh_from_db()
        assert device.meter_profile.phases == 3

    def test_bulk_import_reports_per_row_errors(self):
        tenant, admin, site = self._client_admin_with_devices()
        make_device(tenant, site, serial='OK-001')
        csv_text = (
            'device_serial,meter_role\n'
            'OK-001,consumption\n'           # ok
            'NOT-A-DEVICE,consumption\n'     # row 3 — unknown device
            ',consumption\n'                 # row 4 — missing serial
            'OK-001,not_a_role\n'            # row 5 — bad role
        )
        client = auth_client(admin)
        resp = client.post(
            '/api/v1/meter-profiles/bulk/',
            {'file': self._csv_file(csv_text)},
            format='multipart',
        )
        # Imported = 1 from row 2 (initial create);
        # the OK-001 row 5 update fails before mutating because of bad role.
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['imported'] == 1
        error_rows = sorted(e['row'] for e in resp.data['errors'])
        assert error_rows == [3, 4, 5]

    def test_bulk_import_cross_tenant_serial_rejected(self):
        # Tenant A's admin uploads a row whose device_serial belongs to Tenant B
        t_a = make_tenant('A')
        t_b = make_tenant('B')
        admin_a = make_user(t_a, email='a@a.test')
        s_b = make_site(t_b)
        make_device(t_b, s_b, serial='B-OWN-001')
        csv_text = (
            'device_serial,meter_role\n'
            'B-OWN-001,consumption\n'
        )
        client = auth_client(admin_a)
        resp = client.post(
            '/api/v1/meter-profiles/bulk/',
            {'file': self._csv_file(csv_text)},
            format='multipart',
        )
        # Tenant A cannot see Tenant B's device → reported as an unknown serial.
        assert resp.data['imported'] == 0
        assert len(resp.data['errors']) == 1

    def test_operator_blocked_from_bulk_import(self):
        tenant = make_tenant()
        make_user(tenant)
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@b.test')
        client = auth_client(op)
        resp = client.post(
            '/api/v1/meter-profiles/bulk/',
            {'file': self._csv_file('device_serial,meter_role\n')},
            format='multipart',
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def _csv_file(self, text: str):
        """Build an in-memory upload that DRF's MultiPartParser will accept."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(
            'meters.csv', text.encode('utf-8'), content_type='text/csv',
        )


# ---------------------------------------------------------------------------
# Site serializer exposes new fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSiteSerializerHierarchyFields:

    def test_site_payload_includes_hierarchy_fields(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        resp = auth_client(admin).get(f'/api/v1/sites/{site.pk}/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['is_hierarchical'] is False
        assert resp.data['common_area_apportionment_method'] == 'pro_rata_consumption'

    def test_admin_can_update_apportionment_method(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant, hierarchical=True)
        resp = auth_client(admin).patch(
            f'/api/v1/sites/{site.pk}/',
            {'common_area_apportionment_method': 'by_floor_area'},
        )
        assert resp.status_code == status.HTTP_200_OK
        site.refresh_from_db()
        assert site.common_area_apportionment_method == 'by_floor_area'

    def test_reconciliation_tolerance_bounds_enforced(self):
        tenant = make_tenant()
        admin = make_user(tenant)
        site = make_site(tenant)
        resp = auth_client(admin).patch(
            f'/api/v1/sites/{site.pk}/',
            {'reconciliation_tolerance_percent': 150},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
