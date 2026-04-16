"""Cross-tenant isolation tests for Celery beat tasks in the integrations app.

Verifies that poll_single_device writes StreamReadings only to the virtual
device belonging to the polled DataSource's tenant, and does not affect
any other tenant's data.

Ref: security_risks.md § SR-03 — Tenant Isolation in Celery Beat Tasks
"""
from unittest.mock import MagicMock, patch

import pytest
from django.utils.text import slugify

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceType, Site
from apps.integrations.models import DataSource, DataSourceDevice, ThirdPartyAPIProvider
from apps.readings.models import Stream, StreamReading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_provider() -> ThirdPartyAPIProvider:
    return ThirdPartyAPIProvider.objects.create(
        name='Isolation Provider',
        slug='iso-provider',
        base_url='https://api.iso-provider.example.com',
        auth_type='api_key_header',
        auth_param_schema=[
            {'key': 'X-API-Key', 'label': 'API Key', 'type': 'password', 'required': True},
        ],
        discovery_endpoint={
            'path': '/devices/',
            'method': 'GET',
            'device_id_jsonpath': '$.results[*].id',
        },
        detail_endpoint={
            'path_template': '/devices/{device_id}/readings/',
            'method': 'GET',
        },
        available_streams=[
            {
                'key': 'temperature',
                'label': 'Temperature',
                'unit': '°C',
                'data_type': 'numeric',
                'jsonpath': '$.temperature',
            },
        ],
        default_poll_interval_seconds=300,
    )


def _make_api_device_type() -> DeviceType:
    dt, _ = DeviceType.objects.get_or_create(
        slug='third-party-api',
        defaults={
            'name': '3rd Party API Device',
            'connection_type': DeviceType.ConnectionType.API,
            'is_push': False,
            'default_offline_threshold_minutes': 30,
            'command_ack_timeout_seconds': 30,
        },
    )
    return dt


def make_connected_device(tenant: Tenant, provider: ThirdPartyAPIProvider, serial_suffix: str):
    """Create a DataSource + DataSourceDevice + virtual Device + Stream for a tenant."""
    site = Site.objects.create(tenant=tenant, name=f'Site {serial_suffix}')
    ds = DataSource.objects.create(
        tenant=tenant,
        provider=provider,
        name=f'DS {serial_suffix}',
        credentials={'X-API-Key': f'key-{serial_suffix}'},
    )
    dt = _make_api_device_type()
    virtual_dev = Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=dt,
        name=f'Device {serial_suffix}',
        serial_number=f'api-iso-provider-{serial_suffix}',
        status=Device.Status.ACTIVE,
    )
    Stream.objects.create(
        device=virtual_dev,
        key='temperature',
        label='Temperature',
        unit='°C',
        data_type='numeric',
    )
    dsd = DataSourceDevice.objects.create(
        datasource=ds,
        external_device_id=f'EXT-{serial_suffix}',
        virtual_device=virtual_dev,
        active_stream_keys=['temperature'],
    )
    return dsd


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPollSingleDeviceCrossTenant:
    """poll_single_device must only write StreamReadings for its own tenant's device."""

    def _mock_response(self, temperature: float = 22.5):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'temperature': temperature}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_readings_written_only_to_polled_tenant_device(self):
        """Polling Tenant A's device must not create readings on Tenant B's device."""
        from apps.integrations.tasks import poll_single_device

        tenant_a = make_tenant('PollIsoA')
        tenant_b = make_tenant('PollIsoB')
        provider = make_provider()

        dsd_a = make_connected_device(tenant_a, provider, '001')
        dsd_b = make_connected_device(tenant_b, provider, '002')

        with patch('apps.integrations.tasks.http_requests.request',
                   return_value=self._mock_response(22.5)):
            poll_single_device(dsd_a.pk)

        # Tenant A has exactly one reading
        readings_a = StreamReading.objects.filter(stream__device=dsd_a.virtual_device)
        assert readings_a.count() == 1
        assert readings_a.first().value == 22.5

        # Tenant B has no readings
        readings_b = StreamReading.objects.filter(stream__device=dsd_b.virtual_device)
        assert readings_b.count() == 0

    def test_poll_status_only_updated_for_polled_datasource(self):
        """last_polled_at and last_poll_status must only be updated for the polled DSD."""
        from apps.integrations.tasks import poll_single_device

        tenant_a = make_tenant('StatusIsoA')
        tenant_b = make_tenant('StatusIsoB')
        provider = make_provider()

        dsd_a = make_connected_device(tenant_a, provider, '003')
        dsd_b = make_connected_device(tenant_b, provider, '004')

        assert dsd_b.last_polled_at is None

        with patch('apps.integrations.tasks.http_requests.request',
                   return_value=self._mock_response()):
            poll_single_device(dsd_a.pk)

        dsd_a.refresh_from_db()
        dsd_b.refresh_from_db()

        assert dsd_a.last_polled_at is not None
        assert dsd_a.last_poll_status == DataSourceDevice.PollStatus.OK

        # Tenant B's DSD must be completely untouched
        assert dsd_b.last_polled_at is None
        assert dsd_b.last_poll_status is None

    def test_failure_on_tenant_a_does_not_affect_tenant_b(self):
        """A failed poll for Tenant A's device must not mark Tenant B's device as failed."""
        import requests as req_lib

        from apps.integrations.tasks import poll_single_device

        tenant_a = make_tenant('FailIsoA')
        tenant_b = make_tenant('FailIsoB')
        provider = make_provider()

        dsd_a = make_connected_device(tenant_a, provider, '005')
        dsd_b = make_connected_device(tenant_b, provider, '006')

        with patch('apps.integrations.tasks.http_requests.request',
                   side_effect=req_lib.RequestException('timeout')):
            poll_single_device(dsd_a.pk)

        dsd_a.refresh_from_db()
        dsd_b.refresh_from_db()

        assert dsd_a.last_poll_status == DataSourceDevice.PollStatus.ERROR
        assert dsd_a.consecutive_poll_failures == 1

        # Tenant B untouched
        assert dsd_b.last_poll_status is None
        assert dsd_b.consecutive_poll_failures == 0
