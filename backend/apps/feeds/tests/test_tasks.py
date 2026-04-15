"""Cross-tenant isolation tests for Celery beat tasks in the feeds app.

Verifies that:
  - poll_single_subscription updates only the polled subscription's state
  - evaluate_reference_value_rules dispatches evaluation for all active
    reference_value rules regardless of tenant (global dispatch task)

Ref: security_risks.md § SR-03 — Tenant Isolation in Celery Beat Tasks
"""
from unittest.mock import MagicMock, call, patch

import pytest
from django.utils.text import slugify

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import (
    FeedChannel,
    FeedProvider,
    FeedReading,
    TenantFeedSubscription,
)
from apps.rules.models import Rule, RuleCondition, RuleConditionGroup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_feed_provider() -> FeedProvider:
    return FeedProvider.objects.create(
        name='Tenant ISO Provider',
        slug='tenant-iso-provider',
        base_url='https://api.tenant-iso.example.com',
        auth_type=FeedProvider.AuthType.API_KEY_HEADER,
        auth_param_schema=[
            {'key': 'header_name', 'label': 'Header', 'type': 'text', 'required': True},
            {'key': 'api_key', 'label': 'API Key', 'type': 'password', 'required': True},
        ],
        scope=FeedProvider.Scope.TENANT,
        poll_interval_seconds=300,
        endpoints=[
            {
                'path': '/data/',
                'method': 'GET',
                'channels': [
                    {
                        'key': 'price',
                        'label': 'Price',
                        'unit': '$/MWh',
                        'data_type': 'numeric',
                        'value_jsonpath': '$.price',
                    },
                ],
            },
        ],
    )


def make_subscription(tenant: Tenant, provider: FeedProvider) -> TenantFeedSubscription:
    channel, _ = FeedChannel.objects.get_or_create(
        provider=provider,
        key='price',
        dimension_value=None,
        defaults={
            'label': 'Price',
            'unit': '$/MWh',
            'data_type': FeedChannel.DataType.NUMERIC,
        },
    )
    sub = TenantFeedSubscription.objects.create(
        tenant=tenant,
        provider=provider,
        credentials={'header_name': 'X-API-Key', 'api_key': f'key-{tenant.slug}'},
        subscribed_channel_ids=[channel.pk],
        is_active=True,
    )
    return sub


def make_rule_with_reference_condition(tenant: Tenant, name: str) -> Rule:
    """Create an active Rule with a reference_value RuleCondition."""
    from apps.feeds.models import ReferenceDataset

    dataset, _ = ReferenceDataset.objects.get_or_create(
        slug=f'test-dataset-{tenant.slug}',
        defaults={
            'name': f'Test Dataset {tenant.slug}',
            'dimension_schema': [{'key': 'region', 'label': 'Region', 'type': 'string'}],
            'value_schema': [{'key': 'rate', 'label': 'Rate', 'type': 'numeric', 'unit': 'c/kWh'}],
        },
    )
    rule = Rule.objects.create(tenant=tenant, name=name, is_active=True)
    group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    RuleCondition.objects.create(
        group=group,
        condition_type=RuleCondition.ConditionType.REFERENCE_VALUE,
        operator='>',
        threshold_value='10',
    )
    return rule


# ---------------------------------------------------------------------------
# poll_single_subscription — cross-tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPollSingleSubscriptionCrossTenant:
    """poll_single_subscription must only update its own subscription's state."""

    def _mock_response(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'price': 85.50}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_only_polled_subscription_last_polled_at_updated(self):
        """Polling sub_a must not update sub_b.last_polled_at."""
        from apps.feeds.tasks import poll_single_subscription

        provider = make_tenant_feed_provider()
        sub_a = make_subscription(make_tenant('SubIsoA'), provider)
        sub_b = make_subscription(make_tenant('SubIsoB'), provider)

        assert sub_b.last_polled_at is None

        with patch('apps.feeds.tasks.http_requests.request',
                   return_value=self._mock_response()):
            poll_single_subscription(sub_a.pk)

        sub_a.refresh_from_db()
        sub_b.refresh_from_db()

        assert sub_a.last_polled_at is not None
        assert sub_a.last_poll_status == TenantFeedSubscription.PollStatus.OK
        assert sub_b.last_polled_at is None

    def test_readings_only_created_for_polled_tenant_channels(self):
        """FeedReadings created for sub_a must not be attributed to sub_b's channels."""
        from apps.feeds.tasks import poll_single_subscription

        tenant_a = make_tenant('ReadIsoA')
        tenant_b = make_tenant('ReadIsoB')
        provider = make_tenant_feed_provider()
        sub_a = make_subscription(tenant_a, provider)
        sub_b = make_subscription(tenant_b, provider)

        # Record the state of sub_b's subscribed channel readings before polling
        sub_b_channel_ids = set(sub_b.subscribed_channel_ids)
        readings_before = FeedReading.objects.filter(
            channel_id__in=sub_b_channel_ids
        ).count()

        with patch('apps.feeds.tasks.http_requests.request',
                   return_value=self._mock_response()):
            poll_single_subscription(sub_a.pk)

        # Total readings for sub_b's channels must not increase
        readings_after = FeedReading.objects.filter(
            channel_id__in=sub_b_channel_ids
        ).count()
        assert readings_after == readings_before

    def test_failure_on_sub_a_does_not_affect_sub_b(self):
        """An error polling sub_a must not mark sub_b as errored."""
        import requests as req_lib
        from apps.feeds.tasks import poll_single_subscription

        provider = make_tenant_feed_provider()
        sub_a = make_subscription(make_tenant('ErrIsoA'), provider)
        sub_b = make_subscription(make_tenant('ErrIsoB'), provider)

        with patch('apps.feeds.tasks.http_requests.request',
                   side_effect=req_lib.RequestException('timeout')):
            poll_single_subscription(sub_a.pk)

        sub_a.refresh_from_db()
        sub_b.refresh_from_db()

        assert sub_a.last_poll_status == TenantFeedSubscription.PollStatus.ERROR
        assert sub_b.last_poll_status is None


