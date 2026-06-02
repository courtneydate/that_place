"""Sprint 29a — 3rd-party API history / backfill.

Covers:
  - POST /api/v1/data-sources/:id/backfill/ validation, permissions, conflicts.
  - GET /api/v1/data-sources/:id/backfill/ list shape and permissions.
  - run_backfill_job idempotent dedup, multi-chunk walk, provider-supplied
    timestamps, failure paths, is_backfilling flag lifecycle.
  - poll_datasource_devices skips devices with is_backfilling=True.
  - reconcile_backfill_flags clears orphaned flags.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
     ROADMAP Sprint 29a
"""
from datetime import date, datetime
from datetime import timezone as dt_timezone
from unittest.mock import MagicMock, patch

import pytest
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.integrations.models import (
    DataSource,
    DataSourceBackfillJob,
    DataSourceDevice,
    ThirdPartyAPIProvider,
)
from apps.integrations.tasks import reconcile_backfill_flags, run_backfill_job
from apps.readings.models import Stream, StreamReading

# ---------------------------------------------------------------------------
# Helpers (kept self-contained; mirrors the patterns in test_datasources.py)
# ---------------------------------------------------------------------------


def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post(
        '/api/v1/auth/login/', {'email': user.email, 'password': password},
    )
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_provider(*, supports_history=True, slug='hist-prov'):
    """Provider with a history endpoint that returns list-of-rows responses."""
    return ThirdPartyAPIProvider.objects.create(
        name='HistProv',
        slug=slug,
        base_url='https://api.example.com',
        auth_type='api_key_header',
        auth_param_schema=[
            {'key': 'X-API-Key', 'label': 'API Key', 'type': 'password', 'required': True},
        ],
        discovery_endpoint={'path': '/devices/', 'method': 'GET',
                            'device_id_jsonpath': '$.devices[*].id'},
        detail_endpoint={
            'path_template': '/devices/{device_id}/current/',
            'method': 'GET',
        },
        available_streams=[
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C',
             'data_type': 'numeric', 'jsonpath': '$.temp'},
            {'key': 'humidity', 'label': 'Humidity', 'unit': '%',
             'data_type': 'numeric', 'jsonpath': '$.humidity'},
        ],
        supports_history=supports_history,
        history_endpoint={
            'path_template': '/devices/{device_id}/history/',
            'method': 'GET',
            'params': {'from': '{from_iso}', 'to': '{to_iso}'},
            'response_root_jsonpath': '$.readings[*]',
            'timestamp_jsonpath': '$.ts',
        },
        history_chunk_days=2,
    )


def make_data_source(tenant, provider):
    return DataSource.objects.create(
        tenant=tenant, provider=provider, name='ds',
        credentials={'X-API-Key': 'key'},
    )


def make_dsd(ds, site, *, ext_id='dev-1', stream_keys=('temp', 'humidity')):
    """Create a DataSourceDevice with a virtual Device + the named Streams."""
    device_type, _ = DeviceType.objects.get_or_create(
        slug='third-party-api',
        defaults={
            'name': '3rd Party API Device',
            'description': '',
            'connection_type': DeviceType.ConnectionType.API,
            'is_push': False,
            'default_offline_threshold_minutes': 30,
            'command_ack_timeout_seconds': 30,
        },
    )
    vdev = Device.objects.create(
        tenant=ds.tenant,
        site=site,
        device_type=device_type,
        name=f'V-{ext_id}',
        serial_number=f'api-{ds.provider.slug}-{ds.tenant_id}-{ext_id}',
        status=Device.Status.ACTIVE,
    )
    for key in stream_keys:
        Stream.objects.create(
            device=vdev, key=key, label=key.title(),
            unit='', data_type='numeric',
        )
    return DataSourceDevice.objects.create(
        datasource=ds,
        external_device_id=ext_id,
        virtual_device=vdev,
        active_stream_keys=list(stream_keys),
        is_active=True,
    )


