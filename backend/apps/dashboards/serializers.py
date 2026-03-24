"""Serializers for the dashboards app.

Ref: SPEC.md § Feature: Dashboards & Visualisation
"""
from rest_framework import serializers

from apps.readings.models import Stream

from .models import Dashboard, DashboardWidget

_VALID_COLUMNS = frozenset({1, 2, 3})


class DashboardWidgetSerializer(serializers.ModelSerializer):
    """Serializer for DashboardWidget — used for create/update and nested display."""

    class Meta:
        model = DashboardWidget
        fields = (
            'id',
            'widget_type',
            'stream_ids',
            'config',
            'position',
            'created_at',
        )
        read_only_fields = ('id', 'created_at')

    def validate_stream_ids(self, value):
        """Validate stream_ids is a list of ints, all accessible to the requesting tenant."""
        if not isinstance(value, list):
            raise serializers.ValidationError('stream_ids must be a list.')
        if not all(isinstance(i, int) for i in value):
            raise serializers.ValidationError('All stream_ids must be integers.')
        if value:
            request = self.context.get('request')
            if request and not request.user.is_that_place_admin:
                tenant = request.user.tenantuser.tenant
                valid_ids = set(
                    Stream.objects.filter(
                        device__tenant=tenant,
                        pk__in=value,
                    ).values_list('pk', flat=True)
                )
                invalid = set(value) - valid_ids
                if invalid:
                    raise serializers.ValidationError(
                        f'Stream IDs not found or not accessible: {sorted(invalid)}'
                    )
        return value


class DashboardSerializer(serializers.ModelSerializer):
    """Serializer for Dashboard list and detail, including nested widgets."""

    widgets = DashboardWidgetSerializer(many=True, read_only=True)
    created_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Dashboard
        fields = (
            'id',
            'name',
            'columns',
            'widgets',
            'created_by_email',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'widgets', 'created_by_email', 'created_at', 'updated_at')

    def get_created_by_email(self, obj):
        """Return the email of the dashboard creator, or None if the user was deleted."""
        return obj.created_by.email if obj.created_by else None

    def validate_columns(self, value):
        """Columns must be 1, 2, or 3."""
        if value not in _VALID_COLUMNS:
            raise serializers.ValidationError('columns must be 1, 2, or 3.')
        return value
