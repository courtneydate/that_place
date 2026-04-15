"""Celery tasks for 3rd-party API polling.

poll_datasource_devices — beat task, runs every 30 s. Finds all active
    DataSourceDevices due for polling and dispatches individual poll tasks.

poll_single_device — polls one DataSourceDevice, extracts values via JSONPath,
    stores StreamReadings, handles auth failures and retry tracking.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import logging
import time as time_lib
from datetime import timedelta

import requests as http_requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from jsonpath_ng import parse as jp_parse

logger = logging.getLogger(__name__)

# Consecutive failures before surfacing a DeviceHealth warning
POLL_FAILURE_THRESHOLD = 5

# HTTP timeout for provider API calls (seconds)
REQUEST_TIMEOUT = 15

# How many times to re-authenticate and retry after a 401 from the provider.
# Handles server-side token revocation where the cached token looks valid but
# has been invalidated before its stated expiry.
MAX_AUTH_RETRIES = 3


@shared_task(name='integrations.poll_datasource_devices')
def poll_datasource_devices() -> None:
    """Find all active DataSourceDevices due for polling and dispatch per-device tasks.

    A device is due when:
      - It has never been polled (last_polled_at is None), or
      - Time since last poll >= the device's poll_interval_seconds (falls back
        to provider's default_poll_interval_seconds when null).

    Dispatching is staggered per provider using Celery countdown to respect the
    provider's max_requests_per_second rate limit and avoid thundering-herd 429s.
    """
    from collections import defaultdict

    from .models import DataSourceDevice

    now = timezone.now()
    dispatched = 0

    devices = (
        DataSourceDevice.objects
        .filter(is_active=True, datasource__is_active=True)
        .select_related('datasource__provider')
    )

    # Group due devices by provider so we can stagger per-provider rate limit.
    due_by_provider = defaultdict(list)
    for dsd in devices:
        provider = dsd.datasource.provider
        interval = dsd.poll_interval_seconds or provider.default_poll_interval_seconds
        if dsd.last_polled_at is None:
            due = True
        else:
            due = (now - dsd.last_polled_at).total_seconds() >= interval
        if due:
            due_by_provider[provider.pk].append((dsd, provider))

    for provider_pk, items in due_by_provider.items():
        rate = items[0][1].max_requests_per_second  # requests/second, or None
        for i, (dsd, _) in enumerate(items):
            # countdown (seconds) = how many full batches precede this device.
            # With rate=5: devices 0-4 → countdown 0, devices 5-9 → countdown 1, etc.
            countdown = (i // rate) if rate else 0
            poll_single_device.apply_async(args=[dsd.pk], countdown=countdown)
            dispatched += 1

    if dispatched:
        logger.info('Dispatched %d DataSourceDevice poll tasks', dispatched)


@shared_task(name='integrations.poll_single_device', max_retries=0)
def poll_single_device(datasource_device_id: int) -> None:
    """Poll a single DataSourceDevice and store StreamReadings.

    On success: resets consecutive_poll_failures, updates DeviceHealth (online).
    On failure: increments consecutive_poll_failures; after POLL_FAILURE_THRESHOLD
                marks DeviceHealth as offline/critical.
    """
    from apps.devices.models import DeviceHealth
    from apps.readings.models import Stream, StreamReading

    from .auth_handlers import AuthError, get_auth_session
    from .models import DataSourceDevice

    now = timezone.now()

    try:
        dsd = (
            DataSourceDevice.objects
            .select_related(
                'datasource__provider',
                'datasource',
                'virtual_device',
            )
            .get(pk=datasource_device_id, is_active=True)
        )
    except DataSourceDevice.DoesNotExist:
        logger.warning('DataSourceDevice %d not found or inactive — skipping', datasource_device_id)
        return

    provider = dsd.datasource.provider
    credentials = dsd.datasource.credentials or {}
    token_cache = dsd.datasource.auth_token_cache or {}

    # --- Build request URL and time-windowed params ---
    detail_cfg = provider.detail_endpoint
    path_template = detail_cfg.get('path_template', detail_cfg.get('path', ''))
    path = path_template.replace('{device_id}', str(dsd.external_device_id))
    method = detail_cfg.get('method', 'GET').upper()
    url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')
    time_params = _build_time_params(detail_cfg, dsd.last_polled_at, now)

    # --- Authenticate and call provider, retrying up to MAX_AUTH_RETRIES times on 401.
    # A 401 from the device endpoint means the token was revoked server-side before its
    # stated expiry. Clear the cache and re-authenticate before each retry. ---
    data = None
    for attempt in range(MAX_AUTH_RETRIES):
        try:
            headers, params, updated_cache = get_auth_session(provider, credentials, token_cache)
        except AuthError as exc:
            logger.error(
                'Auth failure polling DataSourceDevice %d (ds=%d): %s',
                dsd.pk, dsd.datasource_id, exc,
            )
            _record_failure(dsd, DataSourceDevice.PollStatus.AUTH_FAILURE, str(exc), now)
            return

        if updated_cache is not None:
            dsd.datasource.auth_token_cache = updated_cache
            token_cache = updated_cache
            dsd.datasource.save(update_fields=['auth_token_cache'])

        try:
            resp = http_requests.request(
                method, url, headers=headers, params={**params, **time_params}, timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            break  # success — exit retry loop
        except http_requests.HTTPError as exc:
            if resp.status_code == 401:
                logger.warning(
                    'DataSourceDevice %d: 401 on attempt %d/%d — clearing token cache and retrying',
                    dsd.pk, attempt + 1, MAX_AUTH_RETRIES,
                )
                token_cache = {}
                dsd.datasource.auth_token_cache = {}
                dsd.datasource.save(update_fields=['auth_token_cache'])
                # continue to next attempt
            else:
                logger.error('Poll request failed for DataSourceDevice %d: %s', dsd.pk, exc)
                _record_failure(dsd, DataSourceDevice.PollStatus.ERROR, str(exc), now)
                return
        except http_requests.RequestException as exc:
            logger.error('Poll request failed for DataSourceDevice %d: %s', dsd.pk, exc)
            _record_failure(dsd, DataSourceDevice.PollStatus.ERROR, str(exc), now)
            return
    else:
        # All MAX_AUTH_RETRIES attempts returned 401
        logger.error(
            'DataSourceDevice %d: 401 Unauthorized after %d auth retries',
            dsd.pk, MAX_AUTH_RETRIES,
        )
        _record_failure(
            dsd,
            DataSourceDevice.PollStatus.AUTH_FAILURE,
            f'401 Unauthorized after {MAX_AUTH_RETRIES} auth retries',
            now,
        )
        return

    # --- Extract values and build StreamReadings ---
    streams_by_key = {
        s.key: s
        for s in Stream.objects.filter(
            device=dsd.virtual_device,
            key__in=dsd.active_stream_keys,
        )
    }
    streams_defs_by_key = {s['key']: s for s in (provider.available_streams or [])}

    readings_to_create = []
    for stream_key in dsd.active_stream_keys:
        stream = streams_by_key.get(stream_key)
        stream_def = streams_defs_by_key.get(stream_key)
        if not stream or not stream_def:
            continue

        jsonpath_expr = stream_def.get('jsonpath')
        if not jsonpath_expr:
            continue

        try:
            matches = jp_parse(jsonpath_expr).find(data)
        except Exception as exc:
            logger.warning(
                'JSONPath error for stream "%s" on DataSourceDevice %d: %s',
                stream_key, dsd.pk, exc,
            )
            continue

        if not matches:
            continue

        readings_to_create.append(StreamReading(
            stream=stream,
            value=matches[0].value,
            timestamp=now,
        ))

    # --- Persist ---
    with transaction.atomic():
        if readings_to_create:
            StreamReading.objects.bulk_create(readings_to_create)

        dsd.last_polled_at = now
        dsd.last_poll_status = DataSourceDevice.PollStatus.OK
        dsd.last_poll_error = None
        dsd.consecutive_poll_failures = 0
        dsd.save(update_fields=[
            'last_polled_at', 'last_poll_status', 'last_poll_error',
            'consecutive_poll_failures',
        ])

        # Update or create DeviceHealth
        health, created = DeviceHealth.objects.get_or_create(
            device=dsd.virtual_device,
            defaults={
                'is_online': True,
                'last_seen_at': now,
                'first_active_at': now,
            },
        )
        if not created:
            health.is_online = True
            health.last_seen_at = now
            health.save(update_fields=['is_online', 'last_seen_at', 'updated_at'])

    logger.debug(
        'Polled DataSourceDevice %d: %d reading(s) stored',
        dsd.pk, len(readings_to_create),
    )


def _build_time_params(detail_cfg: dict, last_polled_at, now) -> dict:
    """Interpolate time tokens in measurement endpoint query params.

    Supports four tokens in param values:
      {from_unix} / {to_unix}  — Unix timestamps (integer seconds, as strings)
      {from_iso}  / {to_iso}   — ISO 8601 UTC (e.g. 2025-04-15T09:00:00Z)

    'from' is last_polled_at, or (now - window_seconds) on the first poll.
    'to' is always now.

    Returns an empty dict when no params are configured, leaving the existing
    behaviour for providers that don't use time-windowed measurement.
    """
    raw_params = detail_cfg.get('params')
    if not raw_params:
        return {}

    window = detail_cfg.get('window_seconds', 300)
    from_dt = last_polled_at if last_polled_at is not None else now - timedelta(seconds=window)

    tokens = {
        '{from_unix}': str(int(from_dt.timestamp())),
        '{to_unix}': str(int(now.timestamp())),
        '{from_iso}': from_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
        '{to_iso}': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }

    result = {}
    for key, value in raw_params.items():
        for token, replacement in tokens.items():
            value = str(value).replace(token, replacement)
        result[key] = value
    return result


@shared_task(name='integrations.fetch_device_metadata')
def fetch_device_metadata(datasource_device_ids: list) -> None:
    """Fetch device metadata for newly connected DataSourceDevices.

    Dispatched after the connection wizard completes. If the provider has
    device_detail_endpoint configured, calls it once per device to populate
    the virtual device name from the provider's own metadata.

    Only updates the name when the endpoint returns a non-empty value, so any
    name the tenant typed manually in the wizard is preserved.

    Respects the provider's max_requests_per_second between calls.
    """
    from .auth_handlers import AuthError, get_auth_session
    from .models import DataSourceDevice

    dsds = (
        DataSourceDevice.objects
        .filter(pk__in=datasource_device_ids, is_active=True)
        .select_related('datasource__provider', 'virtual_device')
    )

    for dsd in dsds:
        provider = dsd.datasource.provider
        detail_cfg = provider.device_detail_endpoint
        if not detail_cfg or not detail_cfg.get('path_template'):
            continue

        path = detail_cfg['path_template'].replace('{device_id}', str(dsd.external_device_id))
        method = detail_cfg.get('method', 'GET').upper()
        url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')
        name_jsonpath = detail_cfg.get('name_jsonpath')

        credentials = dsd.datasource.credentials or {}
        token_cache = dsd.datasource.auth_token_cache or {}
        try:
            headers, params, updated_cache = get_auth_session(provider, credentials, token_cache)
        except AuthError as exc:
            logger.warning(
                'fetch_device_metadata auth failure for DataSourceDevice %d: %s', dsd.pk, exc,
            )
            continue

        if updated_cache is not None:
            dsd.datasource.auth_token_cache = updated_cache
            dsd.datasource.save(update_fields=['auth_token_cache'])

        try:
            resp = http_requests.request(
                method, url, headers=headers, params=params, timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except http_requests.RequestException as exc:
            logger.warning(
                'fetch_device_metadata request failed for DataSourceDevice %d: %s', dsd.pk, exc,
            )
            continue

        if name_jsonpath:
            try:
                matches = jp_parse(name_jsonpath).find(data)
            except Exception as exc:
                logger.warning(
                    'fetch_device_metadata JSONPath error for DataSourceDevice %d: %s', dsd.pk, exc,
                )
                continue

            if matches:
                name = str(matches[0].value).strip()
                if name:
                    device = dsd.virtual_device
                    device.name = name
                    device.save(update_fields=['name'])
                    logger.debug(
                        'Updated virtual device %d name to %r via metadata endpoint',
                        device.pk, name,
                    )

        # Respect provider rate limit between successive calls
        rate = provider.max_requests_per_second
        if rate:
            time_lib.sleep(1.0 / rate)


def _record_failure(dsd, poll_status: str, error_msg: str, now) -> None:
    """Record a poll failure and surface a DeviceHealth warning at threshold."""
    from apps.devices.models import DeviceHealth

    dsd.last_polled_at = now
    dsd.last_poll_status = poll_status
    dsd.last_poll_error = error_msg
    dsd.consecutive_poll_failures += 1
    dsd.save(update_fields=[
        'last_polled_at', 'last_poll_status', 'last_poll_error',
        'consecutive_poll_failures',
    ])

    if dsd.consecutive_poll_failures >= POLL_FAILURE_THRESHOLD:
        DeviceHealth.objects.update_or_create(
            device=dsd.virtual_device,
            defaults={
                'is_online': False,
                'activity_level': DeviceHealth.ActivityLevel.CRITICAL,
            },
        )
        logger.warning(
            'DataSourceDevice %d has %d consecutive failures — device health set critical',
            dsd.pk, dsd.consecutive_poll_failures,
        )
