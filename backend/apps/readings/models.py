"""Readings models: Stream, StreamReading, RuleStreamIndex.

Stream records are auto-created on first data receipt from a device.
StreamReadings are retained forever — no deletion policy.

Ref: SPEC.md § Data Model, § Feature: Stream Discovery & Configuration
"""
import logging

from django.db import models

logger = logging.getLogger(__name__)


class Stream(models.Model):
    """A single data channel reported by a device.

    Created automatically when a device reports an unknown stream key for
    the first time (auto-discovery). The label, unit, and display_enabled
    fields are editable by Tenant Admins.

    data_type is inferred from the DeviceType stream definitions when
    available, otherwise defaults to numeric.
    """

    class DataType(models.TextChoices):
        NUMERIC = 'numeric', 'Numeric'
        BOOLEAN = 'boolean', 'Boolean'
        STRING = 'string', 'String'

    device = models.ForeignKey(
        'devices.Device',
        on_delete=models.CASCADE,
        related_name='streams',
    )
    key = models.CharField(max_length=255, help_text='Machine-readable stream key as reported by the device.')
    label = models.CharField(max_length=255, blank=True, help_text='Human-readable label — editable by Tenant Admin.')
    unit = models.CharField(max_length=50, blank=True, help_text='Unit of measurement, e.g. "°C", "%", "L/min".')
    data_type = models.CharField(max_length=20, choices=DataType.choices, default=DataType.NUMERIC)
    display_enabled = models.BooleanField(
        default=True,
        help_text='Controls dashboard visibility. Data is always stored regardless of this flag.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('device', 'key')]
        ordering = ['key']

    def __str__(self):
        return f'{self.device.serial_number} / {self.key}'


class StreamReading(models.Model):
    """A single timestamped value for a stream.

    All readings are retained forever. timestamp is the ingestion time
    (server-side); future firmware versions may supply a device-side timestamp.
    """

    stream = models.ForeignKey(
        Stream,
        on_delete=models.CASCADE,
        related_name='readings',
    )
    value = models.JSONField(help_text='Stored as JSON to support numeric, boolean, and string values.')
    timestamp = models.DateTimeField(help_text='Time the reading was ingested by the server.')
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['stream', '-timestamp']),
        ]

    def __str__(self):
        return f'{self.stream} @ {self.timestamp}: {self.value}'


class RuleStreamIndex(models.Model):
    """Index linking a Stream to a Rule for efficient rule lookup during ingestion.

    Maintained automatically whenever a rule is created, edited, or deleted.
    On each new StreamReading, only the rules indexed against that stream are
    evaluated — not all rules in the tenant.

    Ref: SPEC.md § Data Model — RuleStreamIndex
    """

    stream = models.ForeignKey(
        Stream,
        on_delete=models.CASCADE,
        related_name='rule_index_entries',
    )
    rule = models.ForeignKey(
        'rules.Rule',
        on_delete=models.CASCADE,
        related_name='stream_index_entries',
    )

    class Meta:
        unique_together = [('stream', 'rule')]

    def __str__(self) -> str:
        return f'Stream {self.stream_id} → Rule {self.rule_id}'
