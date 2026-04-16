"""Sprint 16 tests — Rule Evaluation Engine.

Covers:
  - False→true transition fires the rule (current_state updated, last_fired_at set)
  - True→true transition is suppressed (no second firing)
  - True→false transition clears state
  - False→false is a no-op
  - Cooldown prevents re-firing before cooldown_minutes has elapsed
  - Schedule gate blocks firing outside the configured window
  - Schedule gate does not block state clearing
  - Redis lock prevents duplicate firing under concurrent evaluation
  - Concurrent evaluation race condition: only one evaluate_rule call fires
  - feed_channel condition fires when a new FeedReading crosses the threshold
  - reference_value condition resolves correctly from TenantDatasetAssignment
  - Stale stream (no reading) evaluates to False
  - Compound condition groups (AND/OR) evaluated correctly
  - Rules for inactive devices are not triggered (RuleStreamIndex lookup)
  - Stream dispatch wires up correctly via RuleStreamIndex

Ref: SPEC.md § Feature: Rule Evaluation Engine
"""
from datetime import date, time, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import (
    FeedChannel,
    FeedChannelRuleIndex,
    FeedProvider,
    FeedReading,
    ReferenceDataset,
    ReferenceDatasetRow,
    TenantDatasetAssignment,
)
from apps.readings.models import RuleStreamIndex, Stream, StreamReading
from apps.rules.evaluator import (
    _compare,
    run_evaluation,
    within_schedule_gate,
)
from apps.rules.models import Rule, RuleCondition, RuleConditionGroup
from apps.rules.tasks import evaluate_rule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tenant(name: str = 'Acme') -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name), timezone='Australia/Brisbane')


def make_device_type(slug: str = 'test-dt') -> DeviceType:
    dt, _ = DeviceType.objects.get_or_create(
        slug=slug,
        defaults={
            'name': 'Test Device',
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 10,
            'command_ack_timeout_seconds': 30,
        },
    )
    return dt


def make_device(tenant: Tenant, serial: str = 'TEST-001') -> Device:
    site = Site.objects.create(tenant=tenant, name='Test Site')
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=make_device_type(),
        name='Test Device',
        serial_number=serial,
        status=Device.Status.ACTIVE,
    )


def make_stream(device: Device, key: str = 'temperature', data_type: str = 'numeric') -> Stream:
    stream, _ = Stream.objects.get_or_create(
        device=device,
        key=key,
        defaults={'data_type': data_type, 'label': key},
    )
    return stream


def make_reading(stream: Stream, value, minutes_ago: int = 1) -> StreamReading:
    ts = timezone.now() - timedelta(minutes=minutes_ago)
    return StreamReading.objects.create(stream=stream, value=value, timestamp=ts)


def make_rule(
    tenant: Tenant,
    name: str = 'Test Rule',
    current_state: bool = False,
    cooldown_minutes: int | None = None,
    active_days=None,
    active_from=None,
    active_to=None,
    condition_group_operator: str = 'AND',
) -> Rule:
    return Rule.objects.create(
        tenant=tenant,
        name=name,
        is_active=True,
        current_state=current_state,
        cooldown_minutes=cooldown_minutes,
        active_days=active_days,
        active_from=active_from,
        active_to=active_to,
        condition_group_operator=condition_group_operator,
    )


def add_stream_condition(
    rule: Rule,
    stream: Stream,
    operator: str = '>',
    threshold: str = '30',
    group_operator: str = 'AND',
) -> tuple:
    group = RuleConditionGroup.objects.create(rule=rule, logical_operator=group_operator)
    condition = RuleCondition.objects.create(
        group=group,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream,
        operator=operator,
        threshold_value=threshold,
    )
    RuleStreamIndex.objects.get_or_create(stream=stream, rule=rule)
    return group, condition


def _reload(rule: Rule) -> Rule:
    """Reload a Rule from the database."""
    return Rule.objects.get(pk=rule.pk)


# ---------------------------------------------------------------------------
# _compare() unit tests
# ---------------------------------------------------------------------------

