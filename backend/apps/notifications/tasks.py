"""Celery tasks for notification creation and delivery.

create_alert_notifications(alert_id)
    Called after an Alert is committed (via transaction.on_commit). Expands
    rule notify actions into target users, filters out snoozed users, then
    creates one Notification row per user per enabled channel. Dispatches
    send_email_notification / send_sms_notification for non-in-app rows.

create_system_notification(event_type, tenant_id, event_data)
    Writes one in_app Notification per Tenant Admin in the given tenant.

send_email_notification(notification_id)
    Sends a single email Notification via the configured SMTP backend.
    Updates delivery_status to 'delivered' on success, 'failed' on error.
    Retried once after 60 s on failure.

send_sms_notification(notification_id)
    Sends a single SMS Notification via Twilio. Same retry behaviour.

Ref: SPEC.md § Feature: Notifications
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Allowed snooze durations in minutes (validated at the API layer too).
SNOOZE_DURATIONS = {15, 60, 240, 1440}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_alert_subject(alert) -> str:
    """Return the email subject line for an alert notification."""
    return f'[That Place] Alert: {alert.rule.name}'


def _build_alert_body(alert) -> str:
    """Return the plain-text email body for an alert notification."""
    lines = [
        f'Alert: {alert.rule.name}',
        f'Triggered: {alert.triggered_at.strftime("%Y-%m-%d %H:%M UTC")}',
        f'Status: {alert.status}',
        '',
        'Log in to That Place to acknowledge or resolve this alert.',
    ]
    return '\n'.join(lines)


def _get_active_snooze_user_pks(rule_id: int) -> set[int]:
    """Return the set of user PKs with an active snooze on the given rule."""
    from .models import NotificationSnooze
    return set(
        NotificationSnooze.objects
        .filter(rule_id=rule_id, snoozed_until__gt=timezone.now())
        .values_list('user_id', flat=True)
    )


def _get_preferences(user_pks: set[int]) -> dict:
    """Return a dict of user_pk → UserNotificationPreference for the given users.

    Users with no preference row are treated as having defaults (in-app on,
    email on, SMS off).
    """
    from .models import UserNotificationPreference

    class _Defaults:
        in_app_enabled = True
        email_enabled = True
        sms_enabled = False
        phone_number = ''

    prefs = {
        p.user_id: p
        for p in UserNotificationPreference.objects.filter(user_id__in=user_pks)
    }
    # Fill missing entries with defaults
    for pk in user_pks:
        if pk not in prefs:
            prefs[pk] = _Defaults()
    return prefs


# ---------------------------------------------------------------------------
# Alert notification creation
# ---------------------------------------------------------------------------

@shared_task(name='notifications.create_alert_notifications')
def create_alert_notifications(alert_id: int) -> None:
    """Create Notification rows for all users targeted by a fired alert.

    For each targeted user:
      - Skip if an active NotificationSnooze exists for this rule.
      - Create an in_app Notification if in_app_enabled (default True).
      - Create an email Notification if email_enabled (default True),
        then dispatch send_email_notification.
      - Create an sms Notification if sms_enabled + phone_number set,
        then dispatch send_sms_notification.

    Ref: SPEC.md § Feature: Notifications — alert-triggered notifications
    """
    from apps.accounts.models import TenantUser
    from apps.alerts.models import Alert

    from .models import Notification

    try:
        alert = (
            Alert.objects
            .select_related('rule')
            .prefetch_related('rule__actions')
            .get(pk=alert_id)
        )
    except Alert.DoesNotExist:
        logger.warning('create_alert_notifications: alert %d not found', alert_id)
        return

    notify_actions = [a for a in alert.rule.actions.all() if a.action_type == 'notify']
    if not notify_actions:
        logger.debug(
            'create_alert_notifications: rule %d has no notify actions — skipping',
            alert.rule_id,
        )
        return

    # Collect all targeted User PKs (deduplicated)
    target_user_pks: set[int] = set()
    for action in notify_actions:
        if action.group_ids:
            target_user_pks.update(
                TenantUser.objects
                .filter(notification_memberships__group_id__in=action.group_ids)
                .values_list('user_id', flat=True)
            )
        if action.user_ids:
            target_user_pks.update(
                TenantUser.objects
                .filter(pk__in=action.user_ids)
                .values_list('user_id', flat=True)
            )

    if not target_user_pks:
        logger.debug(
            'create_alert_notifications: no target users for alert %d', alert_id,
        )
        return

    # Filter out snoozed users
    snoozed_pks = _get_active_snooze_user_pks(alert.rule_id)
    active_pks = target_user_pks - snoozed_pks
    if not active_pks:
        logger.debug(
            'create_alert_notifications: all %d target users snoozed for rule %d',
            len(target_user_pks), alert.rule_id,
        )
        return

    prefs = _get_preferences(active_pks)

    in_app_rows = []
    email_rows = []
    sms_rows = []

    for user_pk in active_pks:
        pref = prefs[user_pk]
        if pref.in_app_enabled:
            in_app_rows.append(Notification(
                user_id=user_pk,
                notification_type=Notification.NotificationType.ALERT,
                alert=alert,
                channel=Notification.Channel.IN_APP,
                delivery_status=Notification.DeliveryStatus.SENT,
            ))
        if pref.email_enabled:
            email_rows.append(Notification(
                user_id=user_pk,
                notification_type=Notification.NotificationType.ALERT,
                alert=alert,
                channel=Notification.Channel.EMAIL,
                delivery_status=Notification.DeliveryStatus.SENT,
            ))
        if pref.sms_enabled and pref.phone_number:
            sms_rows.append(Notification(
                user_id=user_pk,
                notification_type=Notification.NotificationType.ALERT,
                alert=alert,
                channel=Notification.Channel.SMS,
                delivery_status=Notification.DeliveryStatus.SENT,
            ))

    # Bulk create in-app (no follow-up task needed)
    if in_app_rows:
        Notification.objects.bulk_create(in_app_rows)

    # Create email rows then dispatch delivery per notification
    if email_rows:
        created_email = Notification.objects.bulk_create(email_rows)
        for notif in created_email:
            send_email_notification.delay(notif.pk)

    # Create SMS rows then dispatch delivery per notification
    if sms_rows:
        created_sms = Notification.objects.bulk_create(sms_rows)
        for notif in created_sms:
            send_sms_notification.delay(notif.pk)

    logger.info(
        'create_alert_notifications: alert %d — in_app=%d email=%d sms=%d '
        '(snoozed=%d)',
        alert_id, len(in_app_rows), len(email_rows), len(sms_rows),
        len(snoozed_pks & target_user_pks),
    )


# ---------------------------------------------------------------------------
# System event notification creation
# ---------------------------------------------------------------------------

@shared_task(name='notifications.create_system_notification')
def create_system_notification(
    event_type: str,
    tenant_id: int,
    event_data: dict | None = None,
) -> None:
    """Create in_app Notification rows for all Tenant Admins in a tenant.

    Used for platform events: device_approved, device_offline, device_deleted,
    datasource_poll_failure. Admins only; no email/SMS for system events in MVP.

    Ref: SPEC.md § Feature: Notifications — system event notifications
    """
    from apps.accounts.models import TenantUser

    from .models import Notification

    admin_user_pks = list(
        TenantUser.objects
        .filter(tenant_id=tenant_id, role=TenantUser.Role.ADMIN)
        .values_list('user_id', flat=True)
    )
    if not admin_user_pks:
        return

    notifications = [
        Notification(
            user_id=pk,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type=event_type,
            event_data=event_data or {},
            channel=Notification.Channel.IN_APP,
            delivery_status=Notification.DeliveryStatus.SENT,
        )
        for pk in admin_user_pks
    ]
    Notification.objects.bulk_create(notifications)
    logger.info(
        'create_system_notification: %s — created %d notification(s) for tenant %d',
        event_type, len(notifications), tenant_id,
    )


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

@shared_task(
    name='notifications.send_email_notification',
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def send_email_notification(self, notification_id: int) -> None:
    """Send a single email Notification via the configured SMTP backend.

    Updates delivery_status to 'delivered' on success or 'failed' after the
    single retry is exhausted. Skips gracefully if the notification no longer
    exists.

    Ref: SPEC.md § Feature: Notifications — delivery failure logging
    """
    from django.core.mail import send_mail

    from .models import Notification

    try:
        notif = (
            Notification.objects
            .select_related('alert__rule', 'user')
            .get(pk=notification_id, channel=Notification.Channel.EMAIL)
        )
    except Notification.DoesNotExist:
        logger.warning('send_email_notification: notification %d not found', notification_id)
        return

    recipient = notif.user.email
    if not recipient:
        logger.warning(
            'send_email_notification: user %d has no email — skipping', notif.user_id,
        )
        notif.delivery_status = Notification.DeliveryStatus.FAILED
        notif.save(update_fields=['delivery_status'])
        return

    try:
        subject = _build_alert_subject(notif.alert)
        body = _build_alert_body(notif.alert)
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
        notif.delivery_status = Notification.DeliveryStatus.DELIVERED
        notif.save(update_fields=['delivery_status'])
        logger.info('send_email_notification: sent to %s (notification %d)', recipient, notification_id)
    except Exception as exc:
        logger.error(
            'send_email_notification: failed for notification %d (%s) — %s',
            notification_id, recipient, exc,
        )
        # Celery re-raises the original exc (not MaxRetriesExceededError) when
        # max_retries is exceeded with an exc= argument, so guard explicitly.
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        notif.delivery_status = Notification.DeliveryStatus.FAILED
        notif.save(update_fields=['delivery_status'])


# ---------------------------------------------------------------------------
# SMS delivery
# ---------------------------------------------------------------------------

@shared_task(
    name='notifications.send_sms_notification',
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def send_sms_notification(self, notification_id: int) -> None:
    """Send a single SMS Notification via Twilio.

    Reads TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER from
    Django settings. Skips if any are missing. The user's phone number is
    read from UserNotificationPreference.phone_number.

    Updates delivery_status to 'delivered' on success or 'failed' after the
    single retry is exhausted.

    Ref: SPEC.md § Feature: Notifications — SMS delivery
    """
    from .models import Notification, UserNotificationPreference

    sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')

    if not all([sid, token, from_number]):
        logger.warning(
            'send_sms_notification: Twilio credentials not configured — skipping notification %d',
            notification_id,
        )
        return

    try:
        notif = (
            Notification.objects
            .select_related('alert__rule', 'user')
            .get(pk=notification_id, channel=Notification.Channel.SMS)
        )
    except Notification.DoesNotExist:
        logger.warning('send_sms_notification: notification %d not found', notification_id)
        return

    try:
        pref = UserNotificationPreference.objects.get(user_id=notif.user_id)
        phone = pref.phone_number
    except UserNotificationPreference.DoesNotExist:
        phone = ''

    if not phone:
        logger.warning(
            'send_sms_notification: user %d has no phone number — skipping', notif.user_id,
        )
        notif.delivery_status = Notification.DeliveryStatus.FAILED
        notif.save(update_fields=['delivery_status'])
        return

    body = (
        f'That Place Alert: {notif.alert.rule.name} — '
        f'triggered {notif.alert.triggered_at.strftime("%Y-%m-%d %H:%M UTC")}'
    )

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        client.messages.create(to=phone, from_=from_number, body=body)
        notif.delivery_status = Notification.DeliveryStatus.DELIVERED
        notif.save(update_fields=['delivery_status'])
        logger.info('send_sms_notification: sent to %s (notification %d)', phone, notification_id)
    except Exception as exc:
        logger.error(
            'send_sms_notification: failed for notification %d (%s) — %s',
            notification_id, phone, exc,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        notif.delivery_status = Notification.DeliveryStatus.FAILED
        notif.save(update_fields=['delivery_status'])
