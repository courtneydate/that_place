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
    available, otherwise defaults to numeric. stream_type marks streams
    produced by the platform itself (derived/computed) vs. ingested raw
    from a device — derived streams have a backing `DerivedStream` config.
    """

    class DataType(models.TextChoices):
        NUMERIC = 'numeric', 'Numeric'
        BOOLEAN = 'boolean', 'Boolean'
        STRING = 'string', 'String'

    class StreamType(models.TextChoices):
        RAW = 'raw', 'Raw (ingested)'
        DERIVED = 'derived', 'Derived (computed)'

    device = models.ForeignKey(
        'devices.Device',
        on_delete=models.CASCADE,
        related_name='streams',
    )
    key = models.CharField(max_length=255, help_text='Machine-readable stream key as reported by the device.')
    label = models.CharField(max_length=255, blank=True, help_text='Human-readable label — editable by Tenant Admin.')
    unit = models.CharField(max_length=50, blank=True, help_text='Unit of measurement, e.g. "°C", "%", "L/min".')
    data_type = models.CharField(max_length=20, choices=DataType.choices, default=DataType.NUMERIC)
    stream_type = models.CharField(
        max_length=20,
        choices=StreamType.choices,
        default=StreamType.RAW,
        help_text='Raw = ingested from a device. Derived = computed from other streams.',
    )
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


class DataExport(models.Model):
    """Audit log for every on-demand CSV export.

    Written before streaming begins so the record exists even if the client
    disconnects mid-download.

    Ref: SPEC.md § Feature: Data Export (CSV) — Export history
    """

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='exports',
    )
    exported_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='exports',
    )
    stream_ids = models.JSONField(help_text='List of Stream PKs included in this export.')
    date_from = models.DateTimeField()
    date_to = models.DateTimeField()
    exported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-exported_at']

    def __str__(self) -> str:
        return f'DataExport(tenant={self.tenant_id}, streams={self.stream_ids}, at={self.exported_at})'


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


class DerivedStream(models.Model):
    """Config for a Stream whose values are computed from other Streams.

    The output `Stream` (one-to-one) has `stream_type=derived` so consumers
    see it as a regular stream. The DerivedStream record holds the formula,
    source stream(s), and params used to evaluate.

    Single-source formulas live on the source Device. Cross-device formulas
    (e.g. `consumption_from_solar`) live on a per-site virtual Device with
    role `site_composite`, auto-created on first use.

    Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
    """

    class Formula(models.TextChoices):
        DELTA = 'delta', 'Δ (current − previous)'
        SUM = 'sum', 'Σ sources at same minute'
        DIFFERENCE = 'difference', 'A − B at same minute'
        SCALE = 'scale', 'source × factor'
        WINDOW_MIN = 'window_min', 'rolling min over N minutes'
        WINDOW_MAX = 'window_max', 'rolling max over N minutes'

    stream = models.OneToOneField(
        Stream,
        on_delete=models.CASCADE,
        related_name='derived_config',
        help_text='The virtual output Stream this config writes into. Must have stream_type=derived.',
    )
    formula = models.CharField(max_length=20, choices=Formula.choices)
    source_streams = models.ManyToManyField(
        Stream,
        related_name='consumer_derived_streams',
        help_text=(
            'One or more source streams. delta/scale/window_min/window_max take 1; '
            'sum takes 1+ (cross-device allowed); difference takes exactly 2 (A, B).'
        ),
    )
    params = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Formula-specific params. '
            'delta: max_gap_minutes (optional int). '
            'scale: factor (float). '
            'window_min/window_max: window_minutes (int). '
            'difference: source_a_id / source_b_id (override ordering).'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f'DerivedStream({self.pk}) {self.formula} → Stream {self.stream_id}'


class DerivedStreamSourceIndex(models.Model):
    """Reverse index: source Stream → DerivedStream that consumes it.

    Maintained automatically on DerivedStream create/edit/delete. The dispatch
    task looks up this index when a source StreamReading is saved to find the
    derived streams that need re-evaluation.

    Analogous to RuleStreamIndex.

    Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
    """

    source_stream = models.ForeignKey(
        Stream,
        on_delete=models.CASCADE,
        related_name='derived_index_entries',
    )
    derived_stream = models.ForeignKey(
        DerivedStream,
        on_delete=models.CASCADE,
        related_name='source_index_entries',
    )

    class Meta:
        unique_together = [('source_stream', 'derived_stream')]

    def __str__(self) -> str:
        return f'Stream {self.source_stream_id} → DerivedStream {self.derived_stream_id}'
