"""Serializers for the alerts app.

AlertSerializer — read-only representation used for list and detail endpoints.
    Includes computed site_names and device_names derived from the rule's
    conditions at query time (no denormalization).

AlertAcknowledgeSerializer — validates the optional note on acknowledge.
AlertResolveSerializer — no body required; exists for uniformity.

Ref: SPEC.md § Feature: Alerts
"""
from rest_framework import serializers

from .models import Alert


class AlertSerializer(serializers.ModelSerializer):
    """Read-only representation of an Alert with derived site and device names.

    site_names and device_names are computed by traversing:
        rule → condition_groups → conditions → stream → device → site

    The calling view must prefetch these relations to avoid N+1 queries.

    Ref: SPEC.md § Feature: Alerts
    """

    rule_name = serializers.CharField(source='rule.name', read_only=True)
    acknowledged_by_email = serializers.SerializerMethodField()
    resolved_by_email = serializers.SerializerMethodField()
    site_names = serializers.SerializerMethodField()
    device_names = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            'id',
            'rule',
            'rule_name',
            'tenant',
            'triggered_at',
            'status',
            'acknowledged_by',
            'acknowledged_by_email',
            'acknowledged_at',
            'acknowledged_note',
            'resolved_by',
            'resolved_by_email',
            'resolved_at',
            'site_names',
            'device_names',
        ]
        read_only_fields = fields

    def get_acknowledged_by_email(self, obj) -> str | None:
        """Return the email of the user who acknowledged the alert, or None."""
        return obj.acknowledged_by.email if obj.acknowledged_by_id else None

    def get_resolved_by_email(self, obj) -> str | None:
        """Return the email of the user who resolved the alert, or None."""
        return obj.resolved_by.email if obj.resolved_by_id else None

    def get_site_names(self, obj) -> list[str]:
        """Return sorted distinct site names from the rule's stream conditions."""
        sites = set()
        for group in obj.rule.condition_groups.all():
            for condition in group.conditions.all():
                stream = getattr(condition, 'stream', None)
                if stream and stream.device and stream.device.site:
                    sites.add(stream.device.site.name)
        return sorted(sites)

    def get_device_names(self, obj) -> list[str]:
        """Return sorted distinct device names from the rule's stream conditions."""
        devices = set()
        for group in obj.rule.condition_groups.all():
            for condition in group.conditions.all():
                stream = getattr(condition, 'stream', None)
                if stream and stream.device:
                    devices.add(stream.device.name)
        return sorted(devices)


class AlertAcknowledgeSerializer(serializers.Serializer):
    """Validates the body of POST /api/v1/alerts/:id/acknowledge/.

    The note field is optional — acknowledging with no note is permitted.
    """

    note = serializers.CharField(required=False, allow_blank=True, default='')


class AlertResolveSerializer(serializers.Serializer):
    """No-body serializer for POST /api/v1/alerts/:id/resolve/.

    Exists for uniformity and to support future resolution metadata.
    """
