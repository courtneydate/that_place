"""Sprint 24 tests — push notifications via Expo.

Covers:
  - UserPushToken CRUD endpoint: register / list / delete + cross-user scoping
  - Re-registering the same token is idempotent (upsert refreshes label)
  - create_alert_notifications dispatches push only for users with a token
  - send_push_notification posts to Expo, sets delivery_status from the
    immediate ticket, and removes DeviceNotRegistered stale tokens

Ref: SPEC.md § Feature: Notifications — mobile push; ROADMAP Sprint 24
"""
from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.alerts.models import Alert
from apps.notifications.models import Notification, UserPushToken
from apps.notifications.tasks import (
    create_alert_notifications,
    send_push_notification,
)
from apps.rules.models import Rule, RuleAction

PUSH_TOKENS_URL = '/api/v1/notifications/push-tokens/'


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _fake_expo_response(tickets):
    """Return a MagicMock requests.Response mimicking the Expo Push API."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {'data': tickets}
    return resp


@pytest.fixture(autouse=True)
def _eager_and_mock_expo(settings, monkeypatch):
    """Run Celery eagerly and stub Expo HTTP calls with a benign success.

    Individual tests can override the requests.post stub with their own to
    exercise specific Expo responses.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    def _fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        return _fake_expo_response(
            [{'status': 'ok', 'id': f'ticket-{i}'} for i in range(len(json or []))]
        )

    monkeypatch.setattr('requests.post', _fake_post)


def make_tenant(name):
    """Create a tenant with a slugified name."""
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email, tenant, role='admin'):
    """Create a User with a TenantUser membership in the given tenant."""
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def _make_alert(tenant, tenant_user, created_by):
    """Create a Rule + notify action targeting `tenant_user` + an active Alert."""
    rule = Rule.objects.create(
        tenant=tenant,
        name='Test rule',
        is_active=True,
        condition_group_operator='AND',
        created_by=created_by,
    )
    RuleAction.objects.create(
        rule=rule,
        action_type=RuleAction.ActionType.NOTIFY,
        notification_channels=['in_app', 'email', 'push'],
        group_ids=[],
        user_ids=[tenant_user.pk],
        message_template='Alert!',
    )
    return Alert.objects.create(
        rule=rule,
        tenant=tenant,
        status=Alert.Status.ACTIVE,
        triggered_at=timezone.now(),
    )


def auth(user):
    """Return an APIClient authenticated as the given user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# UserPushToken CRUD endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPushTokenEndpoint:
    """Register / list / delete an authenticated user's Expo push tokens."""

    def test_register_token(self):
        """Posting a token registers it for the requesting user."""
        tenant = make_tenant('PT-Reg')
        user = make_user('pt-reg@example.com', tenant)
        resp = auth(user).post(PUSH_TOKENS_URL, {
            'token': 'ExponentPushToken[abc123]', 'label': 'iPhone 15',
        })
        assert resp.status_code == 201
        assert UserPushToken.objects.filter(
            user=user, token='ExponentPushToken[abc123]',
        ).exists()

    def test_re_register_same_token_is_idempotent(self):
        """Re-posting the same token refreshes the existing row (no duplicate)."""
        tenant = make_tenant('PT-Idem')
        user = make_user('pt-idem@example.com', tenant)
        first = auth(user).post(PUSH_TOKENS_URL, {
            'token': 'ExponentPushToken[same]', 'label': 'a',
        })
        second = auth(user).post(PUSH_TOKENS_URL, {
            'token': 'ExponentPushToken[same]', 'label': 'b',
        })
        assert first.status_code == 201
        assert second.status_code == 200
        assert first.data['id'] == second.data['id']
        # Label refreshes on re-register.
        assert UserPushToken.objects.get(pk=first.data['id']).label == 'b'

    def test_list_returns_only_current_users_tokens(self):
        """A user only sees their own tokens, not anyone else's."""
        tenant = make_tenant('PT-Scope')
        user_a = make_user('pt-a@example.com', tenant)
        user_b = make_user('pt-b@example.com', tenant, role='operator')
        UserPushToken.objects.create(user=user_a, token='AAA')
        UserPushToken.objects.create(user=user_b, token='BBB')

        resp = auth(user_a).get(PUSH_TOKENS_URL)

        tokens = [t['token'] for t in resp.data]
        assert tokens == ['AAA']

    def test_cannot_delete_other_users_token(self):
        """Deleting a token belonging to another user returns 404."""
        tenant = make_tenant('PT-Del')
        user_a = make_user('pt-del-a@example.com', tenant)
        user_b = make_user('pt-del-b@example.com', tenant, role='operator')
        other_token = UserPushToken.objects.create(user=user_b, token='OTHER')

        resp = auth(user_a).delete(f'{PUSH_TOKENS_URL}{other_token.pk}/')

        assert resp.status_code == 404
        assert UserPushToken.objects.filter(pk=other_token.pk).exists()

    def test_unauthenticated_rejected(self):
        """An unauthenticated request is rejected."""
        resp = APIClient().get(PUSH_TOKENS_URL)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# create_alert_notifications — push fan-out
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAlertPushFanOut:
    """An alert fires a push Notification only when the user has a token."""

    def test_user_with_token_gets_push_notification(self):
        """A user with a registered token gets a push-channel Notification row."""
        tenant = make_tenant('PFO-1')
        user = make_user('pfo-1@example.com', tenant)
        UserPushToken.objects.create(user=user, token='ExponentPushToken[T1]')
        alert = _make_alert(tenant, user.tenantuser, created_by=user)

        create_alert_notifications(alert.pk)

        assert Notification.objects.filter(
            user=user, channel=Notification.Channel.PUSH,
        ).count() == 1

    def test_user_without_token_gets_no_push(self):
        """A user with no registered token gets no push-channel Notification."""
        tenant = make_tenant('PFO-2')
        user = make_user('pfo-2@example.com', tenant)
        alert = _make_alert(tenant, user.tenantuser, created_by=user)

        create_alert_notifications(alert.pk)

        assert Notification.objects.filter(
            user=user, channel=Notification.Channel.PUSH,
        ).count() == 0

    def test_multiple_tokens_yield_one_notification_row(self):
        """One push Notification per user — fan-out across tokens happens in send."""
        tenant = make_tenant('PFO-3')
        user = make_user('pfo-3@example.com', tenant)
        UserPushToken.objects.create(user=user, token='ExponentPushToken[D1]')
        UserPushToken.objects.create(user=user, token='ExponentPushToken[D2]')
        alert = _make_alert(tenant, user.tenantuser, created_by=user)

        create_alert_notifications(alert.pk)

        assert Notification.objects.filter(
            user=user, channel=Notification.Channel.PUSH,
        ).count() == 1


