"""Tests for DataSource CRUD, device discovery, and device connection.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
from unittest.mock import MagicMock, patch

import pytest
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceHealth, Site
from apps.integrations.models import DataSource, DataSourceDevice, ThirdPartyAPIProvider
from apps.readings.models import Stream, StreamReading

DATA_SOURCES_URL = '/api/v1/data-sources/'


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
    return User.objects.create_user(email=email, password=password, is_fieldmouse_admin=True)


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_provider(name='SoilScouts', slug=None):
    return ThirdPartyAPIProvider.objects.create(
        name=name,
        slug=slug or slugify(name),
        base_url='https://api.soilscouts.example.com',
        auth_type='api_key_header',
        auth_param_schema=[
            {'key': 'X-API-Key', 'label': 'API Key', 'type': 'password', 'required': True},
        ],
        discovery_endpoint={
            'path': '/api/devices/',
            'method': 'GET',
            'device_id_jsonpath': '$.results[*].id',
            'device_name_jsonpath': '$.results[*].name',
        },
        detail_endpoint={
            'path_template': '/api/devices/{device_id}/readings/',
            'method': 'GET',
        },
        available_streams=[
            {'key': 'soil_moisture', 'label': 'Soil Moisture', 'unit': '%',
             'data_type': 'numeric', 'jsonpath': '$.soil_moisture'},
            {'key': 'soil_temp', 'label': 'Soil Temp', 'unit': '°C',
             'data_type': 'numeric', 'jsonpath': '$.soil_temperature'},
        ],
        default_poll_interval_seconds=300,
    )


def make_data_source(tenant, provider, name='My DS'):
    return DataSource.objects.create(
        tenant=tenant,
        provider=provider,
        name=name,
        credentials={'X-API-Key': 'test-key'},
    )


def make_site(tenant, name='Main Site'):
    return Site.objects.create(tenant=tenant, name=name)


# ---------------------------------------------------------------------------
# DataSource CRUD
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDataSourceCRUD:

    def test_tenant_admin_can_create(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        payload = {
            'provider': provider.pk,
            'name': 'My SoilScouts',
            'credentials': {'X-API-Key': 'secret-key'},
        }
        resp = auth_client(user).post(DATA_SOURCES_URL, payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert DataSource.objects.filter(tenant=tenant).count() == 1
        # credentials must not appear in response
        assert 'credentials' not in resp.data

    def test_tenant_admin_can_list_own_sources(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        make_data_source(tenant, provider)
        resp = auth_client(user).get(DATA_SOURCES_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_cross_tenant_isolation(self):
        """Tenant A cannot see Tenant B's data sources."""
        tenant_a = make_tenant('Tenant A')
        tenant_b = make_tenant('Tenant B')
        user_a = make_tenant_user('a@a.com', tenant_a)
        user_b = make_tenant_user('b@b.com', tenant_b)
        provider = make_provider()
        make_data_source(tenant_a, provider, 'A DS')
        make_data_source(tenant_b, provider, 'B DS')

        resp_a = auth_client(user_a).get(DATA_SOURCES_URL)
        resp_b = auth_client(user_b).get(DATA_SOURCES_URL)

        assert len(resp_a.data) == 1
        assert resp_a.data[0]['name'] == 'A DS'
        assert len(resp_b.data) == 1
        assert resp_b.data[0]['name'] == 'B DS'

    def test_viewer_can_list(self):
        tenant = make_tenant()
        user = make_tenant_user('viewer@acme.com', tenant, role=TenantUser.Role.VIEWER)
        provider = make_provider()
        make_data_source(tenant, provider)
        resp = auth_client(user).get(DATA_SOURCES_URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_viewer_cannot_create(self):
        tenant = make_tenant()
        user = make_tenant_user('viewer@acme.com', tenant, role=TenantUser.Role.VIEWER)
        provider = make_provider()
        resp = auth_client(user).post(
            DATA_SOURCES_URL,
            {'provider': provider.pk, 'name': 'X', 'credentials': {}},
            format='json',
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_fm_admin_cannot_access_data_sources(self):
        """FM Admins have no TenantUser, so they cannot access tenant data sources."""
        fm = make_fm_admin()
        resp = auth_client(fm).get(DATA_SOURCES_URL)
        # 403 because IsViewOnly excludes FM Admins
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeviceDiscovery:

    def _discovery_response(self):
        return {
            'results': [
                {'id': 'ABC-001', 'name': 'Scout North'},
                {'id': 'ABC-002', 'name': 'Scout South'},
            ]
        }

    def test_discovery_returns_device_list(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)

        mock_resp = MagicMock()
        mock_resp.json.return_value = self._discovery_response()
        mock_resp.raise_for_status.return_value = None

        with patch('apps.integrations.views.http_requests.request', return_value=mock_resp):
            resp = auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/discover/')

        assert resp.status_code == status.HTTP_200_OK
        devices = resp.data['devices']
        assert len(devices) == 2
        assert devices[0]['external_device_id'] == 'ABC-001'
        assert devices[0]['external_device_name'] == 'Scout North'
        assert not devices[0]['already_connected']

    def test_discovery_flags_already_connected_devices(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)

        # Connect ABC-001 already
        from apps.devices.models import DeviceType
        dt, _ = DeviceType.objects.get_or_create(
            slug='third-party-api',
            defaults={
                'name': '3rd Party API Device',
                'connection_type': 'api',
                'is_push': False,
                'default_offline_threshold_minutes': 30,
                'command_ack_timeout_seconds': 30,
            },
        )
        virtual_dev = Device.objects.create(
            tenant=tenant, site=site, device_type=dt,
            name='Scout North', serial_number='api-soilscouts-1-ABC-001',
            status=Device.Status.ACTIVE,
        )
        DataSourceDevice.objects.create(
            datasource=ds,
            external_device_id='ABC-001',
            external_device_name='Scout North',
            virtual_device=virtual_dev,
            active_stream_keys=['soil_moisture'],
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = self._discovery_response()
        mock_resp.raise_for_status.return_value = None

        with patch('apps.integrations.views.http_requests.request', return_value=mock_resp):
            resp = auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/discover/')

        assert resp.status_code == status.HTTP_200_OK
        devices = {d['external_device_id']: d for d in resp.data['devices']}
        assert devices['ABC-001']['already_connected'] is True
        assert devices['ABC-002']['already_connected'] is False

    def test_discovery_auth_failure_returns_400(self):
        from apps.integrations.auth_handlers import AuthError
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)

        with patch('apps.integrations.views.get_auth_session', side_effect=AuthError('bad creds')):
            resp = auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/discover/')

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'auth_failure'

    def test_discovery_provider_error_returns_502(self):
        import requests as req_lib
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)

        with patch('apps.integrations.views.http_requests.request',
                   side_effect=req_lib.RequestException('timeout')):
            resp = auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/discover/')

        assert resp.status_code == status.HTTP_502_BAD_GATEWAY


# ---------------------------------------------------------------------------
# Device connection
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestConnectDevices:

    def test_connect_single_device(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)

        payload = [{
            'external_device_id': 'ABC-001',
            'external_device_name': 'Scout North',
            'site_id': site.pk,
            'active_stream_keys': ['soil_moisture', 'soil_temp'],
        }]

        resp = auth_client(user).post(
            f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert len(resp.data) == 1

        # Virtual device created as active
        dsd = DataSourceDevice.objects.get(datasource=ds, external_device_id='ABC-001')
        assert dsd.virtual_device.status == Device.Status.ACTIVE
        assert dsd.virtual_device.tenant == tenant
        assert dsd.virtual_device.site == site

        # Serial number scheme
        assert dsd.virtual_device.serial_number.startswith('api-soilscouts-')

        # Streams created
        streams = Stream.objects.filter(device=dsd.virtual_device)
        assert streams.count() == 2
        assert set(streams.values_list('key', flat=True)) == {'soil_moisture', 'soil_temp'}

    def test_connect_bulk_devices(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)

        payload = [
            {
                'external_device_id': 'ABC-001',
                'site_id': site.pk,
                'active_stream_keys': ['soil_moisture'],
            },
            {
                'external_device_id': 'ABC-002',
                'site_id': site.pk,
                'active_stream_keys': ['soil_moisture'],
            },
        ]
        resp = auth_client(user).post(
            f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert len(resp.data) == 2
        assert DataSourceDevice.objects.filter(datasource=ds).count() == 2

    def test_stream_label_override(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)

        payload = [{
            'external_device_id': 'ABC-001',
            'site_id': site.pk,
            'active_stream_keys': ['soil_moisture'],
            'stream_overrides': {'soil_moisture': {'label': 'Custom Label', 'unit': 'vol%'}},
        }]
        auth_client(user).post(
            f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json',
        )
        stream = Stream.objects.get(device__serial_number__startswith='api-soilscouts-', key='soil_moisture')
        assert stream.label == 'Custom Label'
        assert stream.unit == 'vol%'

    def test_cannot_connect_already_connected_device(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)
        payload = [{'external_device_id': 'ABC-001', 'site_id': site.pk, 'active_stream_keys': ['soil_moisture']}]

        auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json')
        resp = auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json')
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_invalid_site_returns_400(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)

        payload = [{'external_device_id': 'ABC-001', 'site_id': 9999, 'active_stream_keys': ['soil_moisture']}]
        resp = auth_client(user).post(
            f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cross_tenant_cannot_connect_to_other_datasource(self):
        """Tenant B cannot post to Tenant A's data source."""
        tenant_a = make_tenant('Tenant A')
        tenant_b = make_tenant('Tenant B')
        user_b = make_tenant_user('b@b.com', tenant_b)
        provider = make_provider()
        ds_a = make_data_source(tenant_a, provider, 'A DS')
        site_b = make_site(tenant_b)

        payload = [{'external_device_id': 'ABC-001', 'site_id': site_b.pk, 'active_stream_keys': ['soil_moisture']}]
        resp = auth_client(user_b).post(
            f'{DATA_SOURCES_URL}{ds_a.pk}/devices/', payload, format='json',
        )
        # ds_a is not in tenant_b's queryset → 404
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Device deactivation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeactivateDevice:

    def _make_connected_device(self, tenant, ds, site):
        from apps.devices.models import DeviceType
        dt, _ = DeviceType.objects.get_or_create(
            slug='third-party-api',
            defaults={
                'name': '3rd Party API Device',
                'connection_type': 'api',
                'is_push': False,
                'default_offline_threshold_minutes': 30,
                'command_ack_timeout_seconds': 30,
            },
        )
        virtual_dev = Device.objects.create(
            tenant=tenant, site=site, device_type=dt,
            name='Scout', serial_number='api-soilscouts-1-DEV-001',
            status=Device.Status.ACTIVE,
        )
        return DataSourceDevice.objects.create(
            datasource=ds,
            external_device_id='DEV-001',
            virtual_device=virtual_dev,
            active_stream_keys=['soil_moisture'],
        )

    def test_deactivate_sets_is_active_false(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)
        dsd = self._make_connected_device(tenant, ds, site)

        resp = auth_client(user).delete(
            f'{DATA_SOURCES_URL}{ds.pk}/devices/{dsd.pk}/',
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        dsd.refresh_from_db()
        assert not dsd.is_active

    def test_deactivate_keeps_virtual_device_and_history(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)
        dsd = self._make_connected_device(tenant, ds, site)
        virtual_device_pk = dsd.virtual_device_id

        auth_client(user).delete(f'{DATA_SOURCES_URL}{ds.pk}/devices/{dsd.pk}/')

        # Virtual device still exists
        assert Device.objects.filter(pk=virtual_device_pk).exists()


# ---------------------------------------------------------------------------
# Polling task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPollSingleDevice:

    def _setup(self):
        """Create a minimal connected device for polling tests."""
        from apps.devices.models import DeviceType
        tenant = make_tenant()
        provider = make_provider()
        ds = DataSource.objects.create(
            tenant=tenant, provider=provider, name='DS',
            credentials={'X-API-Key': 'key'},
        )
        site = make_site(tenant)
        dt, _ = DeviceType.objects.get_or_create(
            slug='third-party-api',
            defaults={
                'name': '3rd Party API Device',
                'connection_type': 'api',
                'is_push': False,
                'default_offline_threshold_minutes': 30,
                'command_ack_timeout_seconds': 30,
            },
        )
        virtual_dev = Device.objects.create(
            tenant=tenant, site=site, device_type=dt,
            name='Scout', serial_number='api-soilscouts-1-D1',
            status=Device.Status.ACTIVE,
        )
        Stream.objects.create(
            device=virtual_dev, key='soil_moisture',
            label='Soil Moisture', unit='%', data_type='numeric',
        )
        dsd = DataSourceDevice.objects.create(
            datasource=ds,
            external_device_id='D1',
            virtual_device=virtual_dev,
            active_stream_keys=['soil_moisture'],
        )
        return dsd

    def test_poll_stores_stream_reading(self):
        from apps.integrations.tasks import poll_single_device
        dsd = self._setup()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {'soil_moisture': 42.5}
        mock_resp.raise_for_status.return_value = None

        with patch('apps.integrations.tasks.http_requests.request', return_value=mock_resp):
            poll_single_device(dsd.pk)

        assert StreamReading.objects.filter(stream__device=dsd.virtual_device).count() == 1
        reading = StreamReading.objects.get(stream__device=dsd.virtual_device)
        assert reading.value == 42.5

        dsd.refresh_from_db()
        assert dsd.last_poll_status == 'ok'
        assert dsd.consecutive_poll_failures == 0

    def test_poll_failure_increments_counter(self):
        import requests as req_lib

        from apps.integrations.tasks import poll_single_device
        dsd = self._setup()

        with patch('apps.integrations.tasks.http_requests.request',
                   side_effect=req_lib.RequestException('timeout')):
            poll_single_device(dsd.pk)

        dsd.refresh_from_db()
        assert dsd.last_poll_status == 'error'
        assert dsd.consecutive_poll_failures == 1

    def test_poll_health_warning_after_threshold(self):
        import requests as req_lib

        from apps.integrations.tasks import POLL_FAILURE_THRESHOLD, poll_single_device
        dsd = self._setup()
        dsd.consecutive_poll_failures = POLL_FAILURE_THRESHOLD - 1
        dsd.save()

        with patch('apps.integrations.tasks.http_requests.request',
                   side_effect=req_lib.RequestException('timeout')):
            poll_single_device(dsd.pk)

        dsd.refresh_from_db()
        assert dsd.consecutive_poll_failures == POLL_FAILURE_THRESHOLD
        health = DeviceHealth.objects.get(device=dsd.virtual_device)
        assert not health.is_online

    def test_successful_poll_resets_failure_count(self):
        from apps.integrations.tasks import poll_single_device
        dsd = self._setup()
        dsd.consecutive_poll_failures = 3
        dsd.save()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {'soil_moisture': 30.0}
        mock_resp.raise_for_status.return_value = None

        with patch('apps.integrations.tasks.http_requests.request', return_value=mock_resp):
            poll_single_device(dsd.pk)

        dsd.refresh_from_db()
        assert dsd.consecutive_poll_failures == 0
        assert dsd.last_poll_status == 'ok'