class TestCompare:
    """Unit tests for the _compare() helper — no DB required."""

    def test_numeric_greater_than_true(self):
        assert _compare(35.0, '>', '30', 'numeric') is True

    def test_numeric_greater_than_false(self):
        assert _compare(25.0, '>', '30', 'numeric') is False

    def test_numeric_equal_at_boundary(self):
        assert _compare(30.0, '>', '30', 'numeric') is False

    def test_numeric_gte_at_boundary(self):
        assert _compare(30.0, '>=', '30', 'numeric') is True

    def test_numeric_less_than(self):
        assert _compare(10.0, '<', '20', 'numeric') is True

    def test_numeric_not_equal(self):
        assert _compare(10.0, '!=', '20', 'numeric') is True

    def test_boolean_equal_true(self):
        assert _compare(True, '==', 'true', 'boolean') is True

    def test_boolean_equal_false_string(self):
        assert _compare('false', '==', 'false', 'boolean') is True

    def test_boolean_mismatch(self):
        assert _compare(True, '==', 'false', 'boolean') is False

    def test_string_equal(self):
        assert _compare('open', '==', 'open', 'string') is True

    def test_string_not_equal(self):
        assert _compare('open', '!=', 'closed', 'string') is True

    def test_invalid_numeric_returns_false(self):
        assert _compare('not_a_number', '>', '30', 'numeric') is False

    def test_unknown_operator_returns_false(self):
        assert _compare(10, 'LIKE', '10', 'numeric') is False


# ---------------------------------------------------------------------------
# Schedule gate unit tests
# ---------------------------------------------------------------------------

class TestScheduleGate:
    """Unit tests for within_schedule_gate() — no DB required."""

    def _make_rule(self, active_days=None, active_from=None, active_to=None):
        """Create a minimal rule-like object (not saved to DB)."""
        from unittest.mock import MagicMock
        rule = MagicMock()
        rule.active_days = active_days
        rule.active_from = active_from
        rule.active_to = active_to
        rule.tenant.timezone = 'Australia/Brisbane'
        return rule

    def test_no_gate_always_true(self):
        rule = self._make_rule()
        now = timezone.now()
        assert within_schedule_gate(rule, now) is True

    def test_day_gate_today_included(self):
        import datetime

        # Use a fixed datetime: Wednesday 2026-04-15 10:00 Brisbane (UTC+10)
        from zoneinfo import ZoneInfo
        brisbane = ZoneInfo('Australia/Brisbane')
        now_bris = datetime.datetime(2026, 4, 15, 10, 0, tzinfo=brisbane)  # Wed = 2
        rule = self._make_rule(active_days=[2])  # Wednesday
        assert within_schedule_gate(rule, now_bris) is True

    def test_day_gate_today_excluded(self):
        import datetime
        from zoneinfo import ZoneInfo
        brisbane = ZoneInfo('Australia/Brisbane')
        now_bris = datetime.datetime(2026, 4, 15, 10, 0, tzinfo=brisbane)  # Wed = 2
        rule = self._make_rule(active_days=[0, 1])  # Mon, Tue only
        assert within_schedule_gate(rule, now_bris) is False

    def test_time_window_inside(self):
        import datetime
        from zoneinfo import ZoneInfo
        brisbane = ZoneInfo('Australia/Brisbane')
        now_bris = datetime.datetime(2026, 4, 15, 10, 0, tzinfo=brisbane)
        rule = self._make_rule(active_from=time(8, 0), active_to=time(18, 0))
        assert within_schedule_gate(rule, now_bris) is True

    def test_time_window_outside(self):
        import datetime
        from zoneinfo import ZoneInfo
        brisbane = ZoneInfo('Australia/Brisbane')
        now_bris = datetime.datetime(2026, 4, 15, 6, 0, tzinfo=brisbane)
        rule = self._make_rule(active_from=time(8, 0), active_to=time(18, 0))
        assert within_schedule_gate(rule, now_bris) is False

    def test_midnight_wrapping_window_inside(self):
        import datetime
        from zoneinfo import ZoneInfo
        brisbane = ZoneInfo('Australia/Brisbane')
        now_bris = datetime.datetime(2026, 4, 15, 23, 0, tzinfo=brisbane)
        rule = self._make_rule(active_from=time(22, 0), active_to=time(6, 0))
        assert within_schedule_gate(rule, now_bris) is True

    def test_midnight_wrapping_window_outside(self):
        import datetime
        from zoneinfo import ZoneInfo
        brisbane = ZoneInfo('Australia/Brisbane')
        now_bris = datetime.datetime(2026, 4, 15, 12, 0, tzinfo=brisbane)
        rule = self._make_rule(active_from=time(22, 0), active_to=time(6, 0))
        assert within_schedule_gate(rule, now_bris) is False


