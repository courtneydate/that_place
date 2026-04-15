"""Tests for DataSource CRUD, device discovery, and device connection.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
     security_risks.md § SR-02 — Third-Party API Credential Storage
"""
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection
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


def make_fm_admin(email='fm@that-place.io', password='testpass123'):
    return User.objects.create_user(email=email, password=password, is_that_place_admin=True)


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
        from apps.integrations.models import DataSource
        provider = DataSource.objects.get(pk=ds.pk).provider
        serial = f'api-{provider.slug}-{tenant.pk}-DEV-001'[:255]
        virtual_dev = Device.objects.create(
            tenant=tenant, site=site, device_type=dt,
            name='Scout', serial_number=serial,
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

    def test_reconnect_reactivates_existing_device(self):
        """Re-connecting a previously deactivated device reactivates it instead of creating a duplicate."""
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = make_site(tenant)
        dsd = self._make_connected_device(tenant, ds, site)
        virtual_device_pk = dsd.virtual_device_id

        # Deactivate
        auth_client(user).delete(f'{DATA_SOURCES_URL}{ds.pk}/devices/{dsd.pk}/')
        dsd.refresh_from_db()
        assert not dsd.is_active

        # Re-connect the same external device — must not 500 or create a duplicate Device
        payload = [{'external_device_id': 'DEV-001', 'site_id': site.pk, 'active_stream_keys': ['soil_moisture']}]
        resp = auth_client(user).post(f'{DATA_SOURCES_URL}{ds.pk}/devices/', payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED

        # Same virtual Device reused, not a new one
        dsd.refresh_from_db()
        assert dsd.is_active
        assert dsd.virtual_device_id == virtual_device_pk
        assert Device.objects.filter(tenant=tenant).count() == 1


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


# ---------------------------------------------------------------------------
# SR-02 — Credential encryption at rest
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCredentialEncryptionAtRest:
    """Verify that credential and token fields are stored as ciphertext.

    These tests query the raw database column value and assert the plaintext
    credential value is not visible. The decrypted value must round-trip
    correctly through the ORM.

    Ref: security_risks.md § SR-02 — Third-Party API Credential Storage
    """

    PLAINTEXT_KEY = 'super-secret-api-key-12345'

    def _make_datasource(self):
        tenant = make_tenant('EncTest')
        provider = make_provider()
        return DataSource.objects.create(
            tenant=tenant,
            provider=provider,
            name='Enc DS',
            credentials={'X-API-Key': self.PLAINTEXT_KEY},
        )

    def _raw_column(self, table: str, pk: int, column: str) -> str:
        """Return the raw bytes stored in a column, as a string."""
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT {column} FROM {table} WHERE id = %s', [pk])
            row = cursor.fetchone()
        return str(row[0]) if row else ''

    def test_credentials_not_plaintext_in_db(self):
        """The credentials column must not contain the raw API key."""
        ds = self._make_datasource()
        raw = self._raw_column('integrations_datasource', ds.pk, 'credentials')
        assert self.PLAINTEXT_KEY not in raw

    def test_credentials_round_trip(self):
        """ORM must decrypt credentials back to the original dict."""
        ds = self._make_datasource()
        ds.refresh_from_db()
        assert ds.credentials == {'X-API-Key': self.PLAINTEXT_KEY}

    def test_auth_token_cache_not_plaintext_in_db(self):
        """The auth_token_cache column must not contain plaintext tokens."""
        plaintext_token = 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-payload'
        tenant = make_tenant('TokTest')
        provider = make_provider('TokProv', slug='tok-prov')
        ds = DataSource.objects.create(
            tenant=tenant,
            provider=provider,
            name='Tok DS',
            credentials={'X-API-Key': 'key'},
            auth_token_cache={'access_token': plaintext_token, 'expires_at': 9999999999},
        )
        raw = self._raw_column('integrations_datasource', ds.pk, 'auth_token_cache')
        assert plaintext_token not in raw

    def test_auth_token_cache_round_trip(self):
        """ORM must decrypt auth_token_cache back to the original dict."""
        cache = {'access_token': 'tok-abc', 'expires_at': 9999999999}
        tenant = make_tenant('TokRT')
        provider = make_provider('TokRT', slug='tok-rt')
        ds = DataSource.objects.create(
            tenant=tenant,
            provider=provider,
            name='DS',
            credentials={},
            auth_token_cache=cache,
        )
        ds.refresh_from_db()
        assert ds.auth_token_cache['access_token'] == 'tok-abc'

    def test_credentials_absent_from_api_response(self):
        """credentials must never appear in GET or POST API responses (write-only)."""
        ds = self._make_datasource()
        user = make_tenant_user('enc@acme.com', ds.tenant)
        client = auth_client(user)

        get_resp = client.get(f'{DATA_SOURCES_URL}{ds.pk}/')
        assert 'credentials' not in get_resp.data

        list_resp = client.get(DATA_SOURCES_URL)
        for item in list_resp.data:
            assert 'credentials' not in item

    def test_credentials_absent_from_create_response(self):
        """credentials must not be echoed back in the 201 response."""
        tenant = make_tenant('CrRT')
        user = make_tenant_user('cr@acme.com', tenant)
        provider = make_provider('CrProv', slug='cr-prov')
        payload = {
            'provider': provider.pk,
            'name': 'New DS',
            'credentials': {'X-API-Key': self.PLAINTEXT_KEY},
        }
        resp = auth_client(user).post(DATA_SOURCES_URL, payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert 'credentials' not in resp.data
