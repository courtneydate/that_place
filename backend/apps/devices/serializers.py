"""Serializers for the devices app."""
from rest_framework import serializers

from .models import Device, DeviceHealth, DeviceType, Site


class SiteSerializer(serializers.ModelSerializer):
    """Serializer for Site CRUD."""

    class Meta:
        model = Site
        fields = ('id', 'name', 'description', 'latitude', 'longitude', 'created_at')
        read_only_fields = ('id', 'created_at')


class DeviceTypeSerializer(serializers.ModelSerializer):
    """Serializer for DeviceType CRUD.

    Write operations are restricted to That Place Admins (enforced in the view).
    All authenticated users may read.
    """

    class Meta:
        model = DeviceType
        fields = (
            'id',
            'name',
            'slug',
            'description',
            'connection_type',
            'is_push',
            'default_offline_threshold_minutes',
            'command_ack_timeout_seconds',
            'commands',
            'stream_type_definitions',
            'status_indicator_mappings',
            'is_active',
            'created_at',
        )
        read_only_fields = ('id', 'created_at')


class DeviceSerializer(serializers.ModelSerializer):
    """Serializer for Device registration and retrieval.

    `status` and `topic_format` are read-only — status is managed via the
    approve/reject actions, topic_format is auto-detected from MQTT traffic.
    `health` is a read-only summary of the device's current health (null if
    no telemetry has been received yet).
    """

    device_type_name = serializers.CharField(source='device_type.name', read_only=True)
    site_name = serializers.CharField(source='site.name', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    health = serializers.SerializerMethodField()

    def get_health(self, obj):
        """Return a brief health summary for list views, or None if unavailable."""
        try:
            h = obj.devicehealth
        except DeviceHealth.DoesNotExist:
            return None
        return {
            'is_online': h.is_online,
            'activity_level': h.activity_level,
            'last_seen_at': h.last_seen_at,
        }

    class Meta:
        model = Device
        fields = (
            'id',
            'name',
            'serial_number',
            'site',
            'site_name',
            'device_type',
            'device_type_name',
            'tenant_name',
            'gateway_device',
            'status',
            'offline_threshold_override_minutes',
            'topic_format',
            'health',
            'created_at',
        )
        read_only_fields = ('id', 'status', 'topic_format', 'created_at', 'tenant_name', 'health')

    def validate_site(self, site):
        """Ensure the site belongs to the registering tenant."""
        request = self.context.get('request')
        if request and not request.user.is_that_place_admin:
            tenant = request.user.tenantuser.tenant
            if site.tenant_id != tenant.id:
                raise serializers.ValidationError(
                    'Site does not belong to your tenant.'
                )
        return site

    def validate_gateway_device(self, gateway_device):
        """Ensure the gateway device belongs to the registering tenant."""
        if gateway_device is None:
            return gateway_device
        request = self.context.get('request')
        if request and not request.user.is_that_place_admin:
            tenant = request.user.tenantuser.tenant
            if gateway_device.tenant_id != tenant.id:
                raise serializers.ValidationError(
                    'Gateway device does not belong to your tenant.'
                )
        return gateway_device


class DeviceHealthSerializer(serializers.ModelSerializer):
    """Read-only serializer for DeviceHealth. Used by GET /api/v1/devices/:id/health/."""

    class Meta:
        model = DeviceHealth
        fields = (
            'is_online',
            'last_seen_at',
            'first_active_at',
            'signal_strength',
            'battery_level',
            'activity_level',
            'updated_at',
        )
        read_only_fields = fields
