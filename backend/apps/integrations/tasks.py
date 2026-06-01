"""Celery tasks for 3rd-party API polling.

poll_datasource_devices — beat task, runs every 30 s. Finds all active
    DataSourceDevices due for polling and dispatches individual poll tasks.

poll_single_device — polls one DataSourceDevice, extracts values via JSONPath,
    stores StreamReadings, handles auth failures and retry tracking.

run_backfill_job — Sprint 29a. Walks each DataSourceDevice on the data source,
    splits the date range into chunks, calls the provider history endpoint,
    iterates rows with provider-supplied timestamps, dedupes against existing
    StreamReadings, and tracks aggregate progress on DataSourceBackfillJob.

reconcile_backfill_flags — Sprint 29a. Janitor beat task; clears
    `is_backfilling=True` on DataSourceDevices whose data source has no
    queued/running job. Recovers from worker crashes that left the flag set.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
     ROADMAP Sprint 29a
"""
import logging
import time as time_lib
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

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
        .filter(
            is_active=True,
            datasource__is_active=True,
            is_backfilling=False,
        )
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

    # Dispatch rule evaluation for any stream that received a new reading.
    # The 3rd-party API poll path must trigger the rules engine the same way
    # the MQTT ingestion path does — otherwise a rule whose condition watches a
    # polled stream is never evaluated and never fires.
    # Ref: SPEC.md § Feature: Rule Evaluation Engine.
    if readings_to_create:
        from apps.ingestion.tasks import _dispatch_stream_rule_evaluation
        for stream_id in frozenset(r.stream_id for r in readings_to_create):
            _dispatch_stream_rule_evaluation.delay(stream_id)

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
        from apps.notifications.tasks import create_system_notification
        create_system_notification.delay(
            'datasource_poll_failure',
            dsd.virtual_device.tenant_id,
            {
                'device_name': dsd.virtual_device.name,
                'serial_number': dsd.virtual_device.serial_number,
                'consecutive_failures': dsd.consecutive_poll_failures,
            },
        )
        # If every active data source for this provider is failing, the
        # provider is down platform-wide — notify That Place Admins.
        _maybe_notify_provider_outage(dsd.datasource.provider)


def _maybe_notify_provider_outage(provider) -> None:
    """Emit third_party_api_provider_failure when a provider is down platform-wide.

    A platform-wide outage means every active ``DataSourceDevice`` for the
    provider — across all tenants — is in ``error`` / ``auth_failure``. This is
    distinct from a single tenant's ``datasource_poll_failure`` (usually a
    credential issue). Re-emission is cooldown-suppressed per provider so a
    sustained outage does not flood That Place Admins. Ref: ROADMAP Sprint 23.
    """
    from django.core.cache import cache

    from .models import DataSourceDevice

    devices = DataSourceDevice.objects.filter(
        datasource__provider_id=provider.pk, is_active=True,
    )
    statuses = set(devices.values_list('last_poll_status', flat=True))
    failing = {'error', 'auth_failure'}
    if not statuses or not statuses.issubset(failing):
        # At least one data source is healthy or not yet polled — not an outage.
        return

    if not cache.add(f'provider_outage_notified_{provider.pk}', True, timeout=3600):
        return  # already notified within the cooldown window

    tenant_count = devices.values('datasource__tenant_id').distinct().count()
    from apps.notifications.tasks import emit_event
    emit_event.delay(
        'third_party_api_provider_failure',
        {'provider_name': provider.name, 'tenant_count': tenant_count},
    )
    logger.warning(
        'ThirdPartyAPIProvider "%s" (pk=%d) appears down platform-wide '
        '— %d tenant(s) affected',
        provider.name, provider.pk, tenant_count,
    )


# ---------------------------------------------------------------------------
# Sprint 29a — 3rd-party API history / backfill
# ---------------------------------------------------------------------------

