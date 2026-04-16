"""Celery tasks for the feeds app.

poll_system_feeds        — beat task, runs every 60 s. Finds all active
    scope=system FeedProviders due for polling and dispatches poll tasks.

poll_single_provider     — polls one FeedProvider, extracts channel values
    via JSONPath, stores FeedReadings, dispatches rule evaluation.

poll_tenant_subscriptions — beat task, runs every 60 s. Finds all active
    TenantFeedSubscriptions due for polling and dispatches poll tasks.

poll_single_subscription  — polls one TenantFeedSubscription.

evaluate_reference_value_rules — beat task, runs every 5 minutes. Re-evaluates
    rules that have reference_value conditions (catches TOU boundary changes).

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets,
     § Feature: Rule Evaluation Engine
"""
import logging

import requests as http_requests
from celery import shared_task
from django.utils import timezone
from jsonpath_ng import parse as jp_parse

from apps.rules.models import RuleCondition
from apps.rules.tasks import evaluate_rule

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
POLL_FAILURE_THRESHOLD = 3


# ---------------------------------------------------------------------------
# System feed polling
# ---------------------------------------------------------------------------

@shared_task(name='feeds.poll_system_feeds')
def poll_system_feeds() -> None:
    """Dispatch poll tasks for all active scope=system FeedProviders that are due.

    A provider is due when:
      - It has no FeedReadings at all (never polled), or
      - Time since the latest FeedReading timestamp >= poll_interval_seconds.

    Ref: SPEC.md § Feature: Feed Providers — System-scope feed polling
    """
    from .models import FeedProvider, FeedReading

    now = timezone.now()
    providers = FeedProvider.objects.filter(
        scope=FeedProvider.Scope.SYSTEM,
        is_active=True,
    )

    dispatched = 0
    for provider in providers:
        latest = (
            FeedReading.objects
            .filter(channel__provider=provider)
            .order_by('-fetched_at')
            .values_list('fetched_at', flat=True)
            .first()
        )
        if latest is None:
            due = True
        else:
            due = (now - latest).total_seconds() >= provider.poll_interval_seconds

        if due:
            poll_single_provider.delay(provider.pk)
            dispatched += 1

    if dispatched:
        logger.info('Dispatched %d system feed poll tasks', dispatched)


@shared_task(name='feeds.poll_single_provider', max_retries=3, default_retry_delay=30)
def poll_single_provider(provider_pk: int) -> None:
    """Poll all endpoints of a single FeedProvider and store FeedReadings.

    For each endpoint:
      1. Fetch the URL.
      2. If response_root_jsonpath set, iterate rows; otherwise treat as single object.
      3. For each row, extract dimension_value (if dimension_key configured) and
         each channel's value via value_jsonpath.
      4. get_or_create FeedChannel for (provider, key, dimension_value).
      5. Store FeedReading (idempotent via ignore_conflicts on unique constraint).
      6. Dispatch rule evaluation for rules referencing that channel.

    Ref: SPEC.md § Feature: Feed Providers
    """
    from .models import FeedChannel, FeedProvider, FeedReading

    now = timezone.now()

    try:
        provider = FeedProvider.objects.get(pk=provider_pk, is_active=True)
    except FeedProvider.DoesNotExist:
        logger.warning('FeedProvider %d not found or inactive — skipping', provider_pk)
        return

    consecutive_failures = 0

    for endpoint_cfg in (provider.endpoints or []):
        path = endpoint_cfg.get('path', '')
        method = endpoint_cfg.get('method', 'GET').upper()
        url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')
        response_root_jsonpath = endpoint_cfg.get('response_root_jsonpath')
        dimension_key = endpoint_cfg.get('dimension_key')
        channel_defs = endpoint_cfg.get('channels', [])

        # --- Fetch ---
        try:
            headers = _build_auth_headers(provider)
            resp = http_requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except http_requests.RequestException as exc:
            logger.error('FeedProvider %d endpoint "%s" failed: %s', provider_pk, path, exc)
            consecutive_failures += 1
            continue

        # --- Iterate rows ---
        if response_root_jsonpath:
            try:
                rows = [m.value for m in jp_parse(response_root_jsonpath).find(data)]
            except Exception as exc:
                logger.error(
                    'FeedProvider %d: JSONPath "%s" failed: %s',
                    provider_pk, response_root_jsonpath, exc,
                )
                consecutive_failures += 1
                continue
        else:
            rows = [data]

        readings_to_create = []
        for row in rows:
            # Extract dimension value for this row
            dim_value = None
            if dimension_key:
                dim_value = str(row.get(dimension_key, '')).strip() or None

            for ch_def in channel_defs:
                key = ch_def.get('key')
                value_jsonpath = ch_def.get('value_jsonpath')
                if not key or not value_jsonpath:
                    continue

                # Extract value
                try:
                    matches = jp_parse(value_jsonpath).find(row)
                except Exception as exc:
                    logger.warning(
                        'FeedProvider %d channel "%s": JSONPath error: %s',
                        provider_pk, key, exc,
                    )
                    continue

                if not matches:
                    continue
                value = matches[0].value

                # Get or create FeedChannel for this provider/key/dimension_value
                channel, _ = FeedChannel.objects.get_or_create(
                    provider=provider,
                    key=key,
                    dimension_value=dim_value,
                    defaults={
                        'label': ch_def.get('label', key),
                        'unit': ch_def.get('unit', ''),
                        'data_type': ch_def.get('data_type', FeedChannel.DataType.NUMERIC),
                        'is_active': True,
                    },
                )

                readings_to_create.append(FeedReading(
                    channel=channel,
                    value=value,
                    timestamp=now,
                    fetched_at=now,
                ))

        # Bulk create — ignore_conflicts handles the unique (channel, timestamp) constraint
        if readings_to_create:
            created = FeedReading.objects.bulk_create(
                readings_to_create,
                ignore_conflicts=True,
            )
            logger.debug(
                'FeedProvider %d: stored %d reading(s)', provider_pk, len(created)
            )

            # Dispatch rule evaluation for each unique channel that got a new reading
            channel_ids = {r.channel_id for r in readings_to_create}
            for channel_id in channel_ids:
                _dispatch_feed_rule_evaluation.delay(channel_id)

    if consecutive_failures >= len(provider.endpoints or [1]):
        _notify_admin_feed_failure(provider)


