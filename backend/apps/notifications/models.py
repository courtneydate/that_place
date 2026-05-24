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
        max_length=64,
        blank=True,
        help_text=(
            'For system_event notifications: the NotificationEventType.key '
            'this notification was emitted from (e.g. device_offline).'
        ),
    )
    event_data = models.JSONField(
        null=True,
        blank=True,
        help_text='Context for the event — device name, serial, etc.',
    )
    message = models.TextField(
        blank=True,
        help_text=(
            'Rendered notification text. Populated for system/platform events '
            'from the NotificationEventType template; blank for alert '
            'notifications (the frontend renders those from the alert).'
        ),
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


class NotificationEventType(models.Model):
    """DB-backed registry of system-event and platform-event types.

    Each record defines how one kind of event becomes notifications: its
    severity, who receives it (audience), which channels it uses, the
    event_data keys it carries (metadata_schema), and the message template
    rendered into the notification text. New event types are added as data —
    only the code that detects a condition and calls emit_event() is
    code-level.

    Resolves SPEC.md §9 ⚑ "Notification event registry".

    Ref: SPEC.md § Data Model — NotificationEventType; ROADMAP Sprint 23
    """

    class Severity(models.TextChoices):
        INFO = 'info', 'Info'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    class Audience(models.TextChoices):
        PLATFORM_ADMIN = 'platform_admin', 'That Place Admins'
        TENANT = 'tenant', 'Tenant Admins'

    # The channels an event type may deliver on in v1 (in-app + email).
    # Outbound webhook delivery is flagged for future development.
    VALID_CHANNELS = ('in_app', 'email')

    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text='Stable event identifier, e.g. "device_offline". Stored on Notification.event_type.',
    )
    label = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.INFO,
    )
    audience = models.CharField(
        max_length=20,
        choices=Audience.choices,
        help_text=(
            'platform_admin → delivered to all That Place Admins; '
            'tenant → delivered to the Tenant Admins of the emitting tenant.'
        ),
    )
    default_channels = models.JSONField(
        default=list,
        help_text='Channels this event delivers on, e.g. ["in_app", "email"].',
    )
    metadata_schema = models.JSONField(
        default=list,
        help_text=(
            'The event_data keys this event carries — documents the template '
            'placeholders available to message_template.'
        ),
    )
    message_template = models.TextField(
        help_text=(
            'Notification text. Placeholders are filled from event_data, '
            'e.g. "Device {device_name} went offline".'
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive event types are skipped by emit_event().',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['key']

    def __str__(self) -> str:
        """Return a human-readable identifier for the event type."""
        return f'NotificationEventType({self.key})'

    def render(self, metadata: dict | None) -> str:
        """Render message_template against event metadata.

        Missing placeholders resolve to an empty string rather than raising,
        so a template/metadata mismatch degrades gracefully instead of
        dropping the notification.
        """
        from collections import defaultdict

        safe = defaultdict(str, metadata or {})
        try:
            return self.message_template.format_map(safe)
        except (ValueError, IndexError, KeyError):
            return self.message_template


class UserPushToken(models.Model):
    """An Expo push token registered by a user's mobile device.

    One user can register multiple devices (phone + tablet); each device's
    Expo token is a separate row. The mobile app POSTs its token on launch
    or after the OS-level permission grant; the backend upserts on the token
    string so re-registration refreshes ``last_seen_at`` instead of creating
    duplicates. There is no separate ``push_enabled`` toggle — the presence
    of a registered token is the user's consent (the OS permission grant
    gated registration in the first place).

    Ref: SPEC.md § Feature: Notifications — mobile push; ROADMAP Sprint 24
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_tokens',
    )
    token = models.CharField(
        max_length=255,
        unique=True,
        help_text='Expo push token, e.g. "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]".',
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text='Optional device label, e.g. "iPhone 15".',
    )
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_seen_at']

    def __str__(self) -> str:
        """Return a human-readable identifier (last 8 chars of the token)."""
        return f'UserPushToken(user={self.user_id} ...{self.token[-8:]})'
