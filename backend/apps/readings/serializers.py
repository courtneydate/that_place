"""Serializers for the readings app.

Ref: SPEC.md § Feature: Stream Discovery & Configuration, § Feature: Data Export (CSV)
"""
from rest_framework import serializers

from .models import DataExport, DerivedStream, Stream, StreamReading


class StreamReadingSerializer(serializers.ModelSerializer):
    """Read-only serializer for StreamReading — used by the readings list endpoint."""

    class Meta:
        model = StreamReading
        fields = ('id', 'value', 'timestamp', 'ingested_at')
        read_only_fields = ('id', 'value', 'timestamp', 'ingested_at')


class StreamSerializer(serializers.ModelSerializer):
    """Serializer for Stream list and detail.

    `label`, `unit`, and `display_enabled` are writable by Tenant Admins.
    All other fields are read-only.
    `latest_value` and `latest_timestamp` are populated from annotations
    set by the view queryset (efficient) or fall back to a direct DB query.
    `device` exposes the parent device PK so the frontend can resolve
    device context (e.g. for widget builder edit-mode pre-population).
    """

    latest_value = serializers.SerializerMethodField()
    latest_timestamp = serializers.SerializerMethodField()
    device = serializers.IntegerField(source='device_id', read_only=True)

    class Meta:
        model = Stream
        fields = (
            'id',
            'device',
            'key',
            'label',
            'unit',
            'data_type',
            'stream_type',
            'display_enabled',
            'latest_value',
            'latest_timestamp',
            'created_at',
        )
        read_only_fields = (
            'id', 'device', 'key', 'data_type', 'stream_type',
            'latest_value', 'latest_timestamp', 'created_at',
        )

    def get_latest_value(self, obj):
        """Return the most recent reading value, or None if no readings exist."""
        if hasattr(obj, 'annotated_latest_value'):
            return obj.annotated_latest_value
        reading = obj.readings.first()
        return reading.value if reading else None

    def get_latest_timestamp(self, obj):
        """Return the timestamp of the most recent reading, or None."""
        if hasattr(obj, 'annotated_latest_ts'):
            return obj.annotated_latest_ts
        reading = obj.readings.first()
        return reading.timestamp if reading else None


class ExportRequestSerializer(serializers.Serializer):
    """Validates the POST body for a CSV export request.

    Ref: SPEC.md § Feature: Data Export (CSV)
    """

    stream_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        help_text='One or more Stream PKs to include in the export.',
    )
    date_from = serializers.DateTimeField(help_text='Start of export window (exclusive).')
    date_to = serializers.DateTimeField(help_text='End of export window (inclusive).')

    def validate(self, data):
        """Ensure date_from is before date_to."""
        if data['date_from'] >= data['date_to']:
            raise serializers.ValidationError('date_from must be earlier than date_to.')
        return data


class DataExportSerializer(serializers.ModelSerializer):
    """Read-only serializer for export history list (Admin only).

    Ref: SPEC.md § Feature: Data Export (CSV) — Export history
    """

    exported_by_email = serializers.SerializerMethodField()

    class Meta:
        model = DataExport
        fields = ('id', 'exported_by', 'exported_by_email', 'stream_ids', 'date_from', 'date_to', 'exported_at')
        read_only_fields = fields

    def get_exported_by_email(self, obj) -> str | None:
        """Return the email of the exporting user, or None if deleted."""
        return obj.exported_by.email if obj.exported_by else None


# ---------------------------------------------------------------------------
# Derived streams (Sprint 27)
# ---------------------------------------------------------------------------

SINGLE_SOURCE_FORMULAS = {'delta', 'scale', 'window_min', 'window_max'}
DIFFERENCE_FORMULA = 'difference'
SUM_FORMULA = 'sum'