# HTTP timeout for provider history calls (seconds). Longer than live-poll
# because some history endpoints aggregate large windows on the server.
HISTORY_REQUEST_TIMEOUT = 60


@shared_task(name='integrations.run_backfill_job', max_retries=0)
def run_backfill_job(job_id: int) -> None:
    """Run a DataSourceBackfillJob to completion (Sprint 29a).

    Walks every active DataSourceDevice on the job's data source. For each
    device, splits the [date_from, date_to] window into chunks of
    `provider.history_chunk_days`, calls the provider history endpoint per
    chunk with `{from_iso}/{to_iso}` interpolated into `params`, iterates the
    response rows, extracts a per-row timestamp + per-stream values, and
    creates StreamReadings deduplicated against (stream, timestamp).

    `is_backfilling=True` is set on each DataSourceDevice for the duration of
    its chunk loop so the live-poll beat task skips it. The flag is cleared
    in a `finally` block so a worker crash leaves at most a transient orphan
    that `reconcile_backfill_flags` later cleans up.
    """
    from apps.readings.models import Stream, StreamReading

    from .auth_handlers import AuthError, get_auth_session
    from .models import DataSourceBackfillJob, DataSourceDevice

    try:
        job = (
            DataSourceBackfillJob.objects
            .select_related('datasource__provider', 'datasource')
            .get(pk=job_id)
        )
    except DataSourceBackfillJob.DoesNotExist:
        logger.warning('Backfill job %d not found — skipping', job_id)
        return

    provider = job.datasource.provider
    history_cfg = provider.history_endpoint or {}
    if not provider.supports_history or not history_cfg.get('path_template'):
        _fail_job(job, 'Provider does not support history backfill.')
        return

    job.status = DataSourceBackfillJob.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=['status', 'started_at'])

    credentials = job.datasource.credentials or {}
    devices = list(
        DataSourceDevice.objects
        .filter(datasource=job.datasource, is_active=True)
        .select_related('virtual_device')
    )

    chunk_days = max(provider.history_chunk_days or 7, 1)
    chunks = list(_iter_date_chunks(job.date_from, job.date_to, chunk_days))
    streams_defs = {s['key']: s for s in (provider.available_streams or [])}

    total_fetched = 0
    total_stored = 0

    try:
        for dsd in devices:
            dsd.is_backfilling = True
            dsd.save(update_fields=['is_backfilling'])
            try:
                stream_lookup = _stream_lookup_for_device(Stream, dsd)
                for chunk_start, chunk_end in chunks:
                    fetched, stored = _backfill_one_chunk(
                        provider=provider,
                        datasource=job.datasource,
                        dsd=dsd,
                        history_cfg=history_cfg,
                        credentials=credentials,
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                        stream_lookup=stream_lookup,
                        streams_defs=streams_defs,
                        get_auth_session=get_auth_session,
                        AuthError=AuthError,
                        StreamReading=StreamReading,
                    )
                    total_fetched += fetched
                    total_stored += stored
            finally:
                dsd.is_backfilling = False
                dsd.save(update_fields=['is_backfilling'])

        job.rows_fetched = total_fetched
        job.rows_stored = total_stored
        job.status = DataSourceBackfillJob.Status.COMPLETED
        job.finished_at = timezone.now()
        job.save(update_fields=[
            'rows_fetched', 'rows_stored', 'status', 'finished_at',
        ])
        logger.info(
            'Backfill job %d completed: %d rows fetched, %d stored',
            job.pk, total_fetched, total_stored,
        )
    except Exception as exc:  # noqa: BLE001 — fail the job on any error
        logger.exception('Backfill job %d failed', job.pk)
        job.rows_fetched = total_fetched
        job.rows_stored = total_stored
        _fail_job(job, str(exc))


