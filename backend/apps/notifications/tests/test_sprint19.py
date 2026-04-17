"""Sprint 19 tests — In-App Notifications & System Events.

Covers:
  - create_alert_notifications creates one Notification per targeted user
  - Group expansion: group members receive notifications
  - Individual user_ids receive notifications
  - Deduplication: user in group + user_ids list gets one notification only
  - No notifications created when rule has no notify actions
  - create_system_notification creates one Notification per Tenant Admin
  - Non-admin users do not receive system notifications
  - Notification list scoped to requesting user only
  - ?unread_only=true filter works
  - unread-count endpoint is accurate
  - mark_read marks a single notification as read (idempotent)
  - mark_all_read clears all unread and returns correct count
  - Unauthenticated request returns 401

Ref: SPEC.md § Feature: Notifications
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import (
    NotificationGroup,
    NotificationGroupMember,
    Tenant,
    TenantUser,
    User,
)
from apps.alerts.models import Alert
from apps.devices.models import Device, DeviceType, Site
from apps.notifications.models import Notification
from apps.notifications.tasks import create_alert_notifications, create_system_notification
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
        slug='s19-mqtt',
        defaults={
            'name': 'Sprint 19 Test Device',
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


def make_stream(device: Device, key: str = 'temp') -> Stream:
    return Stream.objects.create(
        device=device,
        key=key,
        label=key,
        data_type=Stream.DataType.NUMERIC,
    )


def make_rule_with_notify_action(
    tenant: Tenant,
    stream: Stream,
    group_ids: list | None = None,
    user_ids: list | None = None,
) -> tuple[Rule, Alert]:
    """Create a fired rule with a notify action targeting the given groups/users."""
    rule = Rule.objects.create(tenant=tenant, name='Notify rule', is_active=True)
    group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
    RuleCondition.objects.create(
        group=group,
        condition_type=RuleCondition.ConditionType.STREAM,
        stream=stream,
        operator='>',
        threshold_value='25',
    )
    RuleAction.objects.create(
        rule=rule,
        action_type=RuleAction.ActionType.NOTIFY,
        notification_channels=['in_app'],
        group_ids=group_ids or [],
        user_ids=user_ids or [],
    )
    RuleStreamIndex.objects.create(rule=rule, stream=stream)
    alert = Alert.objects.create(
        rule=rule,
        tenant=tenant,
        triggered_at=timezone.now(),
        status=Alert.Status.ACTIVE,
    )
    return rule, alert


def auth_client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# create_alert_notifications task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreateAlertNotifications:
    """Alert fire creates one in_app Notification per targeted user."""

    def test_notifies_individual_user(self):
        """A user in user_ids receives one in-app notification."""
        tenant = make_tenant('NotifIndivT')
        device = make_device(tenant, 'NI-001')
        stream = make_stream(device)
        target = make_user('target@example.com', tenant, role='operator')
        target_tu = TenantUser.objects.get(user=target, tenant=tenant)

        _, alert = make_rule_with_notify_action(tenant, stream, user_ids=[target_tu.pk])
        create_alert_notifications(alert.pk)

        # Sprint 20: task now creates one row per channel (in_app + email by default).
        # Assert the in_app row — deduplication and multi-channel counts are
        # covered by test_sprint20.py.
        notifs = Notification.objects.filter(
            user=target, alert=alert, channel=Notification.Channel.IN_APP,
        )
        assert notifs.count() == 1
        assert notifs.first().notification_type == Notification.NotificationType.ALERT

    def test_notifies_group_members(self):
        """All members of a targeted group receive an in-app notification."""
        tenant = make_tenant('NotifGroupT')
        device = make_device(tenant, 'NG-001')
        stream = make_stream(device)
        user_a = make_user('ga@example.com', tenant, role='operator')
        user_b = make_user('gb@example.com', tenant, role='viewer')
        group = NotificationGroup.objects.create(tenant=tenant, name='Ops group')
        tu_a = TenantUser.objects.get(user=user_a, tenant=tenant)
        tu_b = TenantUser.objects.get(user=user_b, tenant=tenant)
        NotificationGroupMember.objects.create(group=group, tenant_user=tu_a)
        NotificationGroupMember.objects.create(group=group, tenant_user=tu_b)

        _, alert = make_rule_with_notify_action(tenant, stream, group_ids=[group.pk])
        create_alert_notifications(alert.pk)

        # Each member gets one in-app row (multi-channel totals tested in Sprint 20).
        assert Notification.objects.filter(
            user=user_a, alert=alert, channel=Notification.Channel.IN_APP,
        ).count() == 1
        assert Notification.objects.filter(
            user=user_b, alert=alert, channel=Notification.Channel.IN_APP,
        ).count() == 1

    def test_deduplication_group_and_individual(self):
        """A user targeted via group AND user_ids gets only one in-app notification."""
        tenant = make_tenant('NotifDedupeT')
        device = make_device(tenant, 'DD-001')
        stream = make_stream(device)
        user = make_user('dedup@example.com', tenant)
        tu = TenantUser.objects.get(user=user, tenant=tenant)
        group = NotificationGroup.objects.create(tenant=tenant, name='Dedupe group')
        NotificationGroupMember.objects.create(group=group, tenant_user=tu)

        # Same user targeted via group AND user_ids
        _, alert = make_rule_with_notify_action(
            tenant, stream, group_ids=[group.pk], user_ids=[tu.pk]
        )
        create_alert_notifications(alert.pk)

        # Deduplication: only one in_app row despite two targeting paths.
        assert Notification.objects.filter(
            user=user, alert=alert, channel=Notification.Channel.IN_APP,
        ).count() == 1

    def test_no_notifications_without_notify_action(self):
        """A rule with only a command action creates no notifications."""
        tenant = make_tenant('NotifNoActionT')
        device = make_device(tenant, 'NA-001')
        stream = make_stream(device)

        rule = Rule.objects.create(tenant=tenant, name='Command only rule', is_active=True)
        group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
        RuleCondition.objects.create(
            group=group,
            condition_type=RuleCondition.ConditionType.STREAM,
            stream=stream,
            operator='>',
            threshold_value='25',
        )
        RuleAction.objects.create(
            rule=rule,
            action_type=RuleAction.ActionType.COMMAND,
        )
        alert = Alert.objects.create(
            rule=rule, tenant=tenant, triggered_at=timezone.now(), status=Alert.Status.ACTIVE
        )
        create_alert_notifications(alert.pk)

        assert Notification.objects.filter(alert=alert).count() == 0

    def test_alert_not_found_is_a_noop(self):
        """Non-existent alert_id does not raise — task exits cleanly."""
        create_alert_notifications(99999)  # Should not raise


# ---------------------------------------------------------------------------
# create_system_notification task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreateSystemNotification:
    """System events create Notifications for all Tenant Admins."""

    def test_admins_receive_system_notification(self):
        """All admins in a tenant receive the system event notification."""
        tenant = make_tenant('SysNotifT')
        admin_a = make_user('sna@example.com', tenant, role='admin')
        admin_b = make_user('snb@example.com', tenant, role='admin')

        create_system_notification('device_offline', tenant.pk, {'device_name': 'Scout 1'})

        for admin in [admin_a, admin_b]:
            notif = Notification.objects.get(user=admin, event_type='device_offline')
            assert notif.notification_type == Notification.NotificationType.SYSTEM_EVENT
            assert notif.event_data == {'device_name': 'Scout 1'}

    def test_non_admins_do_not_receive_system_notification(self):
        """Operators and viewers do not receive system notifications."""
        tenant = make_tenant('SysNotifRoleT')
        make_user('op@example.com', tenant, role='operator')
        make_user('viewer@example.com', tenant, role='viewer')
        admin = make_user('adm@example.com', tenant, role='admin')

        create_system_notification('device_approved', tenant.pk, {})

        assert Notification.objects.filter(event_type='device_approved').count() == 1
        assert Notification.objects.filter(
            user=admin, event_type='device_approved'
        ).count() == 1

    def test_system_notification_event_types(self):
        """Each supported event_type is stored correctly on the notification."""
        tenant = make_tenant('SysEventTypeT')
        admin = make_user('evt@example.com', tenant, role='admin')
        for event_type in ('device_approved', 'device_offline', 'device_deleted', 'datasource_poll_failure'):
            create_system_notification(event_type, tenant.pk, {})

        stored = list(
            Notification.objects.filter(user=admin).values_list('event_type', flat=True)
        )
        assert set(stored) == {
            'device_approved', 'device_offline', 'device_deleted', 'datasource_poll_failure'
        }


# ---------------------------------------------------------------------------
# Notification API endpoints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestNotificationList:
    """GET /api/v1/notifications/ — scoped to the requesting user."""

    def test_user_sees_own_notifications_only(self):
        """User A cannot see User B's notifications."""
        tenant = make_tenant('ListScopeT')
        user_a = make_user('la@example.com', tenant)
        user_b = make_user('lb@example.com', tenant, role='operator')

        Notification.objects.create(
            user=user_b,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
        )

        resp = auth_client(user_a).get('/api/v1/notifications/')
        assert resp.status_code == 200
        assert len(resp.data) == 0

    def test_unread_only_filter(self):
        """?unread_only=true returns only unread notifications."""
        tenant = make_tenant('UnreadFilterT')
        user = make_user('uf@example.com', tenant)

        Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
        )
        Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_approved',
            event_data={},
            read_at=timezone.now(),
        )

        resp = auth_client(user).get('/api/v1/notifications/?unread_only=true')
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]['event_type'] == 'device_offline'

    def test_unauthenticated_returns_401(self):
        """Unauthenticated request is rejected."""
        resp = APIClient().get('/api/v1/notifications/')
        assert resp.status_code == 401


