"""Serializers for the notifications app.

Ref: SPEC.md § Feature: Notifications
"""
from rest_framework import serializers

from .models import Notification, NotificationSnooze, UserNotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only representation of an in-app Notification.

    is_read is a computed convenience field (True when read_at is set).
    alert_rule_name surfaces the rule name for alert-type notifications so
    the frontend can render a meaningful title without a second request.

    Ref: SPEC.md § Feature: Notifications
    """

    is_read = serializers.SerializerMethodField()
    alert_rule_name = serializers.SerializerMethodField()
    alert_rule_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'alert',
            'alert_rule_name',
            'alert_rule_id',
            'event_type',
            'event_data',
            'channel',
            'sent_at',
            'read_at',
            'is_read',
            'delivery_status',
        ]
        read_only_fields = fields

    def get_is_read(self, obj) -> bool:
        """Return True when the notification has been read."""
        return obj.read_at is not None

    def get_alert_rule_name(self, obj) -> str | None:
        """Return the rule name for alert notifications, or None."""
        if obj.alert_id and obj.alert:
            return getattr(obj.alert.rule, 'name', None)
        return None

    def get_alert_rule_id(self, obj) -> int | None:
        """Return the rule PK for alert notifications, or None.

        Used by the frontend to construct the snooze request without a
        separate round-trip to look up the rule.
        """
        if obj.alert_id and obj.alert:
            return getattr(obj.alert, 'rule_id', None)
        return None


class UserNotificationPreferenceSerializer(serializers.ModelSerializer):
    """Read/write serializer for a user's notification channel preferences.

    GET returns the user's current preferences (created with defaults on first
    access). PUT updates any combination of fields.

    phone_number is optional but required for SMS delivery.

    Ref: SPEC.md § Feature: Notifications — Channels
    """

    class Meta:
        model = UserNotificationPreference
        fields = ['in_app_enabled', 'email_enabled', 'sms_enabled', 'phone_number']


class NotificationSnoozeSerializer(serializers.ModelSerializer):
    """Read representation of an active snooze.

    rule_name is included so the frontend can display the rule without a
    separate request.

    Ref: SPEC.md § Feature: Notifications — Notification snooze
    """

    rule_name = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = NotificationSnooze
        fields = ['id', 'rule', 'rule_name', 'snoozed_until', 'created_at', 'is_active']
        read_only_fields = fields

    def get_rule_name(self, obj) -> str | None:
        """Return the rule name for display."""
        return getattr(obj.rule, 'name', None)

    def get_is_active(self, obj) -> bool:
        """Return True if the snooze window has not yet expired."""
        from django.utils import timezone
        return obj.snoozed_until > timezone.now()


class SnoozeCreateSerializer(serializers.Serializer):
    """Input serializer for POST /api/v1/notifications/snooze/.

    Validates rule_id and duration_minutes (must be one of the allowed values).

    Ref: SPEC.md § Feature: Notifications — Notification snooze
    """

    ALLOWED_DURATIONS = [15, 60, 240, 1440]

    rule_id = serializers.IntegerField()
    duration_minutes = serializers.ChoiceField(choices=ALLOWED_DURATIONS)