# ---------------------------------------------------------------------------
# Tenant feed subscription polling
# ---------------------------------------------------------------------------

@shared_task(name='feeds.poll_tenant_subscriptions')
def poll_tenant_subscriptions() -> None:
    """Dispatch poll tasks for all active TenantFeedSubscriptions that are due.

    Ref: SPEC.md § Feature: Feed Providers — Tenant-scope feeds
    """
    from .models import TenantFeedSubscription

    now = timezone.now()
    subscriptions = TenantFeedSubscription.objects.filter(
        is_active=True,
        provider__is_active=True,
        provider__scope='tenant',
    ).select_related('provider')

    dispatched = 0
    for sub in subscriptions:
        if sub.last_polled_at is None:
            due = True
        else:
            due = (now - sub.last_polled_at).total_seconds() >= sub.provider.poll_interval_seconds
        if due:
            poll_single_subscription.delay(sub.pk)
            dispatched += 1

    if dispatched:
        logger.info('Dispatched %d tenant feed subscription poll tasks', dispatched)


@shared_task(name='feeds.poll_single_subscription', max_retries=3, default_retry_delay=30)
def poll_single_subscription(subscription_pk: int) -> None:
    """Poll a single TenantFeedSubscription and store FeedReadings.

    Same logic as poll_single_provider but uses tenant credentials from
    the subscription's encrypted credentials field.

    Ref: SPEC.md § Feature: Feed Providers — Tenant-scope feeds
    """
    from .models import FeedChannel, FeedReading, TenantFeedSubscription

    now = timezone.now()

    try:
        sub = TenantFeedSubscription.objects.select_related('provider', 'tenant').get(
            pk=subscription_pk, is_active=True
        )
    except TenantFeedSubscription.DoesNotExist:
        logger.warning('TenantFeedSubscription %d not found or inactive', subscription_pk)
        return

    provider = sub.provider
    subscribed_ids = set(sub.subscribed_channel_ids or [])

    for endpoint_cfg in (provider.endpoints or []):
        path = endpoint_cfg.get('path', '')
        method = endpoint_cfg.get('method', 'GET').upper()
        url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')
        response_root_jsonpath = endpoint_cfg.get('response_root_jsonpath')
        dimension_key = endpoint_cfg.get('dimension_key')
        channel_defs = endpoint_cfg.get('channels', [])

        try:
            headers = _build_auth_headers(provider, credentials=sub.credentials)
            resp = http_requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except http_requests.RequestException as exc:
            logger.error('TenantFeedSubscription %d poll failed: %s', subscription_pk, exc)
            sub.last_polled_at = now
            sub.last_poll_status = TenantFeedSubscription.PollStatus.ERROR
            sub.last_poll_error = str(exc)
            sub.save(update_fields=['last_polled_at', 'last_poll_status', 'last_poll_error'])
            return

        rows = []
        if response_root_jsonpath:
            try:
                rows = [m.value for m in jp_parse(response_root_jsonpath).find(data)]
            except Exception as exc:
                logger.error('TenantFeedSubscription %d JSONPath error: %s', subscription_pk, exc)
                return
        else:
            rows = [data]

        readings_to_create = []
        for row in rows:
            dim_value = None
            if dimension_key:
                dim_value = str(row.get(dimension_key, '')).strip() or None

            for ch_def in channel_defs:
                key = ch_def.get('key')
                value_jsonpath = ch_def.get('value_jsonpath')
                if not key or not value_jsonpath:
                    continue

                try:
                    matches = jp_parse(value_jsonpath).find(row)
                except Exception:
                    continue
                if not matches:
                    continue

                channel, _ = FeedChannel.objects.get_or_create(
                    provider=provider,
                    key=key,
                    dimension_value=dim_value,
                    defaults={
                        'label': ch_def.get('label', key),
                        'unit': ch_def.get('unit', ''),
                        'data_type': ch_def.get('data_type', FeedChannel.DataType.NUMERIC),
                        'is_active': True,
                    },
                )

                # Only store readings for channels the tenant subscribed to
                if subscribed_ids and channel.pk not in subscribed_ids:
                    continue

                readings_to_create.append(FeedReading(
                    channel=channel,
                    value=matches[0].value,
                    timestamp=now,
                    fetched_at=now,
                ))

        if readings_to_create:
            FeedReading.objects.bulk_create(readings_to_create, ignore_conflicts=True)
            channel_ids = {r.channel_id for r in readings_to_create}
            for channel_id in channel_ids:
                _dispatch_feed_rule_evaluation.delay(channel_id)

    sub.last_polled_at = now
    sub.last_poll_status = TenantFeedSubscription.PollStatus.OK
    sub.last_poll_error = None
    sub.save(update_fields=['last_polled_at', 'last_poll_status', 'last_poll_error'])


