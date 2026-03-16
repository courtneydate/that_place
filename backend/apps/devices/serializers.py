"""Serializers for the devices app."""
from rest_framework import serializers

from .models import Device, DeviceType, Site


class SiteSerializer(serializers.ModelSerializer):
    """Serializer for Site CRUD."""

    class Meta:
        model = Site
        fields = ('id', 'name', 'description', 'latitude', 'longitude', 'created_at')
        read_only_fields = ('id', 'created_at')


class DeviceTypeSerializer(serializers.ModelSerializer):
    """Serializer for DeviceType CRUD.

    Write operations are restricted to Fieldmouse Admins (enforced in the view).
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
            'is_active',
            'created_at',
        )
        read_only_fields = ('id', 'created_at')


class DeviceSerializer(serializers.ModelSerializer):
    """Serializer for Device registration and retrieval.

    `status` and `topic_format` are read-only — status is managed via the
    approve/reject actions, topic_format is auto-detected from MQTT traffic.
    """

    device_type_name = serializers.CharField(source='device_type.name', read_only=True)
    site_name = serializers.CharField(source='site.name', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

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
            'created_at',
        )
        read_only_fields = ('id', 'status', 'topic_format', 'created_at', 'tenant_name')

    def validate_site(self, site):
        """Ensure the site belongs to the registering tenant."""
        request = self.context.get('request')
        if request and not request.user.is_fieldmouse_admin:
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
        if request and not request.user.is_fieldmouse_admin:
            tenant = request.user.tenantuser.tenant
            if gateway_device.tenant_id != tenant.id:
                raise serializers.ValidationError(
                    'Gateway device does not belong to your tenant.'
                )
        return gateway_device