# ---------------------------------------------------------------------------
# evaluate_reference_value_rules — dispatch correctness across tenants
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEvaluateReferenceValueRules:
    """evaluate_reference_value_rules must dispatch evaluation for every active
    reference_value rule regardless of which tenant owns it."""

    def test_dispatches_for_all_tenants_rules(self):
        """Rules from Tenant A and Tenant B must both be dispatched."""
        from apps.feeds.tasks import evaluate_reference_value_rules

        tenant_a = make_tenant('DispIsoA')
        tenant_b = make_tenant('DispIsoB')
        rule_a = make_rule_with_reference_condition(tenant_a, 'Rule A')
        rule_b = make_rule_with_reference_condition(tenant_b, 'Rule B')

        with patch('apps.feeds.tasks.evaluate_rule') as mock_evaluate_rule:
            evaluate_reference_value_rules()

        dispatched_ids = {c.args[0] for c in mock_evaluate_rule.delay.call_args_list}
        assert rule_a.pk in dispatched_ids
        assert rule_b.pk in dispatched_ids

    def test_does_not_dispatch_inactive_rules(self):
        """Inactive rules must not be dispatched regardless of condition type."""
        from apps.feeds.tasks import evaluate_reference_value_rules

        tenant = make_tenant('InactiveDisp')
        active_rule = make_rule_with_reference_condition(tenant, 'Active')
        inactive_rule = make_rule_with_reference_condition(tenant, 'Inactive')
        inactive_rule.is_active = False
        inactive_rule.save(update_fields=['is_active'])

        with patch('apps.feeds.tasks.evaluate_rule') as mock_evaluate_rule:
            evaluate_reference_value_rules()

        dispatched_ids = {c.args[0] for c in mock_evaluate_rule.delay.call_args_list}
        assert active_rule.pk in dispatched_ids
        assert inactive_rule.pk not in dispatched_ids

    def test_rules_without_reference_conditions_not_dispatched(self):
        """Rules that have only stream conditions must not be dispatched by this task."""
        from apps.feeds.tasks import evaluate_reference_value_rules
        from apps.devices.models import DeviceType, Site
        from apps.readings.models import Stream

        tenant = make_tenant('NoRefDisp')
        ref_rule = make_rule_with_reference_condition(tenant, 'Has Ref Cond')

        # Build a rule with only a stream condition — no reference_value
        stream_rule = Rule.objects.create(tenant=tenant, name='Stream Only', is_active=True)
        site = Site.objects.create(tenant=tenant, name='Site')
        dt, _ = DeviceType.objects.get_or_create(
            slug='test-mqtt-noref',
            defaults={
                'name': 'Test MQTT',
                'connection_type': DeviceType.ConnectionType.MQTT,
                'is_push': True,
                'default_offline_threshold_minutes': 10,
                'command_ack_timeout_seconds': 30,
            },
        )
        device = Device.objects.create(
            tenant=tenant, site=site, device_type=dt,
            name='Dev', serial_number='NOREF-001',
            status=Device.Status.ACTIVE,
        )
        stream = Stream.objects.create(device=device, key='temp', label='Temp', unit='°C', data_type='numeric')
        group = RuleConditionGroup.objects.create(rule=stream_rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.STREAM,
            stream=stream,
            operator='>',
            threshold_value='25',
        )

        with patch('apps.feeds.tasks.evaluate_rule') as mock_evaluate_rule:
            evaluate_reference_value_rules()

        dispatched_ids = {c.args[0] for c in mock_evaluate_rule.delay.call_args_list}
        assert ref_rule.pk in dispatched_ids
        assert stream_rule.pk not in dispatched_ids