def _fail_job(job, error: str) -> None:
    """Mark a DataSourceBackfillJob failed with an error string."""
    from .models import DataSourceBackfillJob

    job.status = DataSourceBackfillJob.Status.FAILED
    job.error_detail = error[:5000]
    job.finished_at = timezone.now()
    job.save(update_fields=[
        'status', 'error_detail', 'finished_at',
        'rows_fetched', 'rows_stored',
    ])
    # Also clear any is_backfilling flags this job may have left set.
    from .models import DataSourceDevice
    DataSourceDevice.objects.filter(
        datasource=job.datasource, is_backfilling=True,
    ).update(is_backfilling=False)


def _stream_lookup_for_device(Stream, dsd):
    """Return a {stream_key: Stream} mapping for the device's active streams."""
    return {
        s.key: s
        for s in Stream.objects.filter(
            device=dsd.virtual_device, key__in=dsd.active_stream_keys,
        )
    }


def _iter_date_chunks(date_from, date_to, chunk_days):
    """Split [date_from, date_to] (inclusive) into (start_dt, end_dt) chunks.

    Yields aware UTC datetimes — start at 00:00:00 of the chunk's first day,
    end at 23:59:59.999999 of the chunk's last day. The final chunk may be
    shorter than `chunk_days`.
    """
    cursor = date_from
    delta = timedelta(days=chunk_days)
    while cursor <= date_to:
        chunk_end = min(cursor + delta - timedelta(days=1), date_to)
        start_dt = datetime.combine(cursor, time.min, tzinfo=dt_timezone.utc)
        end_dt = datetime.combine(chunk_end, time.max, tzinfo=dt_timezone.utc)
        yield start_dt, end_dt
        cursor = chunk_end + timedelta(days=1)


