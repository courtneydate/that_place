"""Notification models for That Place.

Notification — a single delivery of an event to a user (one row per user
per channel). Two notification_type values are supported:

  alert        — created when a rule fires; alert_id is set.
  system_event — created for platform events (device approved/offline/deleted,
                 DataSource poll failure).

UserNotificationPreference — per-user channel opt-in/opt-out settings and
SMS phone number. Created on first access with default values (in-app on,
email on, SMS off).

NotificationSnooze — per-user per-rule snooze window. While active,
create_alert_notifications skips writing any notification for that user.

Ref: SPEC.md § Feature: Notifications, § Data Model
"""
from django.conf import settings
from django.db import models


class Notification(models.Model):
    """An in-app notification delivered to a single user.

    Created by Celery tasks — never directly by views. Each fired alert and
    each system event generates one Notification row per targeted user.

    read_at is null for unread notifications; set to now() when the user marks
    it read individually or via mark-all-read.

    Ref: SPEC.md § Feature: Notifications
    """

    class NotificationType(models.TextChoices):
        ALERT = 'alert', 'Alert'
        SYSTEM_EVENT = 'system_event', 'System event'

    class Channel(models.TextChoices):
        IN_APP = 'in_app', 'In-app'
        EMAIL = 'email', 'Email'
        SMS = 'sms', 'SMS'
        PUSH = 'push', 'Push'

    class DeliveryStatus(models.TextChoices):
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
    )
    alert = models.ForeignKey(
        'alerts.Alert',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='notifications',
    )
    event_type = models.CharField(
        max_length=50,
        blank=True,
        help_text=(
            'For system_event notifications: device_approved, device_offline, '
            'device_deleted, datasource_poll_failure.'
        ),
    )
    event_data = models.JSONField(
        null=True,
        blank=True,
        help_text='Context for the event — device name, serial, etc.',
    )
    channel = models.CharField(
        max_length=10,
        choices=Channel.choices,
        default=Channel.IN_APP,
    )
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(
        max_length=10,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.SENT,
    )

    class Meta:
        ordering = ['-sent_at']

    def __str__(self) -> str:
        """Return a human-readable description of the notification."""
        return (
            f'Notification({self.pk}) '
            f'user={self.user_id} type={self.notification_type} '
            f'read={self.read_at is not None}'
        )


class UserNotificationPreference(models.Model):
    """Per-user notification channel preferences and SMS contact number.

    Created on first GET with default values (in-app on, email on, SMS off).
    get_or_create should always be used when reading to ensure a row exists.

    phone_number is required for SMS delivery — if blank, SMS is skipped even
    when sms_enabled is True.

    Ref: SPEC.md § Feature: Notifications — Channels
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preference',
    )
    in_app_enabled = models.BooleanField(
        default=True,
        help_text='Show notifications in the in-app bell/dropdown.',
    )
    email_enabled = models.BooleanField(
        default=True,
        help_text='Send email notifications. On by default — user must opt out.',
    )
    sms_enabled = models.BooleanField(
        default=False,
        help_text='Send SMS notifications. Off by default — user must opt in.',
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text='E.164 format preferred (e.g. +61412345678). Required for SMS delivery.',
    )

    def __str__(self) -> str:
        """Return a human-readable summary of this preference record."""
        return (
            f'UserNotificationPreference(user={self.user_id} '
            f'email={self.email_enabled} sms={self.sms_enabled})'
        )


class NotificationSnooze(models.Model):
    """Suppresses notifications for a specific user + rule combination.

    While snoozed_until is in the future, create_alert_notifications will not
    write any Notification row for this user when the rule fires. Existing
    notifications are unaffected.

    unique_together (user, rule) ensures there is at most one active snooze
    per pair. Re-snoozing updates snoozed_until via update_or_create.

    Ref: SPEC.md § Feature: Notifications — Notification snooze
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_snoozes',
    )
    rule = models.ForeignKey(
        'rules.Rule',
        on_delete=models.CASCADE,
        related_name='notification_snoozes',
    )
    snoozed_until = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'rule')]

    def __str__(self) -> str:
        """Return a human-readable description of the snooze."""
        return (
            f'NotificationSnooze(user={self.user_id} '
            f'rule={self.rule_id} until={self.snoozed_until})'
        )