@pytest.mark.django_db
class TestUnreadCount:
    """GET /api/v1/notifications/unread-count/ — accurate count."""

    def test_unread_count_reflects_unread_only(self):
        """Count matches only notifications with read_at=None."""
        tenant = make_tenant('UnreadCountT')
        user = make_user('uc@example.com', tenant)

        Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
        )
        Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
            read_at=timezone.now(),
        )

        resp = auth_client(user).get('/api/v1/notifications/unread-count/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1


@pytest.mark.django_db
class TestMarkRead:
    """POST /api/v1/notifications/:id/read/ — marks individual notification read."""

    def test_mark_read_sets_read_at(self):
        """Marking a notification as read sets read_at."""
        tenant = make_tenant('MarkReadT')
        user = make_user('mr@example.com', tenant)
        notif = Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
        )

        resp = auth_client(user).post(f'/api/v1/notifications/{notif.pk}/read/')
        assert resp.status_code == 200
        notif.refresh_from_db()
        assert notif.read_at is not None
        assert resp.data['is_read'] is True

    def test_mark_read_is_idempotent(self):
        """Calling mark_read on an already-read notification does not error."""
        tenant = make_tenant('MarkReadIdemT')
        user = make_user('mri@example.com', tenant)
        original_read_at = timezone.now() - timedelta(hours=1)
        notif = Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
            read_at=original_read_at,
        )

        resp = auth_client(user).post(f'/api/v1/notifications/{notif.pk}/read/')
        assert resp.status_code == 200
        notif.refresh_from_db()
        # read_at should not have changed
        assert notif.read_at == original_read_at

    def test_cannot_mark_another_users_notification(self):
        """User A cannot mark User B's notification as read (returns 404)."""
        tenant = make_tenant('MarkReadCrossT')
        user_a = make_user('mra@example.com', tenant)
        user_b = make_user('mrb@example.com', tenant, role='operator')
        notif_b = Notification.objects.create(
            user=user_b,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
        )

        resp = auth_client(user_a).post(f'/api/v1/notifications/{notif_b.pk}/read/')
        assert resp.status_code == 404


