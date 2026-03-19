"""Serializers for the integrations app.

ThirdPartyAPIProvider has two serializers:
  - ThirdPartyAPIProviderAdminSerializer  — full fields (FM Admin)
  - ThirdPartyAPIProviderTenantSerializer — limited fields (Tenant Admin)

DataSource credentials are write-only (never returned in responses).

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import json

from rest_framework import serializers

from apps.devices.serializers import DeviceSerializer

from .models import DataSource, DataSourceDevice, ThirdPartyAPIProvider


class MultipartJSONField(serializers.JSONField):
    """JSONField that parses JSON strings from multipart/form-data.

    DRF's JSONField.to_internal_value does not parse string values when the
    request is multipart (binary=False). This subclass handles the extra
    json.loads step so FM Admin can POST JSON fields as strings in FormData.
    """

    def to_internal_value(self, data):
        """Parse JSON string to Python object if needed."""
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError) as exc:
                raise serializers.ValidationError('Enter valid JSON.') from exc
        return super().to_internal_value(data)


class ThirdPartyAPIProviderAdminSerializer(serializers.ModelSerializer):
    """Full provider serializer for Fieldmouse Admin.

    Includes internal fields (auth_param_schema, discovery_endpoint,
    detail_endpoint, available_streams with JSONPath expressions).
    """

    logo_url = serializers.SerializerMethodField()
    auth_param_schema = MultipartJSONField(default=list)
    discovery_endpoint = MultipartJSONField(default=dict)
    detail_endpoint = MultipartJSONField(default=dict)
    available_streams = MultipartJSONField(default=list)

    def get_logo_url(self, obj) -> str | None:
        """Return absolute URL for the logo, or None."""
        if not obj.logo:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.logo.url)
        return obj.logo.url

    class Meta:
        model = ThirdPartyAPIProvider
        fields = (
            'id',
            'name',
            'slug',
            'description',
            'logo',
            'logo_url',
            'base_url',
            'auth_type',
            'token_url',
            'refresh_url',
            'auth_param_schema',
            'discovery_endpoint',
            'detail_endpoint',
            'available_streams',
            'default_poll_interval_seconds',
            'max_requests_per_second',
            'is_active',
            'created_at',
        )
        read_only_fields = ('id', 'created_at', 'logo_url')
        extra_kwargs = {
            'logo': {'write_only': True, 'required': False},
        }


class ThirdPartyAPIProviderTenantSerializer(serializers.ModelSerializer):
    """Limited provider serializer for Tenant Admins.

    Exposes name, description, logo, auth_param_schema (to generate the
    credential form), and a sanitised available_streams list (key/label/unit/
    data_type only — no JSONPath internals).
    """

    logo_url = serializers.SerializerMethodField()
    available_streams = serializers.SerializerMethodField()

    def get_logo_url(self, obj) -> str | None:
        """Return absolute URL for the logo, or None."""
        if not obj.logo:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.logo.url)
        return obj.logo.url

    def get_available_streams(self, obj) -> list:
        """Return available streams with JSONPath expressions stripped."""
        return [
            {
                'key': s.get('key'),
                'label': s.get('label'),
                'unit': s.get('unit', ''),
                'data_type': s.get('data_type', 'numeric'),
            }
            for s in (obj.available_streams or [])
        ]

    class Meta:
        model = ThirdPartyAPIProvider
        fields = (
            'id',
            'name',
            'slug',
            'description',
            'logo_url',
            'auth_param_schema',
            'available_streams',
            'default_poll_interval_seconds',
        )
        read_only_fields = fields


class DataSourceSerializer(serializers.ModelSerializer):
    """Serializer for DataSource CRUD.

    credentials is write-only — never returned in responses.
    provider_name is included for display convenience.
    """

    provider_name = serializers.CharField(source='provider.name', read_only=True)
    provider_slug = serializers.CharField(source='provider.slug', read_only=True)
    credentials = serializers.JSONField(write_only=True, required=True)
    connected_device_count = serializers.SerializerMethodField()

    def get_connected_device_count(self, obj) -> int:
        """Return the number of active connected devices."""
        return obj.devices.filter(is_active=True).count()

    class Meta:
        model = DataSource
        fields = (
            'id',
            'provider',
            'provider_name',
            'provider_slug',
            'name',
            'credentials',
            'is_active',
            'created_at',
            'connected_device_count',
        )
        read_only_fields = ('id', 'created_at', 'provider_name', 'provider_slug', 'connected_device_count')


class DataSourceDeviceSerializer(serializers.ModelSerializer):
    """Serializer for DataSourceDevice (connected device).

    Includes the virtual device detail for display.
    """

    virtual_device_detail = DeviceSerializer(source='virtual_device', read_only=True)

    class Meta:
        model = DataSourceDevice
        fields = (
            'id',
            'external_device_id',
            'external_device_name',
            'virtual_device',
            'virtual_device_detail',
            'active_stream_keys',
            'last_polled_at',
            'last_poll_status',
            'last_poll_error',
            'consecutive_poll_failures',
            'is_active',
        )
        read_only_fields = (
            'id',
            'external_device_id',
            'external_device_name',
            'virtual_device',
            'virtual_device_detail',
            'last_polled_at',
            'last_poll_status',
            'last_poll_error',
            'consecutive_poll_failures',
        )


class ConnectDeviceSerializer(serializers.Serializer):
    """Validates a single device connection request in the wizard POST payload.

    Used in the POST /data-sources/:id/devices/ endpoint.
    Each item in the request array is validated against this serializer.
    """

    external_device_id = serializers.CharField(max_length=500)
    external_device_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    site_id = serializers.IntegerField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    active_stream_keys = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
    )
    stream_overrides = serializers.DictField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True)),
        required=False,
        default=dict,
        help_text=(
            'Optional per-stream label/unit overrides. '
            'Keys are stream keys; values are {label, unit} dicts.'
        ),
    )
