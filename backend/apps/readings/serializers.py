"""Serializers for the readings app.

Ref: SPEC.md § Feature: Stream Discovery & Configuration
"""
from rest_framework import serializers

from .models import Stream, StreamReading


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
    """

    latest_value = serializers.SerializerMethodField()
    latest_timestamp = serializers.SerializerMethodField()

    class Meta:
        model = Stream
        fields = (
            'id',
            'key',
            'label',
            'unit',
            'data_type',
            'display_enabled',
            'latest_value',
            'latest_timestamp',
            'created_at',
        )
        read_only_fields = ('id', 'key', 'data_type', 'latest_value', 'latest_timestamp', 'created_at')

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
