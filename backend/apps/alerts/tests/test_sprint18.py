"""Sprint 18 tests — Alerts.

Covers:
  - Alert is created atomically when a rule fires
  - Alert is NOT created for suppressed, cleared, or no_change outcomes
  - Alert status transitions: active → acknowledged → resolved
  - Cannot acknowledge an already-acknowledged alert
  - Cannot resolve an already-resolved alert
  - Resolve is permitted from both active and acknowledged states
  - Acknowledge stores optional note
  - ViewOnly user cannot acknowledge or resolve
  - Cross-tenant isolation: cannot access another tenant's alerts
  - ?status= filter works
  - ?rule= filter works
  - site_names and device_names derived correctly from rule conditions

Ref: SPEC.md § Feature: Alerts
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.alerts.models import Alert
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import RuleStreamIndex, Stream, StreamReading
from apps.rules.models import Rule, RuleCondition, RuleConditionGroup
from apps.rules.tasks import evaluate_rule

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email: str, tenant: Tenant, role: str = 'admin') -> tuple:
    user = User.objects.create_user(email=email, password='testpass123')
    tu = TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user, tu


def make_device(tenant: Tenant, serial: str, site=None) -> Device:
    dt, _ = DeviceType.objects.get_or_create(
        slug='s18-mqtt',
        defaults={
            'name': 'Sprint 18 Test Device',
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 60,
            'command_ack_timeout_seconds': 30,
        },
    )
    if site is None:
        site = Site.objects.create(tenant=tenant, name=f'Site {serial}')
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=dt,
        name=f'Device {serial}',
        serial_number=serial,
        status=Device.Status.ACTIVE,
    )


def make_stream(device: Device, key: str = 'temp') -> Stream:
    return Stream.objects.create(
        device=device,
        key=key,
        label=key,
        data_type=Stream.DataType.NUMERIC,
    )


def make_threshold_rule(
    tenant: Tenant,
    stream: Stream,
    threshold: str = '25',
    operator: str = '>',
    current_state: bool = False,
) -> Rule:
    """Create an active rule with a single stream threshold condition."""
    rule = Rule.objects.create(
        tenant=tenant,
        name=f'Rule on {stream.key}',
        is_active=True,
        current_state=current_state,
    )
    group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    RuleCondition.objects.create(
        group=group,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream,
        operator=operator,
        threshold_value=threshold,
    )
    RuleStreamIndex.objects.create(rule=rule, stream=stream)
    return rule


def auth_client(user: User) -> APIClient:
    """Return an APIClient authenticated as the given user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Alert creation via evaluate_rule task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlertCreation:
    """Alert is created atomically when a rule fires."""

    def test_alert_created_on_fire(self):
        """evaluate_rule creates an Alert record when outcome is 'fired'."""
        tenant = make_tenant('AlertFireT')
        device = make_device(tenant, 'AF-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream, threshold='25', operator='>')

        StreamReading.objects.create(
            stream=stream, value='30', timestamp=timezone.now()
        )

        with patch('apps.rules.evaluator._try_acquire_lock', return_value=True):
            evaluate_rule(rule.pk)

        assert Alert.objects.filter(rule=rule, status=Alert.Status.ACTIVE).count() == 1
        alert = Alert.objects.get(rule=rule)
        assert alert.tenant == tenant
        assert alert.triggered_at is not None

    def test_no_alert_on_suppressed(self):
        """No alert created when outcome is 'suppressed' (already triggered)."""
        tenant = make_tenant('AlertSuppT')
        device = make_device(tenant, 'SUP-001')
        stream = make_stream(device)
        # Rule already in fired state
        rule = make_threshold_rule(tenant, stream, threshold='25', operator='>', current_state=True)

        StreamReading.objects.create(
            stream=stream, value='30', timestamp=timezone.now()
        )
        evaluate_rule(rule.pk)

        assert Alert.objects.filter(rule=rule).count() == 0

    def test_no_alert_on_no_change(self):
        """No alert created when conditions are false and state was false."""
        tenant = make_tenant('AlertNCT')
        device = make_device(tenant, 'NC-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream, threshold='25', operator='>')

        # Reading below threshold — no fire
        StreamReading.objects.create(
            stream=stream, value='10', timestamp=timezone.now()
        )
        evaluate_rule(rule.pk)

        assert Alert.objects.filter(rule=rule).count() == 0

    def test_no_alert_on_cleared(self):
        """No alert created when rule clears (true→false)."""
        tenant = make_tenant('AlertClearT')
        device = make_device(tenant, 'CLR-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream, threshold='25', operator='>', current_state=True)

        # Reading below threshold — clears
        StreamReading.objects.create(
            stream=stream, value='10', timestamp=timezone.now()
        )
        evaluate_rule(rule.pk)

        assert Alert.objects.filter(rule=rule).count() == 0


# ---------------------------------------------------------------------------
# Alert status transitions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlertTransitions:
    """Status transitions: active → acknowledged → resolved."""

    def _make_alert(self, tenant, rule) -> Alert:
        return Alert.objects.create(
            rule=rule,
            tenant=tenant,
            triggered_at=timezone.now(),
            status=Alert.Status.ACTIVE,
        )

    def test_acknowledge_active_alert(self):
        """Active alert can be acknowledged; status moves to acknowledged."""
        tenant = make_tenant('AckT')
        device = make_device(tenant, 'ACK-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('ack@example.com', tenant, role='admin')
        alert = self._make_alert(tenant, rule)

        client = auth_client(admin)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/acknowledge/', {'note': 'Checked it out.'})

        assert resp.status_code == 200
        alert.refresh_from_db()
        assert alert.status == Alert.Status.ACKNOWLEDGED
        assert alert.acknowledged_by == admin
        assert alert.acknowledged_note == 'Checked it out.'
        assert alert.acknowledged_at is not None

    def test_acknowledge_with_no_note(self):
        """Acknowledge is permitted without a note."""
        tenant = make_tenant('AckNoNoteT')
        device = make_device(tenant, 'ANN-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('ann@example.com', tenant)
        alert = self._make_alert(tenant, rule)

        client = auth_client(admin)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/acknowledge/', {})

        assert resp.status_code == 200
        alert.refresh_from_db()
        assert alert.status == Alert.Status.ACKNOWLEDGED
        assert alert.acknowledged_note is None

    def test_cannot_acknowledge_already_acknowledged(self):
        """Cannot acknowledge an alert that is already acknowledged."""
        tenant = make_tenant('AckDupT')
        device = make_device(tenant, 'DUP-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('dup@example.com', tenant)
        alert = Alert.objects.create(
            rule=rule, tenant=tenant,
            triggered_at=timezone.now(),
            status=Alert.Status.ACKNOWLEDGED,
        )

        client = auth_client(admin)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/acknowledge/', {})

        assert resp.status_code == 400

    def test_resolve_from_acknowledged(self):
        """Acknowledged alert can be resolved."""
        tenant = make_tenant('ResAckT')
        device = make_device(tenant, 'RES-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('res@example.com', tenant)
        alert = Alert.objects.create(
            rule=rule, tenant=tenant,
            triggered_at=timezone.now(),
            status=Alert.Status.ACKNOWLEDGED,
        )

        client = auth_client(admin)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/resolve/', {})

        assert resp.status_code == 200
        alert.refresh_from_db()
        assert alert.status == Alert.Status.RESOLVED
        assert alert.resolved_by == admin
        assert alert.resolved_at is not None

    def test_resolve_from_active(self):
        """Active alert can be resolved directly (skipping acknowledge)."""
        tenant = make_tenant('ResActiveT')
        device = make_device(tenant, 'RAT-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('rat@example.com', tenant)
        alert = self._make_alert(tenant, rule)

        client = auth_client(admin)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/resolve/', {})

        assert resp.status_code == 200
        alert.refresh_from_db()
        assert alert.status == Alert.Status.RESOLVED

    def test_cannot_resolve_already_resolved(self):
        """Cannot resolve an already-resolved alert."""
        tenant = make_tenant('ResDupT')
        device = make_device(tenant, 'RDT-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('rdt@example.com', tenant)
        alert = Alert.objects.create(
            rule=rule, tenant=tenant,
            triggered_at=timezone.now(),
            status=Alert.Status.RESOLVED,
        )

        client = auth_client(admin)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/resolve/', {})

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlertPermissions:
    """View-Only users cannot acknowledge or resolve. Cross-tenant is 404."""

    def _make_active_alert(self, tenant, rule) -> Alert:
        return Alert.objects.create(
            rule=rule,
            tenant=tenant,
            triggered_at=timezone.now(),
            status=Alert.Status.ACTIVE,
        )

    def test_view_only_cannot_acknowledge(self):
        """View-Only user receives 403 when attempting to acknowledge."""
        tenant = make_tenant('VOAckT')
        device = make_device(tenant, 'VOA-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        viewer, _ = make_user('viewer@example.com', tenant, role='viewer')
        alert = self._make_active_alert(tenant, rule)

        client = auth_client(viewer)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/acknowledge/', {})

        assert resp.status_code == 403

    def test_view_only_cannot_resolve(self):
        """View-Only user receives 403 when attempting to resolve."""
        tenant = make_tenant('VOResT')
        device = make_device(tenant, 'VOR-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        viewer, _ = make_user('vres@example.com', tenant, role='viewer')
        alert = self._make_active_alert(tenant, rule)

        client = auth_client(viewer)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/resolve/', {})

        assert resp.status_code == 403

    def test_operator_can_acknowledge(self):
        """Operator role is permitted to acknowledge."""
        tenant = make_tenant('OpAckT')
        device = make_device(tenant, 'OPA-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        operator, _ = make_user('op@example.com', tenant, role='operator')
        alert = self._make_active_alert(tenant, rule)

        client = auth_client(operator)
        resp = client.post(f'/api/v1/alerts/{alert.pk}/acknowledge/', {})

        assert resp.status_code == 200

    def test_cross_tenant_alert_returns_404(self):
        """A user from Tenant A cannot access Tenant B's alerts."""
        tenant_a = make_tenant('CrossTA')
        tenant_b = make_tenant('CrossTB')
        device_b = make_device(tenant_b, 'CTB-001')
        stream_b = make_stream(device_b)
        rule_b = make_threshold_rule(tenant_b, stream_b)
        alert_b = Alert.objects.create(
            rule=rule_b, tenant=tenant_b,
            triggered_at=timezone.now(),
            status=Alert.Status.ACTIVE,
        )
        user_a, _ = make_user('usera@example.com', tenant_a)

        client = auth_client(user_a)
        resp = client.get(f'/api/v1/alerts/{alert_b.pk}/')

        assert resp.status_code == 404

    def test_view_only_can_list(self):
        """View-Only user can list alerts (read-only access)."""
        tenant = make_tenant('VOListT')
        device = make_device(tenant, 'VOL-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        viewer, _ = make_user('volist@example.com', tenant, role='viewer')
        Alert.objects.create(
            rule=rule, tenant=tenant,
            triggered_at=timezone.now(), status=Alert.Status.ACTIVE,
        )

        client = auth_client(viewer)
        resp = client.get('/api/v1/alerts/')

        assert resp.status_code == 200
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlertFilters:
    """?status=, ?rule=, ?site= filters work correctly."""

    def test_filter_by_status(self):
        """?status=active returns only active alerts."""
        tenant = make_tenant('FiltStatT')
        device = make_device(tenant, 'FST-001')
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('fst@example.com', tenant)

        Alert.objects.create(
            rule=rule, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE
        )
        Alert.objects.create(
            rule=rule, tenant=tenant,
            triggered_at=timezone.now() - timedelta(hours=1),
            status=Alert.Status.RESOLVED,
        )

        client = auth_client(admin)
        resp = client.get('/api/v1/alerts/?status=active')

        assert resp.status_code == 200
        assert all(a['status'] == 'active' for a in resp.data)

    def test_filter_by_rule(self):
        """?rule=<id> returns only alerts for that rule."""
        tenant = make_tenant('FiltRuleT')
        device = make_device(tenant, 'FRL-001')
        stream_a = make_stream(device, 'ta')
        stream_b = make_stream(device, 'tb')
        rule_a = make_threshold_rule(tenant, stream_a)
        rule_b = make_threshold_rule(tenant, stream_b)
        admin, _ = make_user('frl@example.com', tenant)

        Alert.objects.create(rule=rule_a, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE)
        Alert.objects.create(rule=rule_b, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE)

        client = auth_client(admin)
        resp = client.get(f'/api/v1/alerts/?rule={rule_a.pk}')

        assert resp.status_code == 200
        assert all(a['rule'] == rule_a.pk for a in resp.data)

    def test_filter_by_site(self):
        """?site=<id> returns only alerts for rules referencing that site."""
        tenant = make_tenant('FiltSiteT')
        site_a = Site.objects.create(tenant=tenant, name='Site Alpha')
        site_b = Site.objects.create(tenant=tenant, name='Site Beta')
        device_a = make_device(tenant, 'FSA-001', site=site_a)
        device_b = make_device(tenant, 'FSB-001', site=site_b)
        stream_a = make_stream(device_a)
        stream_b = make_stream(device_b)
        rule_a = make_threshold_rule(tenant, stream_a)
        rule_b = make_threshold_rule(tenant, stream_b)
        admin, _ = make_user('fsite@example.com', tenant)

        alert_a = Alert.objects.create(
            rule=rule_a, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE
        )
        Alert.objects.create(
            rule=rule_b, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE
        )

        client = auth_client(admin)
        resp = client.get(f'/api/v1/alerts/?site={site_a.pk}')

        assert resp.status_code == 200
        ids = [a['id'] for a in resp.data]
        assert alert_a.pk in ids
        # rule_b's alert should not appear
        assert all(a['rule'] == rule_a.pk for a in resp.data)


# ---------------------------------------------------------------------------
# Derived site_names and device_names
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlertDerivedFields:
    """site_names and device_names are derived from rule conditions."""

    def test_single_device_and_site(self):
        """Alert for a single-stream rule returns one site and one device name."""
        tenant = make_tenant('DerivedSingleT')
        site = Site.objects.create(tenant=tenant, name='My Site')
        device = make_device(tenant, 'DRV-001', site=site)
        stream = make_stream(device)
        rule = make_threshold_rule(tenant, stream)
        admin, _ = make_user('drv@example.com', tenant)
        Alert.objects.create(rule=rule, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE)

        client = auth_client(admin)
        resp = client.get('/api/v1/alerts/')

        assert resp.status_code == 200
        alert_data = resp.data[0]
        assert alert_data['site_names'] == ['My Site']
        assert alert_data['device_names'] == ['Device DRV-001']

    def test_multiple_devices_and_sites(self):
        """Alert for a multi-stream rule returns all distinct site and device names."""
        tenant = make_tenant('DerivedMultiT')
        site_a = Site.objects.create(tenant=tenant, name='Alpha Site')
        site_b = Site.objects.create(tenant=tenant, name='Beta Site')
        device_a = make_device(tenant, 'MA-001', site=site_a)
        device_b = make_device(tenant, 'MB-001', site=site_b)
        stream_a = make_stream(device_a, 'ta')
        stream_b = make_stream(device_b, 'tb')

        rule = Rule.objects.create(tenant=tenant, name='Multi device rule', is_active=True)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.STREAM,
            stream=stream_a,
            operator='>',
            threshold_value='25',
        )
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.STREAM,
            stream=stream_b,
            operator='>',
            threshold_value='25',
        )
        admin, _ = make_user('multi@example.com', tenant)
        Alert.objects.create(rule=rule, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE)

        client = auth_client(admin)
        resp = client.get('/api/v1/alerts/')

        assert resp.status_code == 200
        alert_data = resp.data[0]
        assert set(alert_data['site_names']) == {'Alpha Site', 'Beta Site'}
        assert set(alert_data['device_names']) == {'Device MA-001', 'Device MB-001'}