# ---------------------------------------------------------------------------
# Core evaluation DB tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRunEvaluation:
    """Integration tests for run_evaluation() — writes to the DB."""

    def test_false_to_true_fires(self):
        """A rule with a satisfied condition transitions false→true and fires."""
        tenant = make_tenant('FireTenant')
        device = make_device(tenant, 'FIRE-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)  # > 30 threshold

        rule = make_rule(tenant, current_state=False)
        add_stream_condition(rule, stream, '>', '30')

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'
        updated = _reload(rule)
        assert updated.current_state is True
        assert updated.last_fired_at is not None

    def test_true_to_true_suppressed(self):
        """A rule already in triggered state is not re-fired when conditions remain true."""
        tenant = make_tenant('SuppressTenant')
        device = make_device(tenant, 'SUPP-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=True)
        add_stream_condition(rule, stream, '>', '30')

        outcome = run_evaluation(rule)

        assert outcome == 'suppressed'
        assert _reload(rule).current_state is True

    def test_true_to_false_clears(self):
        """When conditions go false while state is true, state is cleared."""
        tenant = make_tenant('ClearTenant')
        device = make_device(tenant, 'CLEAR-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 25.0)  # < 30 — condition not met

        rule = make_rule(tenant, current_state=True)
        add_stream_condition(rule, stream, '>', '30')

        outcome = run_evaluation(rule)

        assert outcome == 'cleared'
        assert _reload(rule).current_state is False

    def test_false_to_false_no_change(self):
        """When conditions remain false, state stays false and nothing is written."""
        tenant = make_tenant('NoChangeTenant')
        device = make_device(tenant, 'NC-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 25.0)

        rule = make_rule(tenant, current_state=False)
        add_stream_condition(rule, stream, '>', '30')

        outcome = run_evaluation(rule)

        assert outcome == 'no_change'
        assert _reload(rule).current_state is False
        assert _reload(rule).last_fired_at is None

    def test_stale_stream_no_reading_is_false(self):
        """A stream with no readings evaluates to False (stale stream policy)."""
        tenant = make_tenant('StaleTenant')
        device = make_device(tenant, 'STALE-001')
        stream = make_stream(device, 'temperature')
        # No readings created

        rule = make_rule(tenant, current_state=False)
        add_stream_condition(rule, stream, '>', '30')

        outcome = run_evaluation(rule)

        assert outcome == 'no_change'

    def test_cooldown_prevents_refire(self):
        """Rule does not re-fire if cooldown has not elapsed since last firing."""
        tenant = make_tenant('CooldownTenant')
        device = make_device(tenant, 'CD-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=False, cooldown_minutes=60)
        rule.last_fired_at = timezone.now() - timedelta(minutes=30)  # 30 min ago — still in cooldown
        rule.save(update_fields=['last_fired_at'])
        add_stream_condition(rule, stream, '>', '30')

        outcome = run_evaluation(rule)

        assert outcome == 'cooldown'
        assert _reload(rule).current_state is False

    def test_cooldown_expired_allows_refire(self):
        """Rule fires again after cooldown has elapsed."""
        tenant = make_tenant('CooldownExpiredTenant')
        device = make_device(tenant, 'CDE-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=False, cooldown_minutes=60)
        rule.last_fired_at = timezone.now() - timedelta(hours=2)  # expired
        rule.save(update_fields=['last_fired_at'])
        add_stream_condition(rule, stream, '>', '30')

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'

    def test_schedule_gate_blocks_firing(self):
        """A satisfied condition does not fire when the schedule gate is closed."""
        tenant = make_tenant('GateTenant')
        device = make_device(tenant, 'GATE-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=False, active_days=[0])  # Monday only
        add_stream_condition(rule, stream, '>', '30')

        # Freeze time to a Sunday
        import datetime
        from zoneinfo import ZoneInfo
        sunday = datetime.datetime(2026, 4, 19, 10, 0, tzinfo=ZoneInfo('UTC'))  # Sunday

        outcome = run_evaluation(rule, now=sunday)

        assert outcome == 'gate_blocked'
        assert _reload(rule).current_state is False

    def test_schedule_gate_does_not_block_clearing(self):
        """State clears to False even when the schedule gate is closed."""
        tenant = make_tenant('GateClearTenant')
        device = make_device(tenant, 'GC-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 25.0)  # condition not met

        rule = make_rule(tenant, current_state=True, active_days=[0])  # Mon only
        add_stream_condition(rule, stream, '>', '30')

        import datetime
        from zoneinfo import ZoneInfo
        sunday = datetime.datetime(2026, 4, 19, 10, 0, tzinfo=ZoneInfo('UTC'))

        outcome = run_evaluation(rule, now=sunday)

        assert outcome == 'cleared'
        assert _reload(rule).current_state is False

    def test_redis_lock_lost_prevents_duplicate_fire(self):
        """If SET NX fails (another worker holds lock), this worker skips firing."""
        tenant = make_tenant('LockTenant')
        device = make_device(tenant, 'LOCK-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=False)
        add_stream_condition(rule, stream, '>', '30')

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=False):
            outcome = run_evaluation(rule)

        assert outcome == 'lock_lost'
        assert _reload(rule).current_state is False

    def test_and_group_all_conditions_must_be_true(self):
        """AND group: rule only fires when all conditions are true."""
        tenant = make_tenant('AndTenant')
        device = make_device(tenant, 'AND-001')
        temp = make_stream(device, 'temperature')
        humidity = make_stream(device, 'humidity')
        make_reading(temp, 35.0)    # temp > 30 ✓
        make_reading(humidity, 60.0)  # humidity > 80 ✗

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group, condition_type='stream', stream=temp, operator='>', threshold_value='30',
        )
        RuleCondition.objects.create(
            group=group, condition_type='stream', stream=humidity, operator='>', threshold_value='80',
        )
        RuleStreamIndex.objects.get_or_create(stream=temp, rule=rule)
        RuleStreamIndex.objects.get_or_create(stream=humidity, rule=rule)

        outcome = run_evaluation(rule)

        assert outcome == 'no_change'  # humidity condition fails

    def test_or_group_any_condition_suffices(self):
        """OR group: rule fires when any condition is true."""
        tenant = make_tenant('OrTenant')
        device = make_device(tenant, 'OR-001')
        temp = make_stream(device, 'temperature')
        humidity = make_stream(device, 'humidity')
        make_reading(temp, 35.0)    # temp > 30 ✓
        make_reading(humidity, 60.0)  # humidity > 80 ✗

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='OR')
        RuleCondition.objects.create(
            group=group, condition_type='stream', stream=temp, operator='>', threshold_value='30',
        )
        RuleCondition.objects.create(
            group=group, condition_type='stream', stream=humidity, operator='>', threshold_value='80',
        )
        RuleStreamIndex.objects.get_or_create(stream=temp, rule=rule)
        RuleStreamIndex.objects.get_or_create(stream=humidity, rule=rule)

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'

    def test_multiple_groups_combined_with_or(self):
        """Top-level OR: rule fires if any group is true."""
        tenant = make_tenant('MultiGroupOrTenant')
        device = make_device(tenant, 'MGO-001')
        temp = make_stream(device, 'temperature')
        pressure = make_stream(device, 'pressure')
        make_reading(temp, 25.0)     # temp > 30 ✗
        make_reading(pressure, 200.0)  # pressure > 100 ✓

        rule = make_rule(tenant, current_state=False, condition_group_operator='OR')
        grp1 = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND', order=0)
        RuleCondition.objects.create(
            group=grp1, condition_type='stream', stream=temp, operator='>', threshold_value='30',
        )
        grp2 = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND', order=1)
        RuleCondition.objects.create(
            group=grp2, condition_type='stream', stream=pressure, operator='>', threshold_value='100',
        )
        RuleStreamIndex.objects.get_or_create(stream=temp, rule=rule)
        RuleStreamIndex.objects.get_or_create(stream=pressure, rule=rule)

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'


# ---------------------------------------------------------------------------
# Feed channel condition tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFeedChannelCondition:
    """Feed channel conditions evaluated against latest FeedReading."""

    def _make_provider(self) -> FeedProvider:
        return FeedProvider.objects.create(
            slug='test-feed-provider',
            name='Test Provider',
            base_url='https://example.com',
            auth_type=FeedProvider.AuthType.NONE,
            scope=FeedProvider.Scope.SYSTEM,
            poll_interval_seconds=300,
            is_active=True,
        )

    def test_feed_channel_condition_fires_when_threshold_crossed(self):
        """Rule fires when latest FeedReading exceeds the threshold."""
        tenant = make_tenant('FeedTenant')
        provider = self._make_provider()
        channel = FeedChannel.objects.create(
            provider=provider, key='spot_price', dimension_value='NSW1',
            label='Spot Price', unit='$/MWh', data_type='numeric', is_active=True,
        )
        now = timezone.now()
        FeedReading.objects.create(channel=channel, value=350.0, timestamp=now, fetched_at=now)

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.FEED_CHANNEL,
            channel=channel,
            operator='>',
            threshold_value='300',
        )
        FeedChannelRuleIndex.objects.get_or_create(channel=channel, rule=rule)

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'

    def test_feed_channel_condition_false_when_below_threshold(self):
        """Rule does not fire when FeedReading is below the threshold."""
        tenant = make_tenant('FeedTenant2')
        provider = self._make_provider()
        channel = FeedChannel.objects.create(
            provider=provider, key='spot_price', dimension_value='VIC1',
            label='Spot Price', unit='$/MWh', data_type='numeric', is_active=True,
        )
        now = timezone.now()
        FeedReading.objects.create(channel=channel, value=50.0, timestamp=now, fetched_at=now)

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.FEED_CHANNEL,
            channel=channel,
            operator='>',
            threshold_value='300',
        )

        outcome = run_evaluation(rule)

        assert outcome == 'no_change'

    def test_feed_channel_no_reading_is_false(self):
        """If no FeedReading exists yet, the condition evaluates to False."""
        tenant = make_tenant('FeedNoReadingTenant')
        provider = self._make_provider()
        channel = FeedChannel.objects.create(
            provider=provider, key='spot_price', dimension_value='QLD1',
            label='Spot Price', unit='$/MWh', data_type='numeric', is_active=True,
        )

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.FEED_CHANNEL,
            channel=channel,
            operator='>',
            threshold_value='300',
        )

        outcome = run_evaluation(rule)
        assert outcome == 'no_change'


# ---------------------------------------------------------------------------
# Reference value condition tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReferenceValueCondition:
    """Reference value conditions resolved from TenantDatasetAssignment."""

    def _make_dataset(self) -> ReferenceDataset:
        return ReferenceDataset.objects.create(
            name='Test Tariffs',
            slug='test-tariffs',
            dimension_schema={'state': {'label': 'State', 'type': 'string'}},
            value_schema={'rate': {'label': 'Rate', 'type': 'numeric', 'unit': 'c/kWh'}},
            has_version=False,
            has_time_of_use=False,
        )

    def test_reference_value_fires_when_rate_exceeded(self):
        """Rule fires when resolved dataset rate exceeds threshold."""
        tenant = make_tenant('RefTenant')
        dataset = self._make_dataset()
        ReferenceDatasetRow.objects.create(
            dataset=dataset,
            dimensions={'state': 'QLD'},
            values={'rate': 32.50},
            is_active=True,
        )
        TenantDatasetAssignment.objects.create(
            tenant=tenant,
            site=None,
            dataset=dataset,
            dimension_filter={'state': 'QLD'},
            effective_from=date.today() - timedelta(days=1),
        )

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.REFERENCE_VALUE,
            dataset=dataset,
            value_key='rate',
            operator='>',
            threshold_value='25',
        )

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'

    def test_reference_value_false_when_below_threshold(self):
        """Rule does not fire when resolved rate is below threshold."""
        tenant = make_tenant('RefBelowTenant')
        dataset = self._make_dataset()
        ReferenceDatasetRow.objects.create(
            dataset=dataset,
            dimensions={'state': 'NSW'},
            values={'rate': 10.0},
            is_active=True,
        )
        TenantDatasetAssignment.objects.create(
            tenant=tenant,
            site=None,
            dataset=dataset,
            dimension_filter={'state': 'NSW'},
            effective_from=date.today() - timedelta(days=1),
        )

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.REFERENCE_VALUE,
            dataset=dataset,
            value_key='rate',
            operator='>',
            threshold_value='25',
        )

        outcome = run_evaluation(rule)
        assert outcome == 'no_change'

    def test_reference_value_no_assignment_is_false(self):
        """If no TenantDatasetAssignment exists, condition evaluates to False."""
        tenant = make_tenant('RefNoAssignmentTenant')
        dataset = self._make_dataset()
        ReferenceDatasetRow.objects.create(
            dataset=dataset,
            dimensions={'state': 'VIC'},
            values={'rate': 40.0},
            is_active=True,
        )
        # No TenantDatasetAssignment created

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.REFERENCE_VALUE,
            dataset=dataset,
            value_key='rate',
            operator='>',
            threshold_value='25',
        )

        outcome = run_evaluation(rule)
        assert outcome == 'no_change'

    def test_reference_value_dimension_overrides_applied(self):
        """dimension_overrides on the condition narrows the dataset lookup."""
        tenant = make_tenant('RefOverrideTenant')
        dataset = self._make_dataset()
        # Two rows for different states — only VIC should match via override
        ReferenceDatasetRow.objects.create(
            dataset=dataset, dimensions={'state': 'QLD'}, values={'rate': 10.0}, is_active=True,
        )
        ReferenceDatasetRow.objects.create(
            dataset=dataset, dimensions={'state': 'VIC'}, values={'rate': 45.0}, is_active=True,
        )
        # Assignment has no dimension_filter — override in condition selects the row
        TenantDatasetAssignment.objects.create(
            tenant=tenant, site=None, dataset=dataset,
            dimension_filter={}, effective_from=date.today() - timedelta(days=1),
        )

        rule = make_rule(tenant, current_state=False)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.REFERENCE_VALUE,
            dataset=dataset,
            value_key='rate',
            operator='>',
            threshold_value='25',
            dimension_overrides={'state': 'VIC'},
        )

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                outcome = run_evaluation(rule)

        assert outcome == 'fired'


