"""Serializers for the notifications app.

Ref: SPEC.md § Feature: Notifications
"""
from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only representation of an in-app Notification.

    is_read is a computed convenience field (True when read_at is set).
    alert_rule_name surfaces the rule name for alert-type notifications so
    the frontend can render a meaningful title without a second request.

    Ref: SPEC.md § Feature: Notifications
    """

    is_read = serializers.SerializerMethodField()
    alert_rule_name = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'alert',
            'alert_rule_name',
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
