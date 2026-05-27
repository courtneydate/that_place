"""Sprint 26 tests — Per-Rule Per-Channel Notification Opt-Out.

Covers:
  - Per-rule opt-out suppresses the right channel without affecting others
  - Per-rule opt-out is independent from the global per-channel preference
    (most-restrictive wins on both directions)
  - SMS opt-in (Sprint 20) still independently enforced
  - Snooze (Sprint 20) still independently enforced — short-circuits before
    the opt-out check, suppressing all channels
  - Push opt-out suppresses despite a registered token
  - Opt-outs are scoped per user — one user's opt-out doesn't affect another
  - GET /my-notification-prefs/ returns defaults for a targeted user with no rows
  - PUT /my-notification-prefs/ creates and deletes opt-out rows to match
  - Non-targeted user receives 403 on GET / PUT
  - Cross-tenant rule access returns 404
  - Operator and Viewer roles can manage their own prefs (not Admin-only)

Ref: SPEC.md §8 Phase 5b; ROADMAP Sprint 26
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.alerts.models import Alert
from apps.devices.models import Device, DeviceType, Site
from apps.notifications.models import (
    Notification,
    NotificationSnooze,
    RuleNotificationOptOut,
    UserNotificationPreference,
    UserPushToken,
)
from apps.notifications.tasks import create_alert_notifications
from apps.readings.models import RuleStreamIndex, Stream
from apps.rules.models import Rule, RuleAction, RuleCondition, RuleConditionGroup

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email: str, tenant: Tenant, role: str = 'admin') -> User:
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_device(tenant: Tenant, serial: str) -> Device:
    dt, _ = DeviceType.objects.get_or_create(
        slug='s26-mqtt',
        defaults={
            'name': 'Sprint 26 Test Device',
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 60,
            'command_ack_timeout_seconds': 30,
        },
    )
    site = Site.objects.create(tenant=tenant, name=f'Site {serial}')
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=dt,
        name=f'Device {serial}',
        serial_number=serial,
        status=Device.Status.ACTIVE,
    )


def make_stream(device: Device) -> Stream:
    return Stream.objects.create(
        device=device, key='temp', label='Temp', data_type=Stream.DataType.NUMERIC,
    )


def make_rule_with_notify(tenant: Tenant, stream: Stream, users: list[User]) -> tuple[Rule, Alert]:
    """Return a fired rule+alert with a notify action targeting the given users."""
    rule = Rule.objects.create(tenant=tenant, name=f'S26 rule {tenant.pk}', is_active=True)
    grp = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    RuleCondition.objects.create(
        group=grp,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream,
        operator='>',
        threshold_value='10',
    )
    tu_pks = [TenantUser.objects.get(user=u, tenant=tenant).pk for u in users]
    RuleAction.objects.create(
        rule=rule,
        action_type=RuleAction.ActionType.NOTIFY,
        notification_channels=['in_app', 'email', 'sms', 'push'],
        group_ids=[],
        user_ids=tu_pks,
    )
    RuleStreamIndex.objects.get_or_create(rule=rule, stream=stream)
    alert = Alert.objects.create(
        rule=rule,
        tenant=tenant,
        triggered_at=timezone.now(),
        status=Alert.Status.ACTIVE,
    )
    return rule, alert


def opt_in_for_all_channels(user: User) -> None:
    """Globally enable every channel and set a phone for SMS."""
    UserNotificationPreference.objects.update_or_create(
        user=user,
        defaults={
            'in_app_enabled': True,
            'email_enabled': True,
            'sms_enabled': True,
            'phone_number': '+61412345678',
        },
    )


def auth_client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# create_alert_notifications: opt-out enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_email_opt_out_suppresses_only_email():
    """Opting out of email blocks email but leaves in_app, sms, push alone."""
    tenant = make_tenant('s26-email-only')
    user = make_user('email-out@s26.test', tenant)
    opt_in_for_all_channels(user)
    UserPushToken.objects.create(user=user, token='ExponentPushToken[s26-1]')
    device = make_device(tenant, 'S26-001')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, [user])

    RuleNotificationOptOut.objects.create(user=user, rule=rule, channel='email')

    create_alert_notifications(alert.pk)

    channels = set(
        Notification.objects
        .filter(user=user, alert=alert)
        .values_list('channel', flat=True)
    )
    assert channels == {'in_app', 'sms', 'push'}


@pytest.mark.django_db
def test_in_app_opt_out_blocks_in_app_only():
    """Opting out of in_app blocks in_app but leaves the other channels alone."""
    tenant = make_tenant('s26-in-app')
    user = make_user('in-app-out@s26.test', tenant)
    opt_in_for_all_channels(user)
    UserPushToken.objects.create(user=user, token='ExponentPushToken[s26-2]')
    device = make_device(tenant, 'S26-002')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, [user])

    RuleNotificationOptOut.objects.create(user=user, rule=rule, channel='in_app')

    create_alert_notifications(alert.pk)

    channels = set(
        Notification.objects
        .filter(user=user, alert=alert)
        .values_list('channel', flat=True)
    )
    assert channels == {'email', 'sms', 'push'}


@pytest.mark.django_db
def test_push_opt_out_blocks_push_despite_registered_token():
    """A registered push token alone isn't enough — opt-out wins."""
    tenant = make_tenant('s26-push')
    user = make_user('push-out@s26.test', tenant)
    opt_in_for_all_channels(user)
    UserPushToken.objects.create(user=user, token='ExponentPushToken[s26-3]')
    device = make_device(tenant, 'S26-003')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, [user])

    RuleNotificationOptOut.objects.create(user=user, rule=rule, channel='push')

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(
        user=user, alert=alert, channel='push',
    ).exists()
    assert Notification.objects.filter(
        user=user, alert=alert, channel='in_app',
    ).exists()


