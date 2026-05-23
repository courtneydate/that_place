"""Regression test — the 3rd-party API poller dispatches rule evaluation.

A Rule whose condition watches a polled (3rd-party API) stream must fire when
a poll stores a reading that meets the condition. The poll path has to trigger
the rules engine the same way the MQTT ingestion path does; before this was
fixed, rules on polled streams were never evaluated and never fired.

Ref: SPEC.md § Feature: Rule Evaluation Engine
"""
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib
from django.utils.text import slugify

from apps.accounts.models import Tenant, TenantUser, User
from apps.alerts.models import Alert
from apps.devices.models import Device, DeviceType, Site
from apps.integrations.models import (
    DataSource,
    DataSourceDevice,
    ThirdPartyAPIProvider,
)
from apps.integrations.tasks import poll_single_device
from apps.readings.models import RuleStreamIndex, Stream
from apps.rules.models import Rule, RuleCondition, RuleConditionGroup

HTTP_PATCH = 'apps.integrations.tasks.http_requests.request'
AUTH_PATCH = 'apps.integrations.auth_handlers.get_auth_session'
GOOD_AUTH = ({'Authorization': 'Bearer tok'}, {}, None)


def _response(json_data):
    """Return a mock 200 requests.Response carrying the given JSON body."""
    resp = MagicMock(spec=req_lib.Response)
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture(autouse=True)
def _eager(settings):
    """Run Celery tasks inline so poll → dispatch → evaluate is synchronous."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.mark.django_db
def test_poll_dispatches_rule_evaluation_and_fires():
    """A poll storing a reading above the threshold fires the watching rule."""
    tenant = Tenant.objects.create(name='PollRuleT', slug=slugify('PollRuleT'))
    user = User.objects.create_user(email='pr@example.com', password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role='admin')

    provider = ThirdPartyAPIProvider.objects.create(
        name='RuleDispatchCo',
        slug='ruledispatchco',
        base_url='https://api.example.com',
        auth_type='api_key_header',
        auth_param_schema=[],
        discovery_endpoint={},
        detail_endpoint={'path_template': '/devices/{device_id}/', 'method': 'GET'},
        available_streams=[
            {'key': 'kwh', 'label': 'kWh', 'unit': 'kWh',
             'data_type': 'numeric', 'jsonpath': '$.kwh'},
        ],
    )
    datasource = DataSource.objects.create(
        tenant=tenant, provider=provider, name='DS', credentials={},
    )
    device_type = DeviceType.objects.create(
        name='API Device', slug='rd-api-device', connection_type='api',
        is_push=False, default_offline_threshold_minutes=30,
        command_ack_timeout_seconds=30,
    )
    site = Site.objects.create(tenant=tenant, name='Site')
    virtual_device = Device.objects.create(
        tenant=tenant, site=site, device_type=device_type,
        name='Meter', serial_number='rd-meter-1', status=Device.Status.ACTIVE,
    )
    dsd = DataSourceDevice.objects.create(
        datasource=datasource,
        external_device_id='EXT-1',
        virtual_device=virtual_device,
        active_stream_keys=['kwh'],
    )
    stream = Stream.objects.create(
        device=virtual_device, key='kwh', label='kWh',
        data_type=Stream.DataType.NUMERIC, unit='kWh',
    )

    # A rule that fires when the kwh stream exceeds 100.
    rule = Rule.objects.create(
        tenant=tenant, name='kWh over 100', is_active=True,
        condition_group_operator='AND', created_by=user,
    )
    group = RuleConditionGroup.objects.create(
        rule=rule, logical_operator='AND', order=0,
    )
    RuleCondition.objects.create(
        group=group,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream, operator='>', threshold_value='100', order=0,
    )
    RuleStreamIndex.objects.create(rule=rule, stream=stream)

    # The poll returns kwh = 500 — above the threshold.
    http_mock = MagicMock(return_value=_response({'kwh': 500}))
    with patch(AUTH_PATCH, return_value=GOOD_AUTH):
        with patch(HTTP_PATCH, http_mock):
            poll_single_device(dsd.pk)

    rule.refresh_from_db()
    assert rule.current_state is True
    assert Alert.objects.filter(rule=rule).exists()
