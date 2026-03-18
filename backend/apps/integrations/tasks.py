"""Celery tasks for 3rd-party API polling.

poll_datasource_devices — beat task, runs every 60 s. Finds all active
    DataSourceDevices due for polling and dispatches individual poll tasks.

poll_single_device — polls one DataSourceDevice, extracts values via JSONPath,
    stores StreamReadings, handles auth failures and retry tracking.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import logging

import requests as http_requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from jsonpath_ng.ext import parse as jp_parse

logger = logging.getLogger(__name__)

# Consecutive failures before surfacing a DeviceHealth warning
POLL_FAILURE_THRESHOLD = 5

# HTTP timeout for provider API calls (seconds)
REQUEST_TIMEOUT = 15


@shared_task(name='integrations.poll_datasource_devices')
def poll_datasource_devices() -> None:
    """Find all active DataSourceDevices due for polling and dispatch per-device tasks.

    A device is due when:
      - It has never been polled (last_polled_at is None), or
      - Time since last poll >= provider's default_poll_interval_seconds.
    """
    from .models import DataSourceDevice

    now = timezone.now()
    dispatched = 0

    devices = (
        DataSourceDevice.objects
        .filter(is_active=True, datasource__is_active=True)
        .select_related('datasource__provider')
    )

    for dsd in devices:
        interval = dsd.datasource.provider.default_poll_interval_seconds
        if dsd.last_polled_at is None:
            due = True
        else:
            due = (now - dsd.last_polled_at).total_seconds() >= interval

        if due:
            poll_single_device.delay(dsd.pk)
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

    # --- Authenticate ---
    try:
        headers, params, updated_cache = get_auth_session(provider, credentials, token_cache)
    except AuthError as exc:
        logger.error(
            'Auth failure polling DataSourceDevice %d (ds=%d): %s',
            dsd.pk, dsd.datasource_id, exc,
        )
        _record_failure(dsd, DataSourceDevice.PollStatus.AUTH_FAILURE, str(exc), now)
        return

    # Persist refreshed token
    if updated_cache is not None:
        dsd.datasource.auth_token_cache = updated_cache
        dsd.datasource.save(update_fields=['auth_token_cache'])

    # --- Build request URL ---
    detail_cfg = provider.detail_endpoint
    path_template = detail_cfg.get('path_template', detail_cfg.get('path', ''))
    path = path_template.replace('{device_id}', str(dsd.external_device_id))
    method = detail_cfg.get('method', 'GET').upper()
    url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')

    # --- Call provider ---
    try:
        resp = http_requests.request(
            method, url, headers=headers, params=params, timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except http_requests.RequestException as exc:
        logger.error('Poll request failed for DataSourceDevice %d: %s', dsd.pk, exc)
        _record_failure(dsd, DataSourceDevice.PollStatus.ERROR, str(exc), now)
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