@pytest.mark.django_db
def test_global_pref_off_still_blocks_when_no_opt_out():
    """Global per-channel preference is independent of the per-rule opt-out."""
    tenant = make_tenant('s26-global-off')
    user = make_user('global-off@s26.test', tenant)
    UserNotificationPreference.objects.update_or_create(
        user=user,
        defaults={'in_app_enabled': True, 'email_enabled': False,
                  'sms_enabled': False, 'phone_number': ''},
    )
    device = make_device(tenant, 'S26-004')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, [user])

    create_alert_notifications(alert.pk)

    channels = set(
        Notification.objects
        .filter(user=user, alert=alert)
        .values_list('channel', flat=True)
    )
    assert channels == {'in_app'}


@pytest.mark.django_db
def test_sms_global_opt_in_still_required_with_no_opt_out():
    """Sprint 20's SMS opt-in must still gate SMS even with no per-rule opt-out."""
    tenant = make_tenant('s26-sms-gate')
    user = make_user('sms-gate@s26.test', tenant)
    UserNotificationPreference.objects.update_or_create(
        user=user,
        defaults={'in_app_enabled': True, 'email_enabled': True,
                  'sms_enabled': False, 'phone_number': ''},
    )
    device = make_device(tenant, 'S26-005')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, [user])

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(
        user=user, alert=alert, channel='sms',
    ).exists()


@pytest.mark.django_db
def test_snooze_still_suppresses_all_channels_regardless_of_opt_out():
    """An active snooze takes precedence — all channels are suppressed."""
    tenant = make_tenant('s26-snooze')
    user = make_user('snooze@s26.test', tenant)
    opt_in_for_all_channels(user)
    UserPushToken.objects.create(user=user, token='ExponentPushToken[s26-4]')
    device = make_device(tenant, 'S26-006')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, [user])

    # User has opted out of email AND has an active snooze.
    RuleNotificationOptOut.objects.create(user=user, rule=rule, channel='email')
    NotificationSnooze.objects.create(
        user=user, rule=rule,
        snoozed_until=timezone.now() + timedelta(hours=1),
    )

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(user=user, alert=alert).exists()


@pytest.mark.django_db
def test_opt_out_is_scoped_per_user():
    """User A's opt-out does not affect user B."""
    tenant = make_tenant('s26-scope')
    user_a = make_user('a@s26.test', tenant)
    user_b = make_user('b@s26.test', tenant)
    opt_in_for_all_channels(user_a)
    opt_in_for_all_channels(user_b)
    device = make_device(tenant, 'S26-007')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, [user_a, user_b])

    RuleNotificationOptOut.objects.create(user=user_a, rule=rule, channel='email')

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(
        user=user_a, alert=alert, channel='email',
    ).exists()
    assert Notification.objects.filter(
        user=user_b, alert=alert, channel='email',
    ).exists()


# ---------------------------------------------------------------------------
# GET/PUT /api/v1/rules/:id/my-notification-prefs/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_prefs_returns_defaults_for_targeted_user_with_no_rows():
    tenant = make_tenant('s26-get-default')
    user = make_user('get-default@s26.test', tenant)
    device = make_device(tenant, 'S26-008')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, [user])

    resp = auth_client(user).get(f'/api/v1/rules/{rule.pk}/my-notification-prefs/')

    assert resp.status_code == 200
    assert resp.json() == {'in_app': True, 'email': True, 'sms': True, 'push': True}