def make_history_response(rows):
    """Return a MagicMock requests.Response for a history page."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={'readings': rows})
    return resp


# ---------------------------------------------------------------------------
# Endpoint: POST /api/v1/data-sources/:id/backfill/
# ---------------------------------------------------------------------------

BACKFILL_URL = '/api/v1/data-sources/{}/backfill/'


@pytest.mark.django_db
class TestBackfillEndpointPOST:

    def test_admin_dispatches_job(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        client = auth_client(admin)

        with patch('apps.integrations.tasks.run_backfill_job.delay') as mock_dispatch:
            resp = client.post(
                BACKFILL_URL.format(ds.pk),
                {'date_from': '2026-05-01', 'date_to': '2026-05-07'},
                format='json',
            )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        job = DataSourceBackfillJob.objects.get(pk=resp.data['id'])
        assert job.datasource_id == ds.pk
        assert job.status == DataSourceBackfillJob.Status.QUEUED
        assert job.created_by_id == admin.pk
        mock_dispatch.assert_called_once_with(job.pk)

    def test_provider_without_supports_history_rejected(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        provider = make_provider(supports_history=False)
        ds = make_data_source(tenant, provider)
        client = auth_client(admin)
        resp = client.post(
            BACKFILL_URL.format(ds.pk),
            {'date_from': '2026-05-01', 'date_to': '2026-05-07'},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'history_not_supported'

    def test_date_range_over_365_days_rejected(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        ds = make_data_source(tenant, make_provider())
        client = auth_client(admin)
        resp = client.post(
            BACKFILL_URL.format(ds.pk),
            {'date_from': '2024-01-01', 'date_to': '2025-12-31'},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'date_to' in resp.data['error']['details']

    def test_date_from_after_date_to_rejected(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        ds = make_data_source(tenant, make_provider())
        client = auth_client(admin)
        resp = client.post(
            BACKFILL_URL.format(ds.pk),
            {'date_from': '2026-05-10', 'date_to': '2026-05-01'},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_in_flight_job_rejected(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        ds = make_data_source(tenant, make_provider())
        DataSourceBackfillJob.objects.create(
            datasource=ds,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 7),
            status=DataSourceBackfillJob.Status.RUNNING,
        )
        client = auth_client(admin)
        resp = client.post(
            BACKFILL_URL.format(ds.pk),
            {'date_from': '2026-05-01', 'date_to': '2026-05-07'},
            format='json',
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data['error']['code'] == 'backfill_in_progress'

    def test_completed_job_does_not_block_new_one(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        ds = make_data_source(tenant, make_provider())
        DataSourceBackfillJob.objects.create(
            datasource=ds,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 7),
            status=DataSourceBackfillJob.Status.COMPLETED,
        )
        client = auth_client(admin)
        with patch('apps.integrations.tasks.run_backfill_job.delay'):
            resp = client.post(
                BACKFILL_URL.format(ds.pk),
                {'date_from': '2026-05-01', 'date_to': '2026-05-07'},
                format='json',
            )
        assert resp.status_code == status.HTTP_202_ACCEPTED

    def test_view_only_blocked_from_post(self):
        tenant = make_tenant()
        viewer = make_user('v@x', tenant, role=TenantUser.Role.VIEWER)
        ds = make_data_source(tenant, make_provider())
        client = auth_client(viewer)
        resp = client.post(
            BACKFILL_URL.format(ds.pk),
            {'date_from': '2026-05-01', 'date_to': '2026-05-07'},
            format='json',
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_b = make_user('b@x', tenant_b)
        ds_a = make_data_source(tenant_a, make_provider())
        client = auth_client(admin_b)
        resp = client.post(
            BACKFILL_URL.format(ds_a.pk),
            {'date_from': '2026-05-01', 'date_to': '2026-05-07'},
            format='json',
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Endpoint: GET /api/v1/data-sources/:id/backfill/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBackfillEndpointGET:

    def test_admin_can_list_jobs_newest_first(self):
        tenant = make_tenant()
        admin = make_user('a@x', tenant)
        ds = make_data_source(tenant, make_provider())
        DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 1, 1), date_to=date(2026, 1, 7),
            status=DataSourceBackfillJob.Status.COMPLETED,
        )
        DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 2, 1), date_to=date(2026, 2, 7),
            status=DataSourceBackfillJob.Status.COMPLETED,
        )
        client = auth_client(admin)
        resp = client.get(BACKFILL_URL.format(ds.pk))
        assert resp.status_code == 200
        # newest first
        assert resp.data[0]['date_from'] == '2026-02-01'

    def test_view_only_can_list(self):
        tenant = make_tenant()
        viewer = make_user('v@x', tenant, role=TenantUser.Role.VIEWER)
        ds = make_data_source(tenant, make_provider())
        client = auth_client(viewer)
        resp = client.get(BACKFILL_URL.format(ds.pk))
        assert resp.status_code == 200

    def test_cross_tenant_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_b = make_user('b@x', tenant_b)
        ds_a = make_data_source(tenant_a, make_provider())
        client = auth_client(admin_b)
        resp = client.get(BACKFILL_URL.format(ds_a.pk))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# run_backfill_job — task behaviour
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRunBackfillJob:

    def _make_ready(self):
        """Common setup: tenant, provider, ds, site, one device with two streams."""
        tenant = make_tenant()
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = Site.objects.create(tenant=tenant, name='Site')
        dsd = make_dsd(ds, site)
        return tenant, provider, ds, site, dsd

    def test_chunks_walked_and_readings_stored(self):
        tenant, provider, ds, site, dsd = self._make_ready()
        # 5-day window with chunk_days=2 → 3 chunks (2+2+1 days).
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 5),
        )
        # Each chunk returns 2 rows, 2 streams per row → 4 readings/chunk.
        ts_counter = [0]

        def page(_):
            ts_counter[0] += 1
            rows = [
                {'ts': f'2026-05-{ts_counter[0]:02d}T00:00:00Z', 'temp': 20.0, 'humidity': 50.0},
                {'ts': f'2026-05-{ts_counter[0]:02d}T01:00:00Z', 'temp': 21.0, 'humidity': 51.0},
            ]
            return make_history_response(rows)

        with patch(
            'apps.integrations.tasks.http_requests.request',
            side_effect=lambda *a, **kw: page(None),
        ) as mock_req:
            run_backfill_job(job.pk)

        # 3 chunks → 3 HTTP calls
        assert mock_req.call_count == 3
        job.refresh_from_db()
        assert job.status == DataSourceBackfillJob.Status.COMPLETED
        assert job.rows_fetched == 6   # 3 chunks × 2 rows
        assert job.rows_stored == 12   # 6 rows × 2 streams
        assert StreamReading.objects.count() == 12
        dsd.refresh_from_db()
        assert dsd.is_backfilling is False

    def test_rerun_is_idempotent_no_duplicates(self):
        tenant, provider, ds, site, dsd = self._make_ready()
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )
        rows = [
            {'ts': '2026-05-01T00:00:00Z', 'temp': 20.0, 'humidity': 50.0},
        ]
        with patch(
            'apps.integrations.tasks.http_requests.request',
            return_value=make_history_response(rows),
        ):
            run_backfill_job(job.pk)
        first = StreamReading.objects.count()
        assert first == 2

        # Re-run on a fresh job over the same window — same data returned.
        job2 = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )
        with patch(
            'apps.integrations.tasks.http_requests.request',
            return_value=make_history_response(rows),
        ):
            run_backfill_job(job2.pk)

        assert StreamReading.objects.count() == 2  # no duplicates
        job2.refresh_from_db()
        assert job2.status == DataSourceBackfillJob.Status.COMPLETED
        assert job2.rows_stored == 0  # all deduped

    def test_provider_supplied_timestamp_used(self):
        tenant, provider, ds, site, dsd = self._make_ready()
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )
        rows = [
            {'ts': '2026-05-01T03:45:12Z', 'temp': 19.5, 'humidity': 60.0},
        ]
        with patch(
            'apps.integrations.tasks.http_requests.request',
            return_value=make_history_response(rows),
        ):
            run_backfill_job(job.pk)
        reading = StreamReading.objects.get(stream__key='temp')
        assert reading.timestamp == datetime(
            2026, 5, 1, 3, 45, 12, tzinfo=dt_timezone.utc,
        )
        assert reading.value == 19.5

    def test_unix_timestamp_parsed(self):
        tenant, provider, ds, site, dsd = self._make_ready()
        # 2026-05-01 06:00:00 UTC = 1777874400
        unix_ts = int(datetime(2026, 5, 1, 6, 0, 0, tzinfo=dt_timezone.utc).timestamp())
        rows = [{'ts': unix_ts, 'temp': 22.2, 'humidity': 55.0}]
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )
        with patch(
            'apps.integrations.tasks.http_requests.request',
            return_value=make_history_response(rows),
        ):
            run_backfill_job(job.pk)
        reading = StreamReading.objects.get(stream__key='temp')
        assert reading.timestamp == datetime(
            2026, 5, 1, 6, 0, 0, tzinfo=dt_timezone.utc,
        )

    def test_is_backfilling_set_then_cleared(self):
        tenant, provider, ds, site, dsd = self._make_ready()
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )

        observed = []

        def capture_then_respond(*args, **kwargs):
            dsd.refresh_from_db()
            observed.append(dsd.is_backfilling)
            return make_history_response([
                {'ts': '2026-05-01T00:00:00Z', 'temp': 20.0, 'humidity': 50.0},
            ])

        with patch(
            'apps.integrations.tasks.http_requests.request',
            side_effect=capture_then_respond,
        ):
            run_backfill_job(job.pk)

        assert observed == [True]
        dsd.refresh_from_db()
        assert dsd.is_backfilling is False

    def test_http_failure_marks_job_failed_and_clears_flag(self):
        import requests as http_requests
        tenant, provider, ds, site, dsd = self._make_ready()
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )
        with patch(
            'apps.integrations.tasks.http_requests.request',
            side_effect=http_requests.ConnectionError('refused'),
        ):
            run_backfill_job(job.pk)
        job.refresh_from_db()
        assert job.status == DataSourceBackfillJob.Status.FAILED
        assert 'refused' in job.error_detail
        dsd.refresh_from_db()
        assert dsd.is_backfilling is False

    def test_provider_without_supports_history_fails_job(self):
        tenant = make_tenant()
        provider = make_provider(supports_history=False)
        ds = make_data_source(tenant, provider)
        site = Site.objects.create(tenant=tenant, name='Site')
        make_dsd(ds, site)
        job = DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 1),
        )
        run_backfill_job(job.pk)
        job.refresh_from_db()
        assert job.status == DataSourceBackfillJob.Status.FAILED
        assert 'does not support' in job.error_detail


# ---------------------------------------------------------------------------
# Live-poll exclusion
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLivePollSkipsBackfilling:

    def test_backfilling_device_excluded_from_due_list(self):
        from apps.integrations.tasks import poll_datasource_devices
        tenant = make_tenant()
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = Site.objects.create(tenant=tenant, name='Site')
        dsd = make_dsd(ds, site)
        dsd.is_backfilling = True
        dsd.save(update_fields=['is_backfilling'])

        with patch(
            'apps.integrations.tasks.poll_single_device.apply_async',
        ) as mock_dispatch:
            poll_datasource_devices()
        mock_dispatch.assert_not_called()

    def test_non_backfilling_device_still_polled(self):
        from apps.integrations.tasks import poll_datasource_devices
        tenant = make_tenant()
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = Site.objects.create(tenant=tenant, name='Site')
        make_dsd(ds, site)

        with patch(
            'apps.integrations.tasks.poll_single_device.apply_async',
        ) as mock_dispatch:
            poll_datasource_devices()
        assert mock_dispatch.called


# ---------------------------------------------------------------------------
# Janitor — reconcile_backfill_flags
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReconcileBackfillFlags:

    def test_clears_orphan_flag(self):
        tenant = make_tenant()
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = Site.objects.create(tenant=tenant, name='Site')
        dsd = make_dsd(ds, site)
        dsd.is_backfilling = True
        dsd.save(update_fields=['is_backfilling'])
        # No live job exists.
        reconcile_backfill_flags()
        dsd.refresh_from_db()
        assert dsd.is_backfilling is False

    def test_leaves_flag_when_job_is_running(self):
        tenant = make_tenant()
        provider = make_provider()
        ds = make_data_source(tenant, provider)
        site = Site.objects.create(tenant=tenant, name='Site')
        dsd = make_dsd(ds, site)
        dsd.is_backfilling = True
        dsd.save(update_fields=['is_backfilling'])
        DataSourceBackfillJob.objects.create(
            datasource=ds, date_from=date(2026, 5, 1), date_to=date(2026, 5, 7),
            status=DataSourceBackfillJob.Status.RUNNING,
        )
        reconcile_backfill_flags()
        dsd.refresh_from_db()
        assert dsd.is_backfilling is True
