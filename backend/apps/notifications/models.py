"""Notification model for That Place.

A Notification represents a single delivery of an event to a user's in-app
inbox. Two notification_type values are supported:

  alert       — created when a rule fires; alert_id is set.
  system_event — created for platform events (device approved/offline/deleted,
                 DataSource poll failure); event_type and event_data are set.

Sprint 19 creates in_app channel only. Email/SMS/push are added in Sprint 20+.

Ref: SPEC.md § Feature: Notifications, § Data Model — Notification
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