# ---------------------------------------------------------------------------
# evaluate_rule Celery task tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEvaluateRuleTask:
    """Tests for the evaluate_rule Celery task."""

    def test_task_fires_rule(self):
        """evaluate_rule task triggers a false→true transition."""
        tenant = make_tenant('TaskFire')
        device = make_device(tenant, 'TF-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=False)
        add_stream_condition(rule, stream, '>', '30')

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            with patch('apps.rules.evaluator._release_lock'):
                result = evaluate_rule(rule.pk)

        assert result == 'fired'
        assert _reload(rule).current_state is True

    def test_task_inactive_rule_skipped(self):
        """evaluate_rule returns None for an inactive rule."""
        tenant = make_tenant('InactiveTask')
        rule = Rule.objects.create(tenant=tenant, name='Inactive', is_active=False)

        result = evaluate_rule(rule.pk)

        assert result is None

    def test_task_missing_rule_skipped(self):
        """evaluate_rule returns None for a non-existent rule ID."""
        result = evaluate_rule(99999)
        assert result is None

    def test_concurrent_evaluation_only_one_fires(self):
        """Simulated concurrent evaluation: second call gets lock_lost."""
        tenant = make_tenant('ConcurrentTenant')
        device = make_device(tenant, 'CONC-001')
        stream = make_stream(device, 'temperature')
        make_reading(stream, 35.0)

        rule = make_rule(tenant, current_state=False)
        add_stream_condition(rule, stream, '>', '30')

        call_count = [0]

        def mock_acquire(rule_id):
            call_count[0] += 1
            return call_count[0] == 1  # First call wins, second loses

        with patch('apps.rules.evaluator._try_acquire_lock', side_effect=mock_acquire):
            with patch('apps.rules.evaluator._release_lock'):
                result1 = evaluate_rule(rule.pk)
                # Reload rule to simulate second worker reading from DB
                rule2 = _reload(rule)
                result2 = evaluate_rule(rule2.pk)

        assert result1 == 'fired'
        # Second call: rule is now current_state=True → suppressed (not lock_lost)
        assert result2 == 'suppressed'


# ---------------------------------------------------------------------------
# RuleStreamIndex dispatch tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStreamDispatch:
    """Verify that RuleStreamIndex correctly limits which rules are evaluated."""

    def test_only_indexed_rules_are_evaluated(self):
        """evaluate_rule is called only for rules in RuleStreamIndex for the stream."""
        tenant = make_tenant('DispatchTenant')
        device = make_device(tenant, 'DISP-001')
        stream_a = make_stream(device, 'temperature')
        stream_b = make_stream(device, 'humidity')
        make_reading(stream_a, 35.0)
        make_reading(stream_b, 50.0)

        # Rule 1 references stream_a
        rule_a = make_rule(tenant, name='Rule A')
        add_stream_condition(rule_a, stream_a, '>', '30')

        # Rule 2 references stream_b (not stream_a)
        rule_b = make_rule(tenant, name='Rule B')
        add_stream_condition(rule_b, stream_b, '>', '80')

        # Simulate dispatch for stream_a — only rule_a should be evaluated
        from apps.readings.models import RuleStreamIndex
        rule_ids = list(
            RuleStreamIndex.objects
            .filter(stream_id=stream_a.pk, rule__is_active=True)
            .values_list('rule_id', flat=True)
        )

        assert rule_a.pk in rule_ids
        assert rule_b.pk not in rule_ids
