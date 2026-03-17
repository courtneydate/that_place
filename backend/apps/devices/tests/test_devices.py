"""Tests for Sprint 5: DeviceType library and Device registration/approval flow."""
import pytest
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_fm_admin(email='fm@fieldmouse.io', password='testpass123'):
    return User.objects.create_user(
        email=email, password=password, is_fieldmouse_admin=True
    )


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_device_type(name='Weather Station', slug=None):
    return DeviceType.objects.create(
        name=name,
        slug=slug or slugify(name),
        connection_type='mqtt',
        is_push=True,
        default_offline_threshold_minutes=10,
        command_ack_timeout_seconds=30,
    )


def make_site(tenant, name='Main Site'):
    return Site.objects.create(tenant=tenant, name=name)


def make_device(tenant, site, device_type, serial='SERIAL-001', name='Test Device'):
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=device_type,
        name=name,
        serial_number=serial,
    )


DEVICE_TYPES_URL = '/api/v1/device-types/'
DEVICES_URL = '/api/v1/devices/'


# ---------------------------------------------------------------------------
# DeviceType tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeviceTypeList:

    def test_fm_admin_can_list(self):
        fm = make_fm_admin()
        make_device_type('Station A')
        resp = auth_client(fm).get(DEVICE_TYPES_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_tenant_user_can_list(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        make_device_type()
        resp = auth_client(admin).get(DEVICE_TYPES_URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_unauthenticated_cannot_list(self):
        resp = APIClient().get(DEVICE_TYPES_URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestDeviceTypeCreate:

    def test_fm_admin_can_create(self):
        fm = make_fm_admin()
        payload = {
            'name': 'Soil Scout',
            'slug': 'soil-scout',
            'connection_type': 'mqtt',
            'is_push': True,
            'default_offline_threshold_minutes': 15,
            'command_ack_timeout_seconds': 60,
            'commands': [],
            'stream_type_definitions': [
                {'key': 'temperature', 'label': 'Temperature', 'data_type': 'numeric', 'unit': '°C'}
            ],
        }
        resp = auth_client(fm).post(DEVICE_TYPES_URL, payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['name'] == 'Soil Scout'
        assert DeviceType.objects.filter(slug='soil-scout').exists()

    def test_tenant_admin_cannot_create(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(DEVICE_TYPES_URL, {
            'name': 'Hack Type', 'slug': 'hack', 'connection_type': 'mqtt',
        })
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_name_required(self):
        fm = make_fm_admin()
        resp = auth_client(fm).post(DEVICE_TYPES_URL, {'slug': 'no-name', 'connection_type': 'mqtt'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestDeviceTypeUpdate:

    def test_fm_admin_can_update(self):
        fm = make_fm_admin()
        dt = make_device_type()
        payload = {
            'name': 'Updated Name',
            'slug': dt.slug,
            'connection_type': dt.connection_type,
            'is_push': dt.is_push,
            'default_offline_threshold_minutes': 20,
            'command_ack_timeout_seconds': dt.command_ack_timeout_seconds,
            'is_active': dt.is_active,
        }
        resp = auth_client(fm).put(f'{DEVICE_TYPES_URL}{dt.pk}/', payload, format='json')
        assert resp.status_code == status.HTTP_200_OK
        dt.refresh_from_db()
        assert dt.name == 'Updated Name'
        assert dt.default_offline_threshold_minutes == 20

    def test_tenant_admin_cannot_update(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        dt = make_device_type()
        resp = auth_client(admin).put(f'{DEVICE_TYPES_URL}{dt.pk}/', {'name': 'Hack'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Device registration tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeviceRegistration:

    def test_tenant_admin_can_register_device(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        dt = make_device_type()
        resp = auth_client(admin).post(DEVICES_URL, {
            'name': 'Pump Station Scout',
            'serial_number': 'PSS-001',
            'site': site.pk,
            'device_type': dt.pk,
        })
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['status'] == Device.Status.PENDING
        assert Device.objects.filter(serial_number='PSS-001', status='pending').exists()

    def test_operator_cannot_register_device(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        site = make_site(tenant)
        dt = make_device_type()
        resp = auth_client(op).post(DEVICES_URL, {
            'name': 'Device', 'serial_number': 'OP-001',
            'site': site.pk, 'device_type': dt.pk,
        })
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_cannot_register(self):
        resp = APIClient().post(DEVICES_URL, {'name': 'Device'})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_serial_number_must_be_unique(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        dt = make_device_type()
        Device.objects.create(
            tenant=tenant, site=site, device_type=dt,
            name='Existing', serial_number='DUP-001',
        )
        resp = auth_client(admin).post(DEVICES_URL, {
            'name': 'New', 'serial_number': 'DUP-001',
            'site': site.pk, 'device_type': dt.pk,
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_register_to_other_tenants_site(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        site_b = make_site(tenant_b, 'B Site')
        dt = make_device_type()
        resp = auth_client(admin_a).post(DEVICES_URL, {
            'name': 'Device', 'serial_number': 'CROSS-001',
            'site': site_b.pk, 'device_type': dt.pk,
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Device approval flow tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeviceApproval:

    def test_fm_admin_can_approve_pending_device(self):
        tenant = make_tenant()
        site = make_site(tenant)
        dt = make_device_type()
        device = make_device(tenant, site, dt)
        fm = make_fm_admin()
        resp = auth_client(fm).post(f'{DEVICES_URL}{device.pk}/approve/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['status'] == Device.Status.ACTIVE
        device.refresh_from_db()
        assert device.status == Device.Status.ACTIVE

    def test_fm_admin_can_reject_pending_device(self):
        tenant = make_tenant()
        site = make_site(tenant)
        dt = make_device_type()
        device = make_device(tenant, site, dt)
        fm = make_fm_admin()
        resp = auth_client(fm).post(f'{DEVICES_URL}{device.pk}/reject/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['status'] == Device.Status.REJECTED
        device.refresh_from_db()
        assert device.status == Device.Status.REJECTED

    def test_cannot_approve_already_active_device(self):
        tenant = make_tenant()
        site = make_site(tenant)
        dt = make_device_type()
        device = make_device(tenant, site, dt)
        device.status = Device.Status.ACTIVE
        device.save()
        fm = make_fm_admin()
        resp = auth_client(fm).post(f'{DEVICES_URL}{device.pk}/approve/')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_tenant_admin_cannot_approve(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        dt = make_device_type()
        device = make_device(tenant, site, dt)
        resp = auth_client(admin).post(f'{DEVICES_URL}{device.pk}/approve/')
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_tenant_admin_cannot_reject(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        dt = make_device_type()
        device = make_device(tenant, site, dt)
        resp = auth_client(admin).post(f'{DEVICES_URL}{device.pk}/reject/')
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Cross-tenant isolation tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeviceCrossTenantIsolation:

    def test_tenant_a_cannot_see_tenant_b_devices(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        make_tenant_user('admin@b.com', tenant_b)
        site_b = make_site(tenant_b)
        dt = make_device_type()
        make_device(tenant_b, site_b, dt, serial='B-SERIAL-001')

        resp = auth_client(admin_a).get(DEVICES_URL)
        assert resp.status_code == status.HTTP_200_OK
        serials = [d['serial_number'] for d in resp.data]
        assert 'B-SERIAL-001' not in serials

    def test_tenant_a_cannot_retrieve_tenant_b_device(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        make_tenant_user('admin@b.com', tenant_b)
        site_b = make_site(tenant_b)
        dt = make_device_type()
        device_b = make_device(tenant_b, site_b, dt, serial='B-RETRIEVE-001')

        resp = auth_client(admin_a).get(f'{DEVICES_URL}{device_b.pk}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_tenant_a_cannot_delete_tenant_b_device(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        make_tenant_user('admin@b.com', tenant_b)
        site_b = make_site(tenant_b)
        dt = make_device_type()
        device_b = make_device(tenant_b, site_b, dt, serial='B-DELETE-001')

        resp = auth_client(admin_a).delete(f'{DEVICES_URL}{device_b.pk}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert Device.objects.filter(pk=device_b.pk).exists()

    def test_fm_admin_can_see_all_tenants_devices(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        site_a = make_site(tenant_a)
        site_b = make_site(tenant_b)
        dt = make_device_type()
        make_device(tenant_a, site_a, dt, serial='A-001')
        make_device(tenant_b, site_b, dt, serial='B-001')
        fm = make_fm_admin()

        resp = auth_client(fm).get(DEVICES_URL)
        assert resp.status_code == status.HTTP_200_OK
        serials = [d['serial_number'] for d in resp.data]
        assert 'A-001' in serials
        assert 'B-001' in serials


# ---------------------------------------------------------------------------
# Device status filter test
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeviceStatusFilter:

    def test_filter_by_status_pending(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        dt = make_device_type()
        make_device(tenant, site, dt, serial='P-001', name='Pending')
        device_active = make_device(tenant, site, dt, serial='A-001', name='Active')
        device_active.status = Device.Status.ACTIVE
        device_active.save()

        resp = auth_client(admin).get(f'{DEVICES_URL}?status=pending')
        assert resp.status_code == status.HTTP_200_OK
        serials = [d['serial_number'] for d in resp.data]
        assert 'P-001' in serials
        assert 'A-001' not in serials