@pytest.mark.django_db
class TestMarkAllRead:
    """POST /api/v1/notifications/mark-all-read/ — bulk mark read."""

    def test_marks_all_unread_as_read(self):
        """All unread notifications for the user are marked read."""
        tenant = make_tenant('MarkAllT')
        user = make_user('ma@example.com', tenant)

        for i in range(3):
            Notification.objects.create(
                user=user,
                notification_type=Notification.NotificationType.SYSTEM_EVENT,
                event_type='device_offline',
                event_data={},
            )

        resp = auth_client(user).post('/api/v1/notifications/mark-all-read/')
        assert resp.status_code == 200
        assert resp.data['marked'] == 3
        assert Notification.objects.filter(user=user, read_at__isnull=True).count() == 0

    def test_mark_all_read_returns_zero_when_none_unread(self):
        """Returns marked=0 when all notifications are already read."""
        tenant = make_tenant('MarkAllZeroT')
        user = make_user('maz@example.com', tenant)
        Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
            read_at=timezone.now(),
        )

        resp = auth_client(user).post('/api/v1/notifications/mark-all-read/')
        assert resp.status_code == 200
        assert resp.data['marked'] == 0

    def test_mark_all_read_does_not_affect_other_users(self):
        """mark-all-read only affects the requesting user's notifications."""
        tenant = make_tenant('MarkAllScopeT')
        user_a = make_user('mas_a@example.com', tenant)
        user_b = make_user('mas_b@example.com', tenant, role='operator')

        Notification.objects.create(
            user=user_b,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='device_offline',
            event_data={},
        )

        auth_client(user_a).post('/api/v1/notifications/mark-all-read/')

        # User B's notification should still be unread
        assert Notification.objects.filter(user=user_b, read_at__isnull=True).count() == 1
