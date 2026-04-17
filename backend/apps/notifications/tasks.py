"""Celery tasks for notification creation.

create_alert_notifications(alert_id)
    Called after an Alert is committed to the database (via transaction.on_commit).
    Expands the rule's notify actions into a deduplicated set of target users and
    writes one in_app Notification row per user.

create_system_notification(event_type, tenant_id, event_data)
    Dispatched inline from device and integration tasks when platform events occur.
    Writes one in_app Notification row per Tenant Admin in the given tenant.

Both tasks create notifications via bulk_create for efficiency.

Ref: SPEC.md § Feature: Notifications
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='notifications.create_alert_notifications')
def create_alert_notifications(alert_id: int) -> None:
    """Create in_app Notification rows for all users targeted by a fired alert.

    Loads the Alert's rule and all notify actions. Expands each action's
    group_ids (NotificationGroup PKs) and user_ids (TenantUser PKs) into a
    deduplicated set of User PKs. Creates one Notification per user.

    Called via transaction.on_commit after the evaluate_rule atomic block
    to guarantee the Alert row exists before this task runs.

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
        # Expand group members
        if action.group_ids:
            member_user_pks = (
                TenantUser.objects
                .filter(
                    notification_memberships__group_id__in=action.group_ids,
                )
                .values_list('user_id', flat=True)
            )
            target_user_pks.update(member_user_pks)

        # Add individually targeted TenantUsers
        if action.user_ids:
            individual_user_pks = (
                TenantUser.objects
                .filter(pk__in=action.user_ids)
                .values_list('user_id', flat=True)
            )
            target_user_pks.update(individual_user_pks)

    if not target_user_pks:
        logger.debug(
            'create_alert_notifications: no target users for alert %d rule %d',
            alert_id, alert.rule_id,
        )
        return

    notifications = [
        Notification(
            user_id=user_pk,
            notification_type=Notification.NotificationType.ALERT,
            alert=alert,
            channel=Notification.Channel.IN_APP,
            delivery_status=Notification.DeliveryStatus.SENT,
        )
        for user_pk in target_user_pks
    ]
    Notification.objects.bulk_create(notifications)
    logger.info(
        'create_alert_notifications: created %d notification(s) for alert %d',
        len(notifications), alert_id,
    )


@shared_task(name='notifications.create_system_notification')
def create_system_notification(
    event_type: str,
    tenant_id: int,
    event_data: dict | None = None,
) -> None:
    """Create in_app Notification rows for all Tenant Admins in a tenant.

    Used for platform events: device_approved, device_offline, device_deleted,
    datasource_poll_failure. All Tenant Admins for the given tenant receive a
    notification; other roles do not.

    Dispatched as a Celery task (not called inline) to avoid adding write latency
    to the calling task — important at scale when tenant admin lists grow.

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
        logger.debug(
            'create_system_notification: no admins in tenant %d for event %s',
            tenant_id, event_type,
        )
        return

    notifications = [
        Notification(
            user_id=user_pk,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type=event_type,
            event_data=event_data or {},
            channel=Notification.Channel.IN_APP,
            delivery_status=Notification.DeliveryStatus.SENT,
        )
        for user_pk in admin_user_pks
    ]
    Notification.objects.bulk_create(notifications)
    logger.info(
        'create_system_notification: %s — created %d notification(s) for tenant %d',
        event_type, len(notifications), tenant_id,
    )
