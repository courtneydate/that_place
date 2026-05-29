"""Serializers for the devices app."""
from rest_framework import serializers

from .models import CommandLog, Device, DeviceHealth, DeviceType, Site


class SiteSerializer(serializers.ModelSerializer):
    """Serializer for Site CRUD.

    The hierarchical-metering fields (Sprint 29) are exposed here so a Tenant
    Admin can flag a site as an embedded network and tune its reconciliation
    behaviour. Toggling `is_hierarchical` once meters exist is gated by
    `validate_is_hierarchical` to keep the MeterProfile invariants intact.
    """

    HIERARCHICAL_ROLES = ('gate', 'child', 'common_area')

    class Meta:
        model = Site
        fields = (
            'id', 'name', 'description', 'latitude', 'longitude',
            'is_hierarchical',
            'reconciliation_tolerance_percent',
            'embedded_network_exemption_id',
            'common_area_apportionment_method',
            'created_at',
        )
        read_only_fields = ('id', 'created_at')

    def validate_reconciliation_tolerance_percent(self, value):
        """Sane bounds — variance over 100% is a configuration mistake."""
        if value is None:
            return value
        if value < 0 or value > 100:
            raise serializers.ValidationError(
                'reconciliation_tolerance_percent must be between 0 and 100.'
            )
        return value

    def validate(self, attrs):
        """Guard the `is_hierarchical` toggle against existing meter profiles.

        Flipping the flag would either orphan hierarchical meters or create
        invariant violations on existing child/common_area meters — both
        cases need an explicit cleanup before the flag can move.
        """
        if self.instance is None:
            return attrs
        if 'is_hierarchical' not in attrs:
            return attrs
        new_value = attrs['is_hierarchical']
        if new_value == self.instance.is_hierarchical:
            return attrs

        from apps.metering.models import MeterProfile

        if new_value is False:
            # hierarchical → flat — block if any hierarchical meters exist
            existing = MeterProfile.objects.filter(
                device__site_id=self.instance.id,
                meter_role__in=self.HIERARCHICAL_ROLES,
            )
            count = existing.count()
            if count:
                raise serializers.ValidationError({
                    'is_hierarchical': (
                        f'Cannot disable hierarchical mode while {count} '
                        'gate/child/common_area meter(s) exist on this site. '
                        'Remove or reassign them first.'
                    ),
                })
        else:
            # flat → hierarchical — block if existing child/common_area meters
            # lack a parent, because the invariant becomes load-bearing.
            invalid = MeterProfile.objects.filter(
                device__site_id=self.instance.id,
                meter_role__in=('child', 'common_area'),
                parent_meter__isnull=True,
            ).count()
            if invalid:
                raise serializers.ValidationError({
                    'is_hierarchical': (
                        f'Cannot enable hierarchical mode: {invalid} child/'
                        'common_area meter(s) on this site have no parent. '
                        'Add a gate meter and assign parents first.'
                    ),
                })
        return attrs


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
    device_type_commands = serializers.JSONField(source='device_type.commands', read_only=True)
    site_name = serializers.CharField(source='site.name', read_only=True)
    site_is_hierarchical = serializers.BooleanField(source='site.is_hierarchical', read_only=True)
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
            'site_is_hierarchical',
            'device_type',
            'device_type_name',
            'device_type_commands',
            'tenant_name',
            'gateway_device',
            'status',
            'offline_threshold_override_minutes',
            'topic_format',
            'health',
            'created_at',
        )
        read_only_fields = (
            'id', 'status', 'topic_format', 'created_at',
            'tenant_name', 'health', 'device_type_commands',
            'site_is_hierarchical',
        )

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


class CommandLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for CommandLog history entries."""

    sent_by_email = serializers.CharField(source='sent_by.email', read_only=True, default=None)

    class Meta:
        model = CommandLog
        fields = (
            'id',
            'command_name',
            'params_sent',
            'sent_at',
            'ack_received_at',
            'status',
            'sent_by_email',
            'triggered_by_rule',
        )
        read_only_fields = fields


class SendCommandSerializer(serializers.Serializer):
    """Input serializer for POST /api/v1/devices/:id/command/.

    Validates that command_name exists in the device type's commands list
    and that all required params are present with correct types.
    """

    command_name = serializers.CharField(max_length=255)
    params = serializers.DictField(child=serializers.JSONField(), default=dict)

    def validate(self, data):
        """Verify command_name exists in device type and params satisfy the schema."""
        device = self.context['device']
        command_name = data['command_name']
        params = data.get('params', {})

        commands = device.device_type.commands or []
        command_def = next((c for c in commands if c.get('name') == command_name), None)
        if command_def is None:
            raise serializers.ValidationError({
                'command_name': f'Command "{command_name}" is not defined for this device type.',
            })

        # Validate required params (those without a default value)
        for param in command_def.get('params', []):
            key = param.get('key')
            if key and 'default' not in param and key not in params:
                raise serializers.ValidationError({
                    'params': f'Required parameter "{key}" is missing.',
                })

        data['command_def'] = command_def
        return data