# ---------------------------------------------------------------------------
# Rule evaluation dispatch
# ---------------------------------------------------------------------------

@shared_task(name='feeds.dispatch_feed_rule_evaluation')
def _dispatch_feed_rule_evaluation(channel_id: int) -> None:
    """Dispatch rule evaluation for all rules referencing a FeedChannel.

    Mirrors the RuleStreamIndex pattern used in the ingestion app — looks up
    FeedChannelRuleIndex to find only the rules that reference this channel,
    then dispatches evaluate_rule tasks for each.

    Ref: SPEC.md § Feature: Rule Evaluation Engine — FeedChannelRuleIndex
    """
    from .models import FeedChannelRuleIndex

    rule_ids = list(
        FeedChannelRuleIndex.objects
        .filter(channel_id=channel_id, rule__is_active=True)
        .values_list('rule_id', flat=True)
    )

    if not rule_ids:
        return

    for rule_id in rule_ids:
        evaluate_rule.delay(rule_id)

    logger.debug(
        'Dispatched rule evaluation for %d rule(s) on FeedChannel %d',
        len(rule_ids), channel_id,
    )


# ---------------------------------------------------------------------------
# Reference value beat evaluator
# ---------------------------------------------------------------------------

@shared_task(name='feeds.evaluate_reference_value_rules')
def evaluate_reference_value_rules() -> None:
    """Re-evaluate all active rules that have reference_value conditions.

    Runs every 5 minutes (configured in Celery beat schedule). This catches
    TOU boundary changes — when the time of day shifts from off-peak to peak,
    rules that reference the tariff rate need to be re-evaluated even though
    no stream or feed reading has arrived.

    Only dispatches evaluation for rules whose ONLY condition source is
    reference_value — rules that also have stream or feed_channel conditions
    are already evaluated on incoming readings.

    Ref: SPEC.md § Feature: Reference Datasets — Rule integration
    """
    # Find rules that have at least one reference_value condition and are active
    rule_ids_with_ref = set(
        RuleCondition.objects
        .filter(
            condition_type=RuleCondition.ConditionType.REFERENCE_VALUE,
            group__rule__is_active=True,
        )
        .values_list('group__rule_id', flat=True)
    )

    if not rule_ids_with_ref:
        return

    dispatched = 0
    for rule_id in rule_ids_with_ref:
        evaluate_rule.delay(rule_id)
        dispatched += 1

    logger.info(
        'evaluate_reference_value_rules: dispatched %d rule evaluation task(s)',
        dispatched,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_auth_headers(provider, credentials: dict | None = None) -> dict:
    """Build request headers for the provider's auth type.

    Only api_key_header and bearer_token are currently handled here.
    OAuth2 types will be wired up when a scope=tenant OAuth2 provider is
    registered (uses the same auth_handlers pattern as integrations app).
    """
    from .models import FeedProvider

    creds = credentials or {}

    if provider.auth_type == FeedProvider.AuthType.NONE:
        return {}

    if provider.auth_type == FeedProvider.AuthType.API_KEY_HEADER:
        header_name = creds.get('header_name', 'X-API-Key')
        return {header_name: creds.get('api_key', '')}

    if provider.auth_type == FeedProvider.AuthType.BEARER_TOKEN:
        return {'Authorization': f'Bearer {creds.get("token", "")}'}

    logger.warning(
        'FeedProvider %d: auth_type "%s" not yet handled in _build_auth_headers',
        provider.pk, provider.auth_type,
    )
    return {}


def _notify_admin_feed_failure(provider) -> None:
    """Log a warning when a provider fails all endpoints on a poll cycle.

    Full platform notification (to That Place Admins) will be wired up in
    Sprint 23 when the notification event registry is built.
    """
    logger.error(
        'FeedProvider "%s" (pk=%d) failed on all endpoints. '
        'That Place Admins should be notified.',
        provider.name, provider.pk,
    )