# ---------------------------------------------------------------------------
# send_push_notification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendPushNotification:
    """The Celery task that actually posts to Expo Push."""

    def _make_push_notif(self, user, message='Hello'):
        """Create a system-event push Notification (no alert needed)."""
        return Notification.objects.create(
            user=user,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            channel=Notification.Channel.PUSH,
            message=message,
            delivery_status=Notification.DeliveryStatus.SENT,
        )

    def test_delivered_when_expo_returns_ok(self, monkeypatch):
        """A successful ticket marks the notification delivered."""
        user = User.objects.create_user(email='sp-ok@example.com', password='pw')
        UserPushToken.objects.create(user=user, token='ExponentPushToken[OK]')
        notif = self._make_push_notif(user)

        captured = {}

        def _fake_post(url, json=None, **kwargs):
            captured['url'] = url
            captured['payload'] = json
            return _fake_expo_response([{'status': 'ok', 'id': 't-ok'}])

        monkeypatch.setattr('requests.post', _fake_post)

        send_push_notification(notif.pk)

        notif.refresh_from_db()
        assert notif.delivery_status == Notification.DeliveryStatus.DELIVERED
        assert captured['url'] == 'https://exp.host/--/api/v2/push/send'
        assert captured['payload'][0]['to'] == 'ExponentPushToken[OK]'

    def test_no_tokens_marks_failed(self):
        """If the user has no registered tokens, delivery_status is failed."""
        user = User.objects.create_user(email='sp-no@example.com', password='pw')
        notif = self._make_push_notif(user)

        send_push_notification(notif.pk)

        notif.refresh_from_db()
        assert notif.delivery_status == Notification.DeliveryStatus.FAILED

    def test_device_not_registered_removes_token(self, monkeypatch):
        """A DeviceNotRegistered error deletes the stale token."""
        user = User.objects.create_user(email='sp-dn@example.com', password='pw')
        UserPushToken.objects.create(user=user, token='ExponentPushToken[STALE]')
        notif = self._make_push_notif(user)

        def _fake_post(url, json=None, **kwargs):
            return _fake_expo_response([{
                'status': 'error',
                'message': 'Device not registered',
                'details': {'error': 'DeviceNotRegistered'},
            }])

        monkeypatch.setattr('requests.post', _fake_post)

        send_push_notification(notif.pk)

        assert not UserPushToken.objects.filter(
            token='ExponentPushToken[STALE]',
        ).exists()
        notif.refresh_from_db()
        # Zero of one delivered — overall delivery_status is failed.
        assert notif.delivery_status == Notification.DeliveryStatus.FAILED