class DerivedStreamSerializer(serializers.ModelSerializer):
    """Create / read / update serializer for DerivedStream.

    On create the caller supplies:
      - key, label, unit (for the output Stream)
      - formula
      - source_stream_ids (one or more existing Stream PKs)
      - params (formula-specific)

    The serializer creates the backing output Stream (with `stream_type=derived`)
    and, for cross-device source sets, the per-site Site Composite Device host.
    """

    source_stream_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        write_only=True,
    )
    source_streams = serializers.SerializerMethodField()
    stream_id = serializers.IntegerField(read_only=True)
    stream_key = serializers.CharField(source='stream.key', read_only=True)
    stream_label = serializers.CharField(source='stream.label', read_only=True)
    stream_unit = serializers.CharField(source='stream.unit', read_only=True)
    stream_device_id = serializers.IntegerField(source='stream.device_id', read_only=True)

    # Output Stream creation inputs — write-only.
    key = serializers.CharField(write_only=True, max_length=255)
    label = serializers.CharField(write_only=True, max_length=255, required=False, allow_blank=True, default='')
    unit = serializers.CharField(write_only=True, max_length=50, required=False, allow_blank=True, default='')

    class Meta:
        model = DerivedStream
        fields = (
            'id',
            'formula',
            'params',
            'is_active',
            'created_at',
            'updated_at',
            # Output Stream — read-only fields exposed for the UI
            'stream_id', 'stream_key', 'stream_label', 'stream_unit', 'stream_device_id',
            # Output Stream creation — write-only
            'key', 'label', 'unit',
            # Sources
            'source_stream_ids', 'source_streams',
        )
        read_only_fields = (
            'id', 'created_at', 'updated_at',
            'stream_id', 'stream_key', 'stream_label', 'stream_unit', 'stream_device_id',
            'source_streams',
        )

    def get_source_streams(self, obj):
        """Return a list of {id, key, device_id} for the source streams."""
        return [
            {'id': s.pk, 'key': s.key, 'device_id': s.device_id}
            for s in obj.source_streams.all()
        ]

    def validate(self, data):
        formula = data.get('formula') or getattr(self.instance, 'formula', None)
        source_ids = data.get('source_stream_ids')
        if source_ids is None and self.instance is not None:
            source_ids = list(self.instance.source_streams.values_list('pk', flat=True))

        if formula in SINGLE_SOURCE_FORMULAS and len(source_ids) != 1:
            raise serializers.ValidationError(
                f'Formula {formula!r} requires exactly one source stream; got {len(source_ids)}.'
            )
        if formula == DIFFERENCE_FORMULA and len(source_ids) != 2:
            raise serializers.ValidationError(
                f'Formula {formula!r} requires exactly two source streams; got {len(source_ids)}.'
            )
        if formula == SUM_FORMULA and len(source_ids) < 1:
            raise serializers.ValidationError(
                f'Formula {formula!r} requires at least one source stream.'
            )

        # Validate tenant scope: every source stream must belong to the requesting user's tenant.
        request = self.context.get('request')
        tenant_user = getattr(getattr(request, 'user', None), 'tenantuser', None)
        if tenant_user is None:
            raise serializers.ValidationError('Tenant context required.')
        source_streams = list(
            Stream.objects
            .filter(pk__in=source_ids, device__tenant=tenant_user.tenant)
        )
        if len(source_streams) != len(source_ids):
            raise serializers.ValidationError('One or more source streams do not exist in this tenant.')

        # Formula-specific param checks
        params = data.get('params') or {}
        if formula == 'scale' and 'factor' not in params:
            raise serializers.ValidationError("scale formula requires params.factor (number).")
        if formula in ('window_min', 'window_max') and 'window_minutes' not in params:
            raise serializers.ValidationError(
                f'{formula} formula requires params.window_minutes (positive int).'
            )

        data['_source_streams'] = source_streams
        return data

    def create(self, validated_data):
        from django.db import transaction
        from apps.devices.models import Device
        from .derived_dispatch import (
            get_or_create_site_composite_device,
            sources_span_multiple_devices,
        )

        source_streams = validated_data.pop('_source_streams')
        validated_data.pop('source_stream_ids', None)
        key = validated_data.pop('key')
        label = validated_data.pop('label', '') or key
        unit = validated_data.pop('unit', '')

        # Host device: own device for single-source / same-device sets; site
        # composite for cross-device sets.
        if sources_span_multiple_devices(source_streams):
            site = source_streams[0].device.site
            host_device: Device = get_or_create_site_composite_device(site)
        else:
            host_device = source_streams[0].device

        with transaction.atomic():
            output_stream = Stream.objects.create(
                device=host_device,
                key=key,
                label=label,
                unit=unit,
                data_type=Stream.DataType.NUMERIC,
                stream_type=Stream.StreamType.DERIVED,
            )
            derived = DerivedStream.objects.create(
                stream=output_stream,
                formula=validated_data['formula'],
                params=validated_data.get('params') or {},
                is_active=validated_data.get('is_active', True),
            )
            derived.source_streams.set(source_streams)
        return derived

    def update(self, instance, validated_data):
        from django.db import transaction
        source_streams = validated_data.pop('_source_streams', None)
        validated_data.pop('source_stream_ids', None)

        # Output stream label/unit are editable; key is not.
        stream_label = validated_data.pop('label', None)
        stream_unit = validated_data.pop('unit', None)
        validated_data.pop('key', None)

        with transaction.atomic():
            for field in ('formula', 'params', 'is_active'):
                if field in validated_data:
                    setattr(instance, field, validated_data[field])
            instance.save()
            if source_streams is not None:
                instance.source_streams.set(source_streams)
            if stream_label is not None or stream_unit is not None:
                stream = instance.stream
                if stream_label is not None:
                    stream.label = stream_label
                if stream_unit is not None:
                    stream.unit = stream_unit
                stream.save(update_fields=['label', 'unit'])
        return instance


class DerivedStreamBackfillSerializer(serializers.Serializer):
    """Validates the POST body for a derived-stream backfill request."""

    date_from = serializers.DateTimeField()
    date_to = serializers.DateTimeField()

    def validate(self, data):
        if data['date_from'] >= data['date_to']:
            raise serializers.ValidationError('date_from must be earlier than date_to.')
        return data
