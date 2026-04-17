"""Sprint 20 tests — Email, SMS & Notification Snooze.

Covers:
  - Email Notification row created for users with email_enabled=True
  - Email not created for users with email_enabled=False
  - SMS Notification row created for sms_enabled=True + phone_number set
  - SMS not created for sms_enabled=False
  - SMS not created for sms_enabled=True but phone_number blank
  - Snoozed user receives no Notification rows (any channel)
  - Snooze with snoozed_until in the past does NOT suppress notifications
  - Preferences GET returns defaults for new user (get_or_create)
  - Preferences PUT updates fields correctly
  - Snooze POST creates NotificationSnooze; re-POST extends snoozed_until
  - Snooze DELETE cancels active snooze (idempotent)
  - Snooze GET lists only active (future) snoozes
  - Snooze POST rejects invalid duration_minutes
  - Snooze POST rejects rule from another tenant (404)
  - send_email_notification marks delivery_status delivered on success
  - send_email_notification marks delivery_status failed after max retries
  - send_sms_notification marks delivery_status failed when phone blank

Ref: SPEC.md § Feature: Notifications — Channels, Snooze
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
from apps.notifications.models import (
    Notification,
    NotificationSnooze,
    UserNotificationPreference,
)
from apps.notifications.tasks import (
    create_alert_notifications,
    send_email_notification,
    send_sms_notification,
)
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
        slug='s20-mqtt',
        defaults={
            'name': 'Sprint 20 Test Device',
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


def make_rule_with_notify(tenant: Tenant, stream: Stream, user: User) -> tuple[Rule, Alert]:
    """Return a fired rule+alert with a notify action targeting the given user."""
    rule = Rule.objects.create(tenant=tenant, name='Test rule S20', is_active=True)
    grp = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    RuleCondition.objects.create(
        group=grp,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream,
        operator='>',
        threshold_value='10',
    )
    tu = TenantUser.objects.get(user=user, tenant=tenant)
    RuleAction.objects.create(
        rule=rule,
        action_type=RuleAction.ActionType.NOTIFY,
        notification_channels=['in_app', 'email', 'sms'],
        group_ids=[],
        user_ids=[tu.pk],
    )
    RuleStreamIndex.objects.get_or_create(rule=rule, stream=stream)
    alert = Alert.objects.create(
        rule=rule,
        tenant=tenant,
        triggered_at=timezone.now(),
        status=Alert.Status.ACTIVE,
    )
    return rule, alert


# ---------------------------------------------------------------------------
# Multi-channel notification creation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_email_notification_created_when_enabled():
    tenant = make_tenant('email-on')
    user = make_user('email-on@example.com', tenant)
    UserNotificationPreference.objects.create(
        user=user, email_enabled=True, sms_enabled=False,
    )
    device = make_device(tenant, 'EML001')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, user)

    create_alert_notifications(alert.pk)

    assert Notification.objects.filter(
        user=user, alert=alert, channel=Notification.Channel.EMAIL,
    ).exists()


@pytest.mark.django_db
def test_email_notification_not_created_when_disabled():
    tenant = make_tenant('email-off')
    user = make_user('email-off@example.com', tenant)
    UserNotificationPreference.objects.create(
        user=user, email_enabled=False, sms_enabled=False,
    )
    device = make_device(tenant, 'EML002')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, user)

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(
        user=user, alert=alert, channel=Notification.Channel.EMAIL,
    ).exists()


@pytest.mark.django_db
def test_sms_notification_created_when_opted_in_with_phone():
    tenant = make_tenant('sms-on')
    user = make_user('sms-on@example.com', tenant)
    UserNotificationPreference.objects.create(
        user=user, sms_enabled=True, phone_number='+61412345678',
    )
    device = make_device(tenant, 'SMS001')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, user)

    create_alert_notifications(alert.pk)

    assert Notification.objects.filter(
        user=user, alert=alert, channel=Notification.Channel.SMS,
    ).exists()


@pytest.mark.django_db
def test_sms_not_created_when_opted_out():
    tenant = make_tenant('sms-off')
    user = make_user('sms-off@example.com', tenant)
    UserNotificationPreference.objects.create(
        user=user, sms_enabled=False, phone_number='+61412345678',
    )
    device = make_device(tenant, 'SMS002')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, user)

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(
        user=user, alert=alert, channel=Notification.Channel.SMS,
    ).exists()


@pytest.mark.django_db
def test_sms_not_created_when_opted_in_but_no_phone():
    tenant = make_tenant('sms-nonum')
    user = make_user('sms-nonum@example.com', tenant)
    UserNotificationPreference.objects.create(
        user=user, sms_enabled=True, phone_number='',
    )
    device = make_device(tenant, 'SMS003')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, user)

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(
        user=user, alert=alert, channel=Notification.Channel.SMS,
    ).exists()


@pytest.mark.django_db
def test_default_preferences_creates_in_app_and_email_only():
    """Users with no preference row get defaults: in-app + email, no SMS."""
    tenant = make_tenant('defaults')
    user = make_user('defaults@example.com', tenant)
    # No UserNotificationPreference row — defaults apply
    device = make_device(tenant, 'DEF001')
    stream = make_stream(device)
    _, alert = make_rule_with_notify(tenant, stream, user)

    create_alert_notifications(alert.pk)

    assert Notification.objects.filter(user=user, alert=alert, channel=Notification.Channel.IN_APP).exists()
    assert Notification.objects.filter(user=user, alert=alert, channel=Notification.Channel.EMAIL).exists()
    assert not Notification.objects.filter(user=user, alert=alert, channel=Notification.Channel.SMS).exists()


# ---------------------------------------------------------------------------
# Snooze suppression
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_snoozed_user_receives_no_notifications():
    tenant = make_tenant('snooze-suppress')
    user = make_user('snooze@example.com', tenant)
    device = make_device(tenant, 'SNZ001')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, user)

    NotificationSnooze.objects.create(
        user=user,
        rule=rule,
        snoozed_until=timezone.now() + timedelta(hours=1),
    )

    create_alert_notifications(alert.pk)

    assert not Notification.objects.filter(user=user, alert=alert).exists()


@pytest.mark.django_db
def test_expired_snooze_does_not_suppress():
    tenant = make_tenant('snooze-expired')
    user = make_user('expired@example.com', tenant)
    device = make_device(tenant, 'SNZ002')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, user)

    # Snooze already expired
    NotificationSnooze.objects.create(
        user=user,
        rule=rule,
        snoozed_until=timezone.now() - timedelta(minutes=1),
    )

    create_alert_notifications(alert.pk)

    assert Notification.objects.filter(
        user=user, alert=alert, channel=Notification.Channel.IN_APP,
    ).exists()


# ---------------------------------------------------------------------------
# Preferences endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_preferences_get_creates_defaults():
    tenant = make_tenant('pref-get')
    user = make_user('pref-get@example.com', tenant)
    client = APIClient()
    client.force_authenticate(user)

    resp = client.get('/api/v1/notifications/preferences/')

    assert resp.status_code == 200
    assert resp.data['email_enabled'] is True
    assert resp.data['sms_enabled'] is False
    assert resp.data['in_app_enabled'] is True
    # Row created in DB
    assert UserNotificationPreference.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_preferences_put_updates_fields():
    tenant = make_tenant('pref-put')
    user = make_user('pref-put@example.com', tenant)
    client = APIClient()
    client.force_authenticate(user)

    resp = client.put(
        '/api/v1/notifications/preferences/',
        {'email_enabled': False, 'sms_enabled': True, 'phone_number': '+61400000001'},
        format='json',
    )

    assert resp.status_code == 200
    pref = UserNotificationPreference.objects.get(user=user)
    assert pref.email_enabled is False
    assert pref.sms_enabled is True
    assert pref.phone_number == '+61400000001'


@pytest.mark.django_db
def test_preferences_unauthenticated_returns_401():
    client = APIClient()
    resp = client.get('/api/v1/notifications/preferences/')
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Snooze endpoints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_snooze_create():
    tenant = make_tenant('snooze-create')
    user = make_user('snooze-c@example.com', tenant)
    device = make_device(tenant, 'SNC001')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, user)
    client = APIClient()
    client.force_authenticate(user)

    resp = client.post(
        '/api/v1/notifications/snooze/',
        {'rule_id': rule.pk, 'duration_minutes': 60},
        format='json',
    )

    assert resp.status_code == 201
    assert NotificationSnooze.objects.filter(user=user, rule=rule).exists()
    snooze = NotificationSnooze.objects.get(user=user, rule=rule)
    assert snooze.snoozed_until > timezone.now()


@pytest.mark.django_db
def test_snooze_repost_extends_duration():
    tenant = make_tenant('snooze-extend')
    user = make_user('snooze-e@example.com', tenant)
    device = make_device(tenant, 'SNC002')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, user)
    NotificationSnooze.objects.create(
        user=user, rule=rule,
        snoozed_until=timezone.now() + timedelta(minutes=15),
    )
    client = APIClient()
    client.force_authenticate(user)

    resp = client.post(
        '/api/v1/notifications/snooze/',
        {'rule_id': rule.pk, 'duration_minutes': 1440},
        format='json',
    )

    assert resp.status_code == 200
    snooze = NotificationSnooze.objects.get(user=user, rule=rule)
    # Should be ~24 hours from now, not 15 minutes
    assert snooze.snoozed_until > timezone.now() + timedelta(hours=23)


@pytest.mark.django_db
def test_snooze_delete_cancels():
    tenant = make_tenant('snooze-del')
    user = make_user('snooze-d@example.com', tenant)
    device = make_device(tenant, 'SND001')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, user)
    NotificationSnooze.objects.create(
        user=user, rule=rule,
        snoozed_until=timezone.now() + timedelta(hours=4),
    )
    client = APIClient()
    client.force_authenticate(user)

    resp = client.delete(f'/api/v1/notifications/snooze/{rule.pk}/')

    assert resp.status_code == 204
    assert not NotificationSnooze.objects.filter(user=user, rule=rule).exists()


@pytest.mark.django_db
def test_snooze_delete_idempotent():
    tenant = make_tenant('snooze-del-idem')
    user = make_user('snooze-di@example.com', tenant)
    device = make_device(tenant, 'SND002')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, user)
    client = APIClient()
    client.force_authenticate(user)

    # No snooze exists — should still return 204
    resp = client.delete(f'/api/v1/notifications/snooze/{rule.pk}/')
    assert resp.status_code == 204


@pytest.mark.django_db
def test_snooze_get_lists_only_active():
    tenant = make_tenant('snooze-list')
    user = make_user('snooze-l@example.com', tenant)
    device = make_device(tenant, 'SNL001')
    stream = make_stream(device)
    rule1, _ = make_rule_with_notify(tenant, stream, user)
    rule2 = Rule.objects.create(tenant=tenant, name='Rule 2', is_active=True)
    # Active snooze
    NotificationSnooze.objects.create(
        user=user, rule=rule1,
        snoozed_until=timezone.now() + timedelta(hours=1),
    )
    # Expired snooze
    NotificationSnooze.objects.create(
        user=user, rule=rule2,
        snoozed_until=timezone.now() - timedelta(minutes=5),
    )
    client = APIClient()
    client.force_authenticate(user)

    resp = client.get('/api/v1/notifications/snooze/')

    assert resp.status_code == 200
    assert len(resp.data) == 1
    assert resp.data[0]['rule'] == rule1.pk


@pytest.mark.django_db
def test_snooze_invalid_duration_rejected():
    tenant = make_tenant('snooze-bad-dur')
    user = make_user('snooze-bad@example.com', tenant)
    device = make_device(tenant, 'SNB001')
    stream = make_stream(device)
    rule, _ = make_rule_with_notify(tenant, stream, user)
    client = APIClient()
    client.force_authenticate(user)

    resp = client.post(
        '/api/v1/notifications/snooze/',
        {'rule_id': rule.pk, 'duration_minutes': 99},
        format='json',
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_snooze_cross_tenant_rejected():
    tenant_a = make_tenant('snooze-xtenant-a')
    tenant_b = make_tenant('snooze-xtenant-b')
    user_a = make_user('a@xtenant.com', tenant_a)
    user_b = make_user('b@xtenant.com', tenant_b)
    device_b = make_device(tenant_b, 'XTN001')
    stream_b = make_stream(device_b)
    rule_b, _ = make_rule_with_notify(tenant_b, stream_b, user_b)
    client = APIClient()
    client.force_authenticate(user_a)

    resp = client.post(
        '/api/v1/notifications/snooze/',
        {'rule_id': rule_b.pk, 'duration_minutes': 60},
        format='json',
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delivery tasks
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_email_notification_success():
    tenant = make_tenant('email-send')
    user = make_user('send@example.com', tenant)
    device = make_device(tenant, 'ESD001')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, user)
    notif = Notification.objects.create(
        user=user,
        notification_type=Notification.NotificationType.ALERT,
        alert=alert,
        channel=Notification.Channel.EMAIL,
        delivery_status=Notification.DeliveryStatus.SENT,
    )

    with patch('django.core.mail.send_mail') as mock_send:
        mock_send.return_value = 1
        send_email_notification(notif.pk)

    notif.refresh_from_db()
    assert notif.delivery_status == Notification.DeliveryStatus.DELIVERED
    mock_send.assert_called_once()


@pytest.mark.django_db
def test_send_email_notification_failure_marks_failed():
    tenant = make_tenant('email-fail')
    user = make_user('fail@example.com', tenant)
    device = make_device(tenant, 'EFL001')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, user)
    notif = Notification.objects.create(
        user=user,
        notification_type=Notification.NotificationType.ALERT,
        alert=alert,
        channel=Notification.Channel.EMAIL,
        delivery_status=Notification.DeliveryStatus.SENT,
    )

    with patch('django.core.mail.send_mail', side_effect=Exception('SMTP down')):
        # Invoke via apply() with retries=1 so Celery sees this as the final
        # attempt (max_retries=1), triggering MaxRetriesExceededError and the
        # failure branch that sets delivery_status=failed.
        send_email_notification.apply(args=[notif.pk], kwargs={}, retries=1)

    notif.refresh_from_db()
    assert notif.delivery_status == Notification.DeliveryStatus.FAILED


@pytest.mark.django_db
def test_send_sms_no_phone_marks_failed():
    tenant = make_tenant('sms-nonum2')
    user = make_user('smsnonum@example.com', tenant)
    UserNotificationPreference.objects.create(
        user=user, sms_enabled=True, phone_number='',
    )
    device = make_device(tenant, 'SNP001')
    stream = make_stream(device)
    rule, alert = make_rule_with_notify(tenant, stream, user)
    notif = Notification.objects.create(
        user=user,
        notification_type=Notification.NotificationType.ALERT,
        alert=alert,
        channel=Notification.Channel.SMS,
        delivery_status=Notification.DeliveryStatus.SENT,
    )

    with patch.dict('django.conf.settings.__dict__', {
        'TWILIO_ACCOUNT_SID': 'ACtest',
        'TWILIO_AUTH_TOKEN': 'token',
        'TWILIO_FROM_NUMBER': '+1234567890',
    }):
        send_sms_notification(notif.pk)

    notif.refresh_from_db()
    assert notif.delivery_status == Notification.DeliveryStatus.FAILED
