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
    aggregation_kind_default is the kind the IntervalAggregation beat task
    maintains for this stream — extra kinds can be added on demand via the
    backfill endpoint.
    """

    class DataType(models.TextChoices):
        NUMERIC = 'numeric', 'Numeric'
        BOOLEAN = 'boolean', 'Boolean'
        STRING = 'string', 'String'

    class StreamType(models.TextChoices):
        RAW = 'raw', 'Raw (ingested)'
        DERIVED = 'derived', 'Derived (computed)'

    class AggregationKind(models.TextChoices):
        SUM = 'sum', 'Sum (energy)'
        MEAN = 'mean', 'Mean (instantaneous)'
        MIN = 'min', 'Minimum'
        MAX = 'max', 'Maximum'
        LAST = 'last', 'Last (cumulative)'

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
    aggregation_kind_default = models.CharField(
        max_length=10,
        choices=AggregationKind.choices,
        default=AggregationKind.MEAN,
        help_text=(
            'The aggregation kind maintained by the IntervalAggregate beat task. '
            'Use sum for energy streams, mean for instantaneous (power/voltage/'
            'current), last for cumulative counters. Extra kinds can be computed '
            'on demand via the backfill endpoint.'
        ),
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
    quality (Sprint 28) marks how the value was produced — raw readings from
    the ingestion path are `measured`; derived streams inherit worst-input
    quality from their source readings.
    """

    class Quality(models.TextChoices):
        MEASURED = 'measured', 'Measured (raw)'
        ESTIMATED = 'estimated', 'Estimated'
        SUBSTITUTED = 'substituted', 'Substituted'
        GAP = 'gap', 'Gap (no data)'

    stream = models.ForeignKey(
        Stream,
        on_delete=models.CASCADE,
        related_name='readings',
    )
    value = models.JSONField(help_text='Stored as JSON to support numeric, boolean, and string values.')
    timestamp = models.DateTimeField(help_text='Time the reading was ingested by the server.')
    quality = models.CharField(
        max_length=20,
        choices=Quality.choices,
        default=Quality.MEASURED,
        help_text=(
            'Data quality flag (Sprint 28). Raw readings = measured. Derived '
            'streams inherit the worst-quality input. v1 does not estimate gaps.'
        ),
    )
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


class IntervalAggregate(models.Model):
    """A rolled-up aggregate of StreamReadings over a fixed period (Sprint 28).

    Periods are clock-aligned in UTC: 5-minute buckets at 00:00/00:05/…,
    30-minute at 00:00/00:30/…, hourly at the top of the hour, daily at
    00:00 UTC, monthly at the first of the month. Multiple aggregation kinds
    per stream are allowed but the beat task only maintains
    `Stream.aggregation_kind_default` by default; other kinds can be filled
    via the on-demand backfill endpoint.

    Quality breakdown carries the count of source readings by quality plus a
    single derived aggregate quality (worst-input rule). A period with zero
    raw readings is created with `count=0` and `quality=gap`.

    Ref: SPEC.md § Feature: Interval Aggregation Engine; § Feature: Data
    Quality Flags; ROADMAP Sprint 28
    """

    class Period(models.TextChoices):
        MIN_5 = '5min', '5 minutes'
        MIN_30 = '30min', '30 minutes'
        HOUR = '1h', '1 hour'
        DAY = '1d', '1 day'
        MONTH = '1mo', '1 month'

    stream = models.ForeignKey(
        Stream,
        on_delete=models.CASCADE,
        related_name='aggregates',
    )
    period = models.CharField(max_length=10, choices=Period.choices)
    period_start = models.DateTimeField(
        help_text='UTC-aligned bucket boundary (e.g. 2026-05-28T00:05:00Z for a 5-min bucket).',
    )
    aggregation_kind = models.CharField(
        max_length=10,
        choices=Stream.AggregationKind.choices,
    )
    value = models.JSONField(
        null=True,
        blank=True,
        help_text='Aggregated value. Null for gap periods (count=0).',
    )
    count = models.PositiveIntegerField(
        default=0,
        help_text='Number of source readings included in this aggregate.',
    )
    quality = models.CharField(
        max_length=20,
        choices=StreamReading.Quality.choices,
        default=StreamReading.Quality.MEASURED,
        help_text='Derived aggregate quality via worst-input rule.',
    )
    quality_breakdown = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Map of quality → count for the source readings, e.g. '
            '{"measured": 4, "estimated": 1}. Empty {} for gap periods.'
        ),
    )
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('stream', 'period', 'period_start', 'aggregation_kind')]
        ordering = ['-period_start']
        indexes = [
            models.Index(fields=['stream', '-period_start']),
        ]

    def __str__(self) -> str:
        return (
            f'IntervalAggregate(stream={self.stream_id} {self.period}@{self.period_start} '
            f'{self.aggregation_kind}={self.value}, q={self.quality})'
        )
