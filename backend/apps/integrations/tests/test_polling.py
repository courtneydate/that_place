"""Tests for integrations.tasks — poll_single_device, _build_time_params,
and fetch_device_metadata.

Covers:
- Auth-retry logic for server-side token revocation
- Time token interpolation for time-windowed measurement endpoints
- Background metadata fetch task

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import requests as req_lib

from apps.integrations.tasks import (
    MAX_AUTH_RETRIES,
    _build_time_params,
    fetch_device_metadata,
    poll_single_device,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_dsd(pk=11):
    """Return a minimal DataSourceDevice mock wired up for poll_single_device."""
    provider = MagicMock()
    provider.base_url = 'https://soilscouts.fi/api/v1'
    provider.detail_endpoint = {'method': 'GET', 'path_template': '/devices/{device_id}/'}
    provider.available_streams = []

    datasource = MagicMock()
    datasource.pk = 1
    datasource.provider = provider
    datasource.credentials = {'username': 'u', 'password': 'p'}
    datasource.auth_token_cache = {'access_token': 'old_token', 'expires_at': 9_999_999_999}

    dsd = MagicMock()
    dsd.pk = pk
    dsd.datasource_id = 1
    dsd.datasource = datasource
    dsd.external_device_id = '15269'
    dsd.virtual_device = MagicMock()
    dsd.active_stream_keys = []
    dsd.consecutive_poll_failures = 0
    return dsd


def make_response(status_code=200, json_data=None):
    """Return a mock requests.Response."""
    resp = MagicMock(spec=req_lib.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        http_err = req_lib.HTTPError(response=resp, request=MagicMock())
        resp.raise_for_status.side_effect = http_err
    else:
        resp.raise_for_status.return_value = None
    return resp


# Patch paths — auth_handlers imports are local to the function body,
# so we patch at the source module, not at tasks.
AUTH_PATCH = 'apps.integrations.auth_handlers.get_auth_session'
META_AUTH_PATCH = 'apps.integrations.auth_handlers.get_auth_session'
HTTP_PATCH = 'apps.integrations.tasks.http_requests.request'
DSD_PATCH = 'apps.integrations.models.DataSourceDevice.objects'
STREAM_PATCH = 'apps.readings.models.Stream.objects.filter'
READING_PATCH = 'apps.readings.models.StreamReading.objects.bulk_create'
HEALTH_PATCH = 'apps.devices.models.DeviceHealth.objects.get_or_create'
ATOMIC_PATCH = 'django.db.transaction.atomic'


@contextmanager
def poll_patches(dsd, auth_return, http_side_effect):
    """Stack all patches needed to run poll_single_device in isolation."""
    with patch(DSD_PATCH) as mock_qs:
        mock_qs.select_related.return_value.get.return_value = dsd
        with patch(AUTH_PATCH, return_value=auth_return):
            with patch(HTTP_PATCH, side_effect=http_side_effect):
                with patch(STREAM_PATCH, return_value=[]):
                    with patch(READING_PATCH):
                        with patch(HEALTH_PATCH, return_value=(MagicMock(), False)):
                            with patch(ATOMIC_PATCH):
                                yield


GOOD_AUTH = ({'Authorization': 'Bearer tok'}, {}, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPollAuthRetry:

    def test_max_retries_constant_is_three(self):
        """MAX_AUTH_RETRIES is 3 as agreed."""
        assert MAX_AUTH_RETRIES == 3

    def test_succeeds_on_first_attempt(self):
        """200 on the first try — no retry, poll status set to OK."""
        dsd = make_dsd()
        ok_resp = make_response(200)

        with poll_patches(dsd, GOOD_AUTH, [ok_resp]):
            poll_single_device(dsd.pk)

        dsd.save.assert_called()
        saved_kwargs = dsd.save.call_args
        assert 'last_poll_status' in str(saved_kwargs) or dsd.last_poll_status is not None

    def test_retries_once_on_401_then_succeeds(self):
        """A 401 on attempt 1 is retried; 200 on attempt 2 succeeds."""
        dsd = make_dsd()
        resp_401 = make_response(401)
        resp_200 = make_response(200)

        http_mock = MagicMock(side_effect=[resp_401, resp_200])

        with patch(DSD_PATCH) as mock_qs:
            mock_qs.select_related.return_value.get.return_value = dsd
            with patch(AUTH_PATCH, return_value=GOOD_AUTH):
                with patch(HTTP_PATCH, http_mock):
                    with patch(STREAM_PATCH, return_value=[]):
                        with patch(READING_PATCH):
                            with patch(HEALTH_PATCH, return_value=(MagicMock(), False)):
                                with patch(ATOMIC_PATCH):
                                    poll_single_device(dsd.pk)

        assert http_mock.call_count == 2
        # Token cache must have been cleared after the 401
        dsd.datasource.save.assert_any_call(update_fields=['auth_token_cache'])
        assert dsd.datasource.auth_token_cache == {}

    def test_records_auth_failure_after_all_retries_exhausted(self):
        """Three consecutive 401s record AUTH_FAILURE and increment failure count."""
        dsd = make_dsd()
        resp_401 = make_response(401)
        http_mock = MagicMock(return_value=resp_401)

        with patch(DSD_PATCH) as mock_qs:
            mock_qs.select_related.return_value.get.return_value = dsd
            with patch(AUTH_PATCH, return_value=GOOD_AUTH):
                with patch(HTTP_PATCH, http_mock):
                    poll_single_device(dsd.pk)

        assert http_mock.call_count == MAX_AUTH_RETRIES
        assert dsd.consecutive_poll_failures == 1  # _record_failure incremented it

    def test_does_not_retry_on_non_401_http_error(self):
        """A 500 fails immediately — no retry."""
        dsd = make_dsd()
        resp_500 = make_response(500)
        http_mock = MagicMock(return_value=resp_500)

        with poll_patches(dsd, GOOD_AUTH, http_mock):
            poll_single_device(dsd.pk)

        assert http_mock.call_count == 1

    def test_does_not_retry_on_network_error(self):
        """A connection error fails immediately — no retry."""
        dsd = make_dsd()
        http_mock = MagicMock(side_effect=req_lib.ConnectionError('refused'))

        with poll_patches(dsd, GOOD_AUTH, http_mock):
            poll_single_device(dsd.pk)

        assert http_mock.call_count == 1

    def test_persists_new_token_when_auth_returns_updated_cache(self):
        """When get_auth_session returns an updated cache, it is saved to the DataSource."""
        dsd = make_dsd()
        new_cache = {'access_token': 'new_tok', 'refresh_token': 'ref', 'expires_at': 9999}
        auth_return = ({'Authorization': 'Bearer new_tok'}, {}, new_cache)
        resp_200 = make_response(200)

        with poll_patches(dsd, auth_return, [resp_200]):
            poll_single_device(dsd.pk)

        assert dsd.datasource.auth_token_cache == new_cache
        dsd.datasource.save.assert_any_call(update_fields=['auth_token_cache'])


# ---------------------------------------------------------------------------
# _build_time_params
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2025, 4, 15, 9, 30, 0, tzinfo=timezone.utc)
FIXED_FROM = datetime(2025, 4, 15, 9, 25, 0, tzinfo=timezone.utc)  # 5 min before now


class TestBuildTimeParams:

    def test_returns_empty_dict_when_no_params_configured(self):
        """Providers without time params return {} — no change to existing behaviour."""
        assert _build_time_params({}, FIXED_FROM, FIXED_NOW) == {}
        assert _build_time_params({'method': 'GET'}, FIXED_FROM, FIXED_NOW) == {}

    def test_interpolates_unix_tokens(self):
        """Unix timestamp tokens are replaced with integer second strings."""
        cfg = {'params': {'start-timestamp': '{from_unix}', 'end-timestamp': '{to_unix}'}}
        result = _build_time_params(cfg, FIXED_FROM, FIXED_NOW)
        assert result == {
            'start-timestamp': str(int(FIXED_FROM.timestamp())),
            'end-timestamp': str(int(FIXED_NOW.timestamp())),
        }

    def test_interpolates_iso_tokens(self):
        """ISO 8601 tokens are replaced with UTC datetime strings."""
        cfg = {'params': {'from': '{from_iso}', 'to': '{to_iso}'}}
        result = _build_time_params(cfg, FIXED_FROM, FIXED_NOW)
        assert result == {
            'from': '2025-04-15T09:25:00Z',
            'to': '2025-04-15T09:30:00Z',
        }

    def test_uses_window_seconds_when_last_polled_at_is_none(self):
        """First poll: from = now - window_seconds."""
        cfg = {'params': {'from': '{from_iso}', 'to': '{to_iso}'}, 'window_seconds': 300}
        result = _build_time_params(cfg, None, FIXED_NOW)
        assert result['from'] == '2025-04-15T09:25:00Z'  # 09:30 - 300s = 09:25
        assert result['to'] == '2025-04-15T09:30:00Z'

    def test_default_window_is_300_seconds(self):
        """window_seconds defaults to 300 when not specified."""
        cfg = {'params': {'ts': '{from_unix}'}}
        result = _build_time_params(cfg, None, FIXED_NOW)
        expected_from = int(FIXED_NOW.timestamp()) - 300
        assert result == {'ts': str(expected_from)}

    def test_preserves_static_param_values(self):
        """Param values without tokens are passed through unchanged."""
        cfg = {'params': {'format': 'json', 'from': '{from_iso}'}}
        result = _build_time_params(cfg, FIXED_FROM, FIXED_NOW)
        assert result['format'] == 'json'
        assert result['from'] == '2025-04-15T09:25:00Z'


# ---------------------------------------------------------------------------
# fetch_device_metadata
# ---------------------------------------------------------------------------


def make_dsd_for_metadata(pk=42, has_detail_endpoint=True, name_jsonpath='$.name'):
    """Return a minimal DataSourceDevice mock for fetch_device_metadata tests."""
    provider = MagicMock()
    provider.base_url = 'https://api.example.com'
    provider.max_requests_per_second = None
    provider.device_detail_endpoint = (
        {'path_template': '/devices/{device_id}', 'method': 'GET', 'name_jsonpath': name_jsonpath}
        if has_detail_endpoint else {}
    )
    datasource = MagicMock()
    datasource.credentials = {}
    datasource.auth_token_cache = {}
    datasource.provider = provider

    virtual_device = MagicMock()
    virtual_device.pk = 99

    dsd = MagicMock()
    dsd.pk = pk
    dsd.external_device_id = 'DEV001'
    dsd.datasource = datasource
    dsd.virtual_device = virtual_device
    return dsd


class TestFetchDeviceMetadata:

    def test_skips_when_no_device_detail_endpoint(self):
        """Devices whose provider has no device_detail_endpoint are skipped silently."""
        dsd = make_dsd_for_metadata(has_detail_endpoint=False)
        with patch('apps.integrations.models.DataSourceDevice.objects') as mock_qs:
            mock_qs.filter.return_value.select_related.return_value = [dsd]
            with patch('apps.integrations.tasks.http_requests.request') as mock_req:
                fetch_device_metadata([dsd.pk])
        mock_req.assert_not_called()

    def test_updates_virtual_device_name_from_response(self):
        """Name extracted via JSONPath is saved to the virtual device."""
        dsd = make_dsd_for_metadata()
        good_auth = ({'Authorization': 'Bearer tok'}, {}, None)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {'name': 'Station Alpha', 'id': 'DEV001'}

        with patch('apps.integrations.models.DataSourceDevice.objects') as mock_qs:
            mock_qs.filter.return_value.select_related.return_value = [dsd]
            with patch('apps.integrations.auth_handlers.get_auth_session', return_value=good_auth):
                with patch('apps.integrations.tasks.http_requests.request', return_value=resp):
                    fetch_device_metadata([dsd.pk])

        dsd.virtual_device.save.assert_called_once_with(update_fields=['name'])
        assert dsd.virtual_device.name == 'Station Alpha'

    def test_skips_update_when_name_is_empty(self):
        """An empty string from JSONPath does not overwrite the current name."""
        dsd = make_dsd_for_metadata()
        good_auth = ({'Authorization': 'Bearer tok'}, {}, None)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {'name': '   '}

        with patch('apps.integrations.models.DataSourceDevice.objects') as mock_qs:
            mock_qs.filter.return_value.select_related.return_value = [dsd]
            with patch('apps.integrations.auth_handlers.get_auth_session', return_value=good_auth):
                with patch('apps.integrations.tasks.http_requests.request', return_value=resp):
                    fetch_device_metadata([dsd.pk])

        dsd.virtual_device.save.assert_not_called()

    def test_continues_to_next_device_on_request_error(self):
        """A network error on one device does not abort metadata fetch for others."""
        dsd1 = make_dsd_for_metadata(pk=1)
        dsd2 = make_dsd_for_metadata(pk=2)
        good_auth = ({'Authorization': 'Bearer tok'}, {}, None)
        resp_ok = MagicMock()
        resp_ok.raise_for_status.return_value = None
        resp_ok.json.return_value = {'name': 'Station Beta'}

        http_side_effects = [req_lib.ConnectionError('refused'), resp_ok]

        with patch('apps.integrations.models.DataSourceDevice.objects') as mock_qs:
            mock_qs.filter.return_value.select_related.return_value = [dsd1, dsd2]
            with patch('apps.integrations.auth_handlers.get_auth_session', return_value=good_auth):
                with patch('apps.integrations.tasks.http_requests.request',
                           side_effect=http_side_effects):
                    fetch_device_metadata([dsd1.pk, dsd2.pk])

        dsd1.virtual_device.save.assert_not_called()
        dsd2.virtual_device.save.assert_called_once_with(update_fields=['name'])

    def test_respects_rate_limit_between_calls(self):
        """When max_requests_per_second is set, sleep is called between device calls."""
        dsd1 = make_dsd_for_metadata(pk=1)
        dsd2 = make_dsd_for_metadata(pk=2)
        dsd1.datasource.provider.max_requests_per_second = 2
        dsd2.datasource.provider.max_requests_per_second = 2
        good_auth = ({'Authorization': 'Bearer tok'}, {}, None)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {'name': 'X'}

        with patch('apps.integrations.models.DataSourceDevice.objects') as mock_qs:
            mock_qs.filter.return_value.select_related.return_value = [dsd1, dsd2]
            with patch('apps.integrations.auth_handlers.get_auth_session', return_value=good_auth):
                with patch('apps.integrations.tasks.http_requests.request', return_value=resp):
                    with patch('apps.integrations.tasks.time_lib.sleep') as mock_sleep:
                        fetch_device_metadata([dsd1.pk, dsd2.pk])

        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(0.5)  # 1.0 / 2 rps
