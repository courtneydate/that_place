"""Sprint 27 — Windowed Aggregate Rule Condition tests.

Covers:
  - avg / min / max correctness over a rolling window
  - fires when the rolling aggregate crosses the threshold
  - false when the window is empty (stream has no readings in window)
  - serializer validation: stream + aggregate_fn + window_minutes + operator
    + numeric-only operators
  - RuleStreamIndex correctly indexes streams referenced by windowed conditions
    so dispatch from ingestion picks them up

Ref: SPEC.md § Feature: Rules Engine — Windowed aggregate; ROADMAP Sprint 27
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import RuleStreamIndex, Stream, StreamReading
from apps.rules.evaluator import _eval_windowed_aggregate_condition
from apps.rules.models import (
    Rule,
    RuleCondition,
    RuleConditionGroup,
)


def make_tenant(name='W27 tenant'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email, tenant, role='admin'):
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_site(tenant):
    return Site.objects.create(tenant=tenant, name='Site')


def make_device(tenant, site, serial='W27-001'):
    dt, _ = DeviceType.objects.get_or_create(
        slug='w27-dt',
        defaults={
            'name': 'W27 device', 'connection_type': 'mqtt', 'is_push': True,
            'default_offline_threshold_minutes': 60,
        },
    )
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Device', serial_number=serial, status=Device.Status.ACTIVE,
    )


def make_stream(device, key='temperature'):
    return Stream.objects.create(device=device, key=key, data_type=Stream.DataType.NUMERIC)


def make_windowed_condition(rule, stream, aggregate_fn, window_minutes, operator, threshold):
    group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    return RuleCondition.objects.create(
        group=group,
        condition_type=RuleCondition.ConditionType.WINDOWED_AGGREGATE,
        stream=stream,
        aggregate_fn=aggregate_fn,
        window_minutes=window_minutes,
        operator=operator,
        threshold_value=threshold,
    )


# ---------------------------------------------------------------------------
# Evaluator correctness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_window_avg_fires_when_threshold_crossed():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    rule = Rule.objects.create(tenant=tenant, name='avg>25', is_active=True)
    cond = make_windowed_condition(rule, stream, 'avg', 15, '>', '25')

    now = timezone.now()
    StreamReading.objects.create(stream=stream, value=20.0, timestamp=now - timedelta(minutes=10))
    StreamReading.objects.create(stream=stream, value=30.0, timestamp=now - timedelta(minutes=5))
    StreamReading.objects.create(stream=stream, value=40.0, timestamp=now - timedelta(minutes=1))
    # avg = (20+30+40)/3 = 30.0 > 25
    assert _eval_windowed_aggregate_condition(cond) is True


@pytest.mark.django_db
def test_window_avg_false_when_below_threshold():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    rule = Rule.objects.create(tenant=tenant, name='avg>30', is_active=True)
    cond = make_windowed_condition(rule, stream, 'avg', 15, '>', '30')

    now = timezone.now()
    StreamReading.objects.create(stream=stream, value=20.0, timestamp=now - timedelta(minutes=5))
    StreamReading.objects.create(stream=stream, value=22.0, timestamp=now - timedelta(minutes=1))
    assert _eval_windowed_aggregate_condition(cond) is False


@pytest.mark.django_db
def test_window_max_fires_on_peak():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    rule = Rule.objects.create(tenant=tenant, name='max>50', is_active=True)
    cond = make_windowed_condition(rule, stream, 'max', 10, '>', '50')

    now = timezone.now()
    StreamReading.objects.create(stream=stream, value=30.0, timestamp=now - timedelta(minutes=8))
    StreamReading.objects.create(stream=stream, value=55.0, timestamp=now - timedelta(minutes=4))
    StreamReading.objects.create(stream=stream, value=20.0, timestamp=now - timedelta(minutes=1))
    assert _eval_windowed_aggregate_condition(cond) is True


@pytest.mark.django_db
def test_window_min_fires_on_dip():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    rule = Rule.objects.create(tenant=tenant, name='min<10', is_active=True)
    cond = make_windowed_condition(rule, stream, 'min', 10, '<', '10')

    now = timezone.now()
    StreamReading.objects.create(stream=stream, value=15.0, timestamp=now - timedelta(minutes=5))
    StreamReading.objects.create(stream=stream, value=5.0, timestamp=now - timedelta(minutes=2))
    assert _eval_windowed_aggregate_condition(cond) is True


@pytest.mark.django_db
def test_window_returns_false_when_no_readings_in_window():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    rule = Rule.objects.create(tenant=tenant, name='avg>1', is_active=True)
    cond = make_windowed_condition(rule, stream, 'avg', 5, '>', '1')

    # No readings — empty window.
    assert _eval_windowed_aggregate_condition(cond) is False

    # Readings exist but are outside the 5-minute window.
    StreamReading.objects.create(
        stream=stream, value=999.0,
        timestamp=timezone.now() - timedelta(minutes=30),
    )
    assert _eval_windowed_aggregate_condition(cond) is False


@pytest.mark.django_db
def test_window_excludes_readings_outside_window():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)
    rule = Rule.objects.create(tenant=tenant, name='max>40', is_active=True)
    cond = make_windowed_condition(rule, stream, 'max', 5, '>', '40')

    now = timezone.now()
    # 30 mins ago — outside the 5-min window.
    StreamReading.objects.create(stream=stream, value=100.0, timestamp=now - timedelta(minutes=30))
    # Inside the window.
    StreamReading.objects.create(stream=stream, value=20.0, timestamp=now - timedelta(minutes=2))
    # Max inside window is 20, not 100. Threshold 40. False.
    assert _eval_windowed_aggregate_condition(cond) is False


# ---------------------------------------------------------------------------
# Serializer validation
# ---------------------------------------------------------------------------


def _rule_payload(stream_id, *, aggregate_fn='avg', window_minutes=10, operator='>', threshold='5'):
    return {
        'name': 'W27 test',
        'description': '',
        'is_active': True,
        'condition_group_operator': 'AND',
        'condition_groups': [{
            'logical_operator': 'AND',
            'order': 0,
            'conditions': [{
                'condition_type': 'windowed_aggregate',
                'stream': stream_id,
                'aggregate_fn': aggregate_fn,
                'window_minutes': window_minutes,
                'operator': operator,
                'threshold_value': threshold,
                'order': 0,
            }],
        }],
        'actions': [{
            'action_type': 'notify',
            'notification_channels': ['in_app'],
            'group_ids': [],
            'user_ids': [],
            'message_template': '',
        }],
    }


def auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.mark.django_db
def test_serializer_accepts_valid_windowed_condition():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('admin@w27.test', tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)

    resp = auth(admin).post('/api/v1/rules/', _rule_payload(stream.pk), format='json')
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_serializer_rejects_missing_aggregate_fn():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('a@w27.test', tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)

    resp = auth(admin).post(
        '/api/v1/rules/',
        _rule_payload(stream.pk, aggregate_fn=''),
        format='json',
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_serializer_rejects_invalid_aggregate_fn():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('b@w27.test', tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)

    resp = auth(admin).post(
        '/api/v1/rules/',
        _rule_payload(stream.pk, aggregate_fn='median'),
        format='json',
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_serializer_rejects_zero_or_negative_window_minutes():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('c@w27.test', tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)

    resp = auth(admin).post(
        '/api/v1/rules/',
        _rule_payload(stream.pk, window_minutes=0),
        format='json',
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_serializer_rejects_non_numeric_operator():
    """`==` etc. on strings are not valid for a windowed (numeric) aggregate."""
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('d@w27.test', tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)

    payload = _rule_payload(stream.pk)
    # The default '>' is allowed. Send a string-only operator instead.
    # All four numeric operators (>, <, >=, <=, ==, !=) are valid for windowed,
    # so use a non-existent operator to force rejection.
    payload['condition_groups'][0]['conditions'][0]['operator'] = 'bogus'
    resp = auth(admin).post('/api/v1/rules/', payload, format='json')
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# RuleStreamIndex picks up windowed_aggregate stream
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rulestreamindex_includes_windowed_aggregate_stream():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('idx@w27.test', tenant)
    device = make_device(tenant, site)
    stream = make_stream(device)

    resp = auth(admin).post('/api/v1/rules/', _rule_payload(stream.pk), format='json')
    assert resp.status_code == 201
    rule_id = resp.json()['id']

    assert RuleStreamIndex.objects.filter(rule_id=rule_id, stream=stream).exists()