def _backfill_one_chunk(
    *,
    provider,
    datasource,
    dsd,
    history_cfg,
    credentials,
    chunk_start,
    chunk_end,
    stream_lookup,
    streams_defs,
    get_auth_session,
    AuthError,
    StreamReading,
):
    """Fetch one chunk for one device and persist deduplicated readings.

    Returns (rows_fetched, rows_stored).
    """
    token_cache = datasource.auth_token_cache or {}
    try:
        headers, base_params, updated_cache = get_auth_session(
            provider, credentials, token_cache,
        )
    except AuthError as exc:
        raise RuntimeError(
            f'Auth failure during backfill on device {dsd.pk}: {exc}',
        ) from exc

    if updated_cache is not None:
        datasource.auth_token_cache = updated_cache
        datasource.save(update_fields=['auth_token_cache'])

    path_template = history_cfg.get('path_template', '')
    method = history_cfg.get('method', 'GET').upper()
    path = path_template.replace('{device_id}', str(dsd.external_device_id))
    url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')
    time_params = _build_time_params_for_window(
        history_cfg, chunk_start, chunk_end,
    )

    try:
        resp = http_requests.request(
            method, url,
            headers=headers, params={**base_params, **time_params},
            timeout=HISTORY_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except http_requests.RequestException as exc:
        raise RuntimeError(
            f'History request failed for device {dsd.pk} '
            f'({chunk_start.date()}→{chunk_end.date()}): {exc}',
        ) from exc

    root_path = history_cfg.get('response_root_jsonpath', '$[*]')
    ts_path = history_cfg.get('timestamp_jsonpath')
    if not ts_path:
        raise RuntimeError(
            'Provider history_endpoint is missing timestamp_jsonpath.',
        )

    try:
        rows = [m.value for m in jp_parse(root_path).find(data)]
    except Exception as exc:
        raise RuntimeError(
            f'response_root_jsonpath failed on chunk response: {exc}',
        ) from exc

    fetched = len(rows)
    if not rows:
        return 0, 0

    # Build the per-row timestamp + per-stream value extractors.
    ts_expr = jp_parse(ts_path)
    stream_exprs = {}
    for key in dsd.active_stream_keys:
        if key not in stream_lookup or key not in streams_defs:
            continue
        path_expr = streams_defs[key].get('jsonpath')
        if not path_expr:
            continue
        try:
            stream_exprs[key] = jp_parse(path_expr)
        except Exception as exc:
            logger.warning(
                'JSONPath parse failed for stream "%s" on backfill device %d: %s',
                key, dsd.pk, exc,
            )

    # Collect candidate (stream_id, ts, value) tuples from this chunk.
    candidates_by_stream: dict[int, list[tuple]] = {}
    for row in rows:
        ts_matches = ts_expr.find(row)
        if not ts_matches:
            continue
        ts = _parse_provider_timestamp(ts_matches[0].value)
        if ts is None:
            continue
        for key, expr in stream_exprs.items():
            stream = stream_lookup[key]
            matches = expr.find(row)
            if not matches:
                continue
            candidates_by_stream.setdefault(stream.pk, []).append((ts, matches[0].value, stream))

    if not candidates_by_stream:
        return fetched, 0

    # Dedup: per stream, fetch existing timestamps in the chunk window and skip
    # any candidate whose timestamp already exists.
    new_readings = []
    for stream_pk, items in candidates_by_stream.items():
        candidate_ts = {ts for ts, _, _ in items}
        existing_ts = set(
            StreamReading.objects.filter(
                stream_id=stream_pk,
                timestamp__in=candidate_ts,
            ).values_list('timestamp', flat=True)
        )
        for ts, value, stream in items:
            if ts in existing_ts:
                continue
            new_readings.append(StreamReading(
                stream=stream, value=value, timestamp=ts,
            ))

    if new_readings:
        with transaction.atomic():
            StreamReading.objects.bulk_create(new_readings)

    return fetched, len(new_readings)


def _build_time_params_for_window(cfg: dict, from_dt, to_dt) -> dict:
    """Like _build_time_params but with explicit window endpoints.

    The live-poll variant infers `from` from `last_polled_at`. The backfill
    variant uses the chunk boundaries directly.
    """
    raw_params = cfg.get('params')
    if not raw_params:
        return {}

    tokens = {
        '{from_unix}': str(int(from_dt.timestamp())),
        '{to_unix}': str(int(to_dt.timestamp())),
        '{from_iso}': from_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
        '{to_iso}': to_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    result = {}
    for key, value in raw_params.items():
        for token, replacement in tokens.items():
            value = str(value).replace(token, replacement)
        result[key] = value
    return result


def _parse_provider_timestamp(raw):
    """Parse a provider-supplied timestamp to an aware UTC datetime.

    Accepts ISO 8601 strings (with or without trailing Z) and integer Unix
    timestamps (seconds since epoch). Returns None on failure so the row can
    be skipped without aborting the chunk.
    """
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=dt_timezone.utc)
        except (ValueError, OSError):
            return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


@shared_task(name='integrations.reconcile_backfill_flags')
def reconcile_backfill_flags() -> None:
    """Janitor beat task — clears orphaned `is_backfilling` flags.

    Recovers from worker crashes that left `is_backfilling=True` on a
    DataSourceDevice with no live job. A flag is considered orphaned when its
    data source has no queued or running DataSourceBackfillJob. Runs every
    5 minutes via Celery beat.
    """
    from .models import DataSourceBackfillJob, DataSourceDevice

    active_ds_ids = set(
        DataSourceBackfillJob.objects
        .filter(status__in=[
            DataSourceBackfillJob.Status.QUEUED,
            DataSourceBackfillJob.Status.RUNNING,
        ])
        .values_list('datasource_id', flat=True)
    )
    cleared = (
        DataSourceDevice.objects
        .filter(is_backfilling=True)
        .exclude(datasource_id__in=active_ds_ids)
        .update(is_backfilling=False)
    )
    if cleared:
        logger.warning(
            'reconcile_backfill_flags: cleared is_backfilling on %d orphan(s)',
            cleared,
        )
