"""Tests for Sprint 13: health-history endpoint and status_indicator_mappings.

Ref: SPEC.md § Feature: Dashboards & Visualisation — Health/Uptime Chart,
     Status Indicator widget.
"""
import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import Stream, StreamReading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_fm_admin(email='fm@that-place.io', password='testpass123'):
    return User.objects.create_user(email=email, password=password, is_that_place_admin=True)


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_device_type(name='Weather Station'):
    return DeviceType.objects.create(
        name=name,
        slug=slugify(name),
        connection_type='mqtt',
        is_push=True,
        default_offline_threshold_minutes=10,
        command_ack_timeout_seconds=30,
    )


def make_site(tenant, name='Main Site'):
    return Site.objects.create(tenant=tenant, name=name)


def make_device(tenant, site, device_type, serial='SN001'):
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=device_type,
        name='Test Device',
        serial_number=serial,
        status=Device.Status.ACTIVE,
    )


def make_stream(device, key='temperature'):
    return Stream.objects.create(device=device, key=key, label=key, data_type='numeric')


# ---------------------------------------------------------------------------
# health-history endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealthHistory:
    """Tests for GET /api/v1/devices/:id/health-history/"""

    def setup_method(self):
        self.tenant = make_tenant('HealthCo')
        self.user = make_tenant_user('admin@healthco.com', self.tenant)
        self.client = auth_client(self.user)
        self.device_type = make_device_type()
        self.site = make_site(self.tenant)
        self.device = make_device(self.tenant, self.site, self.device_type)
        self.stream = make_stream(self.device)

    def test_returns_timeline(self):
        """Happy path: returns a timeline with bucket_minutes."""
        StreamReading.objects.create(
            stream=self.stream,
            value=23.4,
            timestamp=timezone.now(),
        )
        resp = self.client.get(
            f'/api/v1/devices/{self.device.id}/health-history/?time_range=1h'
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert 'timeline' in data
        assert 'bucket_minutes' in data
        assert isinstance(data['timeline'], list)
        assert len(data['timeline']) > 0
        first = data['timeline'][0]
        assert 'timestamp' in first
        assert 'is_online' in first

    def test_online_bucket_true_when_reading_present(self):
        """A bucket containing a reading is marked online."""
        StreamReading.objects.create(
            stream=self.stream,
            value=23.4,
            timestamp=timezone.now(),
        )
        resp = self.client.get(
            f'/api/v1/devices/{self.device.id}/health-history/?time_range=1h'
        )
        assert resp.status_code == status.HTTP_200_OK
        timeline = resp.json()['timeline']
        # The most recent bucket should be online (reading just created)
        assert any(entry['is_online'] for entry in timeline)

    def test_all_offline_when_no_readings(self):
        """Timeline entries are all offline when device has no readings."""
        resp = self.client.get(
            f'/api/v1/devices/{self.device.id}/health-history/?time_range=1h'
        )
        assert resp.status_code == status.HTTP_200_OK
        timeline = resp.json()['timeline']
        assert all(not entry['is_online'] for entry in timeline)

    def test_requires_authentication(self):
        """Unauthenticated request is rejected with 401."""
        anon = APIClient()
        resp = anon.get(f'/api/v1/devices/{self.device.id}/health-history/')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_denied(self):
        """Tenant B cannot access Tenant A's device health history."""
        tenant_b = make_tenant('OtherCorp')
        user_b = make_tenant_user('admin@othercorp.com', tenant_b)
        client_b = auth_client(user_b)
        resp = client_b.get(
            f'/api/v1/devices/{self.device.id}/health-history/?time_range=24h'
        )
        # Device not in Tenant B's queryset → 404
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_bucket_size_varies_by_range(self):
        """Bucket minutes are smaller for short ranges, larger for long ranges."""
        resp_1h = self.client.get(
            f'/api/v1/devices/{self.device.id}/health-history/?time_range=1h'
        )
        resp_30d = self.client.get(
            f'/api/v1/devices/{self.device.id}/health-history/?time_range=30d'
        )
        assert resp_1h.json()['bucket_minutes'] < resp_30d.json()['bucket_minutes']


# ---------------------------------------------------------------------------
# status_indicator_mappings field tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStatusIndicatorMappings:
    """Tests for status_indicator_mappings on DeviceType."""

    def setup_method(self):
        self.fm_admin = make_fm_admin()
        self.fm_client = auth_client(self.fm_admin)

    def test_fm_admin_can_set_mappings(self):
        """That Place Admin can create a device type with status_indicator_mappings."""
        mappings = {
            'motor_status': [
                {'value': 'running', 'color': '#22C55E', 'label': 'Running'},
                {'value': 'fault', 'color': '#EF4444', 'label': 'Fault'},
            ]
        }
        resp = self.fm_client.post('/api/v1/device-types/', {
            'name': 'Motor Controller',
            'slug': 'motor-controller',
            'connection_type': 'mqtt',
            'is_push': True,
            'default_offline_threshold_minutes': 10,
            'command_ack_timeout_seconds': 30,
            'commands': [],
            'stream_type_definitions': [],
            'status_indicator_mappings': mappings,
            'is_active': True,
        }, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()['status_indicator_mappings'] == mappings

    def test_mappings_returned_in_list(self):
        """status_indicator_mappings is included in the device type list response."""
        mappings = {'pump_state': [{'value': 'on', 'color': '#22C55E', 'label': 'On'}]}
        DeviceType.objects.create(
            name='Pump',
            slug='pump',
            connection_type='mqtt',
            is_push=True,
            default_offline_threshold_minutes=10,
            command_ack_timeout_seconds=30,
            status_indicator_mappings=mappings,
        )
        tenant = make_tenant('ReadCo')
        user = make_tenant_user('reader@readco.com', tenant)
        client = auth_client(user)
        resp = client.get('/api/v1/device-types/')
        assert resp.status_code == status.HTTP_200_OK
        found = next((dt for dt in resp.json() if dt['slug'] == 'pump'), None)
        assert found is not None
        assert found['status_indicator_mappings'] == mappings

    def test_mappings_default_empty_dict(self):
        """status_indicator_mappings defaults to {} when not provided."""
        resp = self.fm_client.post('/api/v1/device-types/', {
            'name': 'Simple Sensor',
            'slug': 'simple-sensor',
            'connection_type': 'mqtt',
            'is_push': True,
            'default_offline_threshold_minutes': 10,
            'command_ack_timeout_seconds': 30,
            'commands': [],
            'stream_type_definitions': [],
            'is_active': True,
        }, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()['status_indicator_mappings'] == {}
