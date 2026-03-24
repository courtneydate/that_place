"""Tests for Sprint 9: Stream Configuration.

Covers:
- GET /api/v1/devices/:id/streams/ — list streams with latest value
- GET /api/v1/streams/:id/       — retrieve single stream
- PUT /api/v1/streams/:id/       — update label, unit, display_enabled

Ref: SPEC.md § Feature: Stream Discovery & Configuration
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


def make_device(tenant, serial='DEV-001'):
    dt = DeviceType.objects.create(
        name='Scout', slug='scout',
        connection_type='mqtt', is_push=True,
        stream_type_definitions=[], commands=[],
    )
    site = Site.objects.create(tenant=tenant, name='Site')
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Test Device', serial_number=serial,
        status=Device.Status.ACTIVE, topic_format='that_place_v1',
    )


def make_stream(device, key='Relay_1', label='Relay 1', unit='', data_type='boolean'):
    return Stream.objects.create(
        device=device, key=key, label=label,
        unit=unit, data_type=data_type,
    )


def make_reading(stream, value=1):
    return StreamReading.objects.create(
        stream=stream, value=value, timestamp=timezone.now(),
    )


def make_user(tenant, role=TenantUser.Role.ADMIN, email=None):
    email = email or f'{role}@test.com'
    user = User.objects.create_user(email=email, password='pass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': 'pass123'})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


# ---------------------------------------------------------------------------
# GET /api/v1/devices/:id/streams/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeviceStreamsList:

    def test_returns_streams_for_device(self):
        tenant = make_tenant()
        device = make_device(tenant)
        make_stream(device, 'Relay_1')
        make_stream(device, 'Analog_1', unit='V', data_type='numeric')
        user = make_user(tenant)

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/streams/')

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2
        keys = {s['key'] for s in resp.data}
        assert keys == {'Relay_1', 'Analog_1'}

    def test_includes_latest_value(self):
        tenant = make_tenant(name='Latest Val')
        device = make_device(tenant, 'LV-001')
        stream = make_stream(device, 'Temp', data_type='numeric')
        make_reading(stream, value=22.5)
        user = make_user(tenant)

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/streams/')

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data[0]['latest_value'] == 22.5

    def test_latest_value_null_when_no_readings(self):
        tenant = make_tenant(name='No Readings')
        device = make_device(tenant, 'NR-001')
        make_stream(device, 'Relay_1')
        user = make_user(tenant)

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/streams/')

        assert resp.data[0]['latest_value'] is None
        assert resp.data[0]['latest_timestamp'] is None

    def test_view_only_can_access(self):
        tenant = make_tenant(name='View Only')
        device = make_device(tenant, 'VO-001')
        make_stream(device)
        user = make_user(tenant, role=TenantUser.Role.VIEWER, email='viewer@test.com')

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/streams/')

        assert resp.status_code == status.HTTP_200_OK

    def test_cross_tenant_device_blocked(self):
        tenant_a = make_tenant(name='Tenant A')
        tenant_b = make_tenant(name='Tenant B')
        device_a = make_device(tenant_a, 'TA-001')
        make_stream(device_a)
        user_b = make_user(tenant_b)

        resp = auth_client(user_b).get(f'/api/v1/devices/{device_a.pk}/streams/')

        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET /api/v1/streams/:id/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStreamRetrieve:

    def test_returns_stream_fields(self):
        tenant = make_tenant(name='Retrieve Co')
        device = make_device(tenant, 'RC-001')
        stream = make_stream(device, 'Analog_1', label='Tank Level', unit='%')
        user = make_user(tenant)

        resp = auth_client(user).get(f'/api/v1/streams/{stream.pk}/')

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['key'] == 'Analog_1'
        assert resp.data['label'] == 'Tank Level'
        assert resp.data['unit'] == '%'
        assert 'display_enabled' in resp.data
        assert 'latest_value' in resp.data

    def test_cross_tenant_stream_blocked(self):
        tenant_a = make_tenant(name='TA Stream')
        tenant_b = make_tenant(name='TB Stream')
        device_a = make_device(tenant_a, 'TAS-001')
        stream_a = make_stream(device_a)
        user_b = make_user(tenant_b, email='user_b@test.com')

        resp = auth_client(user_b).get(f'/api/v1/streams/{stream_a.pk}/')

        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# PUT /api/v1/streams/:id/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStreamUpdate:

    def test_admin_can_update_label_and_unit(self):
        tenant = make_tenant(name='Update Co')
        device = make_device(tenant, 'UC-001')
        stream = make_stream(device, 'Analog_1', label='Old Label', unit='')
        user = make_user(tenant)

        resp = auth_client(user).put(f'/api/v1/streams/{stream.pk}/', {
            'label': 'Tank Level',
            'unit': '%',
            'display_enabled': True,
        })

        assert resp.status_code == status.HTTP_200_OK
        stream.refresh_from_db()
        assert stream.label == 'Tank Level'
        assert stream.unit == '%'

    def test_admin_can_disable_display(self):
        tenant = make_tenant(name='Toggle Co')
        device = make_device(tenant, 'TC-001')
        stream = make_stream(device, 'Relay_1')
        user = make_user(tenant)

        resp = auth_client(user).put(f'/api/v1/streams/{stream.pk}/', {
            'label': 'Relay 1',
            'unit': '',
            'display_enabled': False,
        })

        assert resp.status_code == status.HTTP_200_OK
        stream.refresh_from_db()
        assert stream.display_enabled is False

    def test_display_disabled_does_not_affect_data_storage(self):
        """Disabling display_enabled must not delete or prevent future readings."""
        import json

        from apps.ingestion.tasks import process_mqtt_message

        tenant = make_tenant(name='Data Storage Co')
        device = make_device(tenant, 'DS-001')
        stream = make_stream(device, 'Relay_1')
        stream.display_enabled = False
        stream.save()

        process_mqtt_message(
            'that-place/scout/DS-001/telemetry',
            json.dumps({'Relay_1': 1}),
        )

        assert StreamReading.objects.filter(stream=stream).exists()

    def test_viewer_cannot_update(self):
        tenant = make_tenant(name='Viewer Update')
        device = make_device(tenant, 'VU-001')
        stream = make_stream(device)
        user = make_user(tenant, role=TenantUser.Role.VIEWER, email='viewer2@test.com')

        resp = auth_client(user).put(f'/api/v1/streams/{stream.pk}/', {
            'label': 'Hacked',
            'unit': '',
            'display_enabled': True,
        })

        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_readonly_fields_not_writable(self):
        """key and data_type should be ignored even if submitted."""
        tenant = make_tenant(name='Readonly Co')
        device = make_device(tenant, 'RO-001')
        stream = make_stream(device, 'Relay_1', data_type='boolean')
        user = make_user(tenant)

        auth_client(user).put(f'/api/v1/streams/{stream.pk}/', {
            'label': 'New Label',
            'unit': '',
            'display_enabled': True,
            'key': 'hacked_key',
            'data_type': 'string',
        })

        stream.refresh_from_db()
        assert stream.key == 'Relay_1'
        assert stream.data_type == 'boolean'

    def test_cross_tenant_stream_update_blocked(self):
        tenant_a = make_tenant(name='TA Update')
        tenant_b = make_tenant(name='TB Update')
        device_a = make_device(tenant_a, 'TAU-001')
        stream_a = make_stream(device_a)
        user_b = make_user(tenant_b, email='user_b_upd@test.com')

        resp = auth_client(user_b).put(f'/api/v1/streams/{stream_a.pk}/', {
            'label': 'Stolen',
            'unit': '',
            'display_enabled': True,
        })

        assert resp.status_code == status.HTTP_404_NOT_FOUND