@pytest.mark.django_db
def test_put_prefs_creates_and_deletes_opt_outs():
    tenant = make_tenant('s26-put')
    user = make_user('put@s26.test', tenant)
    device = make_device(tenant, 'S26-009')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, [user])

    client = auth_client(user)
    resp = client.put(
        f'/api/v1/rules/{rule.pk}/my-notification-prefs/',
        data={'in_app': True, 'email': False, 'sms': False, 'push': True},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.json() == {'in_app': True, 'email': False, 'sms': False, 'push': True}

    opt_outs = set(
        RuleNotificationOptOut.objects
        .filter(user=user, rule=rule)
        .values_list('channel', flat=True)
    )
    assert opt_outs == {'email', 'sms'}

    # Toggle email back on — opt-out row for email is deleted.
    resp = client.put(
        f'/api/v1/rules/{rule.pk}/my-notification-prefs/',
        data={'in_app': True, 'email': True, 'sms': False, 'push': True},
        format='json',
    )
    assert resp.status_code == 200
    remaining = set(
        RuleNotificationOptOut.objects
        .filter(user=user, rule=rule)
        .values_list('channel', flat=True)
    )
    assert remaining == {'sms'}


@pytest.mark.django_db
def test_non_targeted_user_gets_403():
    """A user not in the rule's notify targets cannot read or set prefs."""
    tenant = make_tenant('s26-403')
    targeted = make_user('targeted@s26.test', tenant)
    other = make_user('other@s26.test', tenant)
    device = make_device(tenant, 'S26-010')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, [targeted])

    client = auth_client(other)
    resp = client.get(f'/api/v1/rules/{rule.pk}/my-notification-prefs/')
    assert resp.status_code == 403

    resp = client.put(
        f'/api/v1/rules/{rule.pk}/my-notification-prefs/',
        data={'in_app': True, 'email': True, 'sms': True, 'push': True},
        format='json',
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_cross_tenant_rule_returns_404():
    """A user from tenant B cannot access a rule belonging to tenant A."""
    tenant_a = make_tenant('s26-cross-A')
    tenant_b = make_tenant('s26-cross-B')
    user_a = make_user('a@s26-cross.test', tenant_a)
    user_b = make_user('b@s26-cross.test', tenant_b)
    device = make_device(tenant_a, 'S26-011')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant_a, stream, [user_a])

    resp = auth_client(user_b).get(f'/api/v1/rules/{rule.pk}/my-notification-prefs/')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_operator_can_manage_own_prefs():
    """Operator role can manage their own prefs — not Admin-only."""
    tenant = make_tenant('s26-operator')
    operator = make_user('operator@s26.test', tenant, role='operator')
    device = make_device(tenant, 'S26-012')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, [operator])

    client = auth_client(operator)
    resp = client.put(
        f'/api/v1/rules/{rule.pk}/my-notification-prefs/',
        data={'in_app': True, 'email': False, 'sms': True, 'push': True},
        format='json',
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_viewer_can_manage_own_prefs():
    """Viewer role can manage their own prefs — not Admin-only."""
    tenant = make_tenant('s26-viewer')
    viewer = make_user('viewer@s26.test', tenant, role='viewer')
    device = make_device(tenant, 'S26-013')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, [viewer])

    client = auth_client(viewer)
    resp = client.put(
        f'/api/v1/rules/{rule.pk}/my-notification-prefs/',
        data={'in_app': False, 'email': True, 'sms': True, 'push': True},
        format='json',
    )
    assert resp.status_code == 200
    assert RuleNotificationOptOut.objects.filter(
        user=viewer, rule=rule, channel='in_app',
    ).exists()


@pytest.mark.django_db
def test_anonymous_blocked_from_prefs_endpoint():
    """No auth → 401."""
    tenant = make_tenant('s26-anon')
    user = make_user('anon@s26.test', tenant)
    device = make_device(tenant, 'S26-014')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, [user])

    resp = APIClient().get(f'/api/v1/rules/{rule.pk}/my-notification-prefs/')
    assert resp.status_code == 401


@pytest.mark.django_db
def test_group_targeted_user_can_access_prefs():
    """A user targeted via group membership (not user_ids) is still a target."""
    from apps.accounts.models import NotificationGroup, NotificationGroupMember

    tenant = make_tenant('s26-group')
    user = make_user('grouped@s26.test', tenant)
    device = make_device(tenant, 'S26-015')
    stream = make_stream(device)

    group = NotificationGroup.objects.create(tenant=tenant, name='Custom group')
    tu = TenantUser.objects.get(user=user, tenant=tenant)
    NotificationGroupMember.objects.create(group=group, tenant_user=tu)

    rule = Rule.objects.create(tenant=tenant, name='S26 group rule', is_active=True)
    grp_cg = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    RuleCondition.objects.create(
        group=grp_cg,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream,
        operator='>',
        threshold_value='10',
    )
    RuleAction.objects.create(
        rule=rule,
        action_type=RuleAction.ActionType.NOTIFY,
        notification_channels=['in_app', 'email'],
        group_ids=[group.pk],
        user_ids=[],
    )

    resp = auth_client(user).get(f'/api/v1/rules/{rule.pk}/my-notification-prefs/')
    assert resp.status_code == 200
