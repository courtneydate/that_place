"""Billing app models — Sprint 30 (accounts) + Sprint 31 (runs).

Sprint 30 models the customer the operator-tenant invoices: BillingAccount,
BillingAccountMeter (links to billable Streams), BillingAccountTariffAssignment
(links to PPA / retail tariffs), BillingAccountAuditLog.

Sprint 31 adds the billing engine — BillingRun (a period × scope × status
record), BillingRunSnapshot (the exact aggregates used so the run is
reproducible), BillingLineItem (per-(account, stream, TOU period) energy /
supply / credit lines with per-line GST), and BillingSchedule (recurring
runs via Celery beat).

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
     SPEC.md § Feature: Billing Runs & Invoicing
     SPEC.md § Data Model — BillingAccount / BillingAccountMeter /
         BillingAccountTariffAssignment / BillingAccountAuditLog
         BillingRun / BillingRunSnapshot / BillingLineItem / BillingSchedule
     ROADMAP.md § Sprint 30, Sprint 31
"""
from django.contrib.postgres.fields import ArrayField
from django.db import models


class BillingAccount(models.Model):
    """The customer the operator-tenant invoices.

    `parent_account` is informational v1 grouping only — it does not change
    how billing is computed. `account_type=internal` accounts (e.g. common
    areas) are never invoiced externally; the billing engine still computes
    line items against them for apportionment.
    """

    class AccountType(models.TextChoices):
        PPA_HOST = 'ppa_host', 'PPA host (solar host customer)'
        EN_TENANT = 'en_tenant', 'Embedded-network tenant'
        INTERNAL = 'internal', 'Internal (e.g. common-area services)'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='billing_accounts',
    )
    name = models.CharField(max_length=255)
    customer_reference = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='External reference (e.g. tenancy code, lot number). Unique per tenant when set.',
    )
    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=50, blank=True, default='')
    billing_address = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Postal address as a dict: {street, suburb, state, postcode, country}. '
            'Stored flexibly so international addresses can be added without migrations.'
        ),
    )
    abn = models.CharField(
        max_length=14,
        blank=True,
        default='',
        help_text='Australian Business Number (11 digits, optionally with spaces).',
    )
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.PPA_HOST,
    )
    parent_account = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='child_accounts',
        help_text='Informational grouping only (e.g. site → tenancies).',
    )
    invoice_email_recipients = ArrayField(
        models.EmailField(),
        default=list,
        blank=True,
        help_text='Email addresses that receive the invoice PDF on finalize.',
    )
    floor_area_sqm = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Net lettable area (NLA). Used by `by_floor_area` apportionment.',
    )
    is_active = models.BooleanField(default=True)
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the account first started consuming billable energy. Drives mid-cycle pro-rata.',
    )
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Move-out date. Drives a pro-rata final invoice in Sprint 31.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'customer_reference'],
                condition=~models.Q(customer_reference=''),
                name='billing_account_unique_customer_ref_per_tenant',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.tenant.slug})'


class BillingAccountMeter(models.Model):
    """Links a billing account to a specific billable Stream over a date range.

    A single meter (Device + MeterProfile) can carry several billing-role
    Streams that bill to different accounts — e.g. a gate meter exporting to
    grid (PPA host gets paid the FiT) and importing from grid (each EN tenant
    pays the retail rate for their share). So the link lives at Stream level,
    not Device level.

    The Stream must have a non-null `billing_role` — enforced at the
    serializer level so the misconfiguration surfaces at link time, not at
    billing-run time.
    """

    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name='meter_links',
    )
    stream = models.ForeignKey(
        'readings.Stream',
        on_delete=models.PROTECT,
        related_name='billing_account_links',
    )
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text='Null means the link is open-ended (no end date set).',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f'{self.billing_account.name} ← {self.stream}'


class BillingAccountTariffAssignment(models.Model):
    """Links a billing account to a PPA / retail tariff dataset.

    Reuses the Sprint 15a ReferenceDataset row-resolution engine — the
    `dimension_filter` JSONB identifies which subset of rows applies to this
    account; `version` either pins to a specific year (e.g. "2025-26") or
    follows the latest active.

    Optional `stream` scope means "this tariff only applies when billing
    energy from a specific stream on this account". Null = applies to every
    billing-role stream on the account that doesn't have a more-specific
    assignment.
    """

    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name='tariff_assignments',
    )
    stream = models.ForeignKey(
        'readings.Stream',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='billing_tariff_assignments',
        help_text='Optional — null means all billing-role streams on this account.',
    )
    dataset = models.ForeignKey(
        'feeds.ReferenceDataset',
        on_delete=models.PROTECT,
        related_name='billing_account_assignments',
    )
    dimension_filter = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Subset of the dataset rows that apply to this account, e.g. '
            '{"plan_code": "stage1-2026"}. Empty means all rows in the dataset.'
        ),
    )
    version = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='Pinned version (e.g. "2025-26"). Null follows the latest active.',
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        scope = self.stream.key if self.stream_id else 'all streams'
        return f'{self.billing_account.name} · {self.dataset.slug} ({scope})'


class BillingAccountAuditLog(models.Model):
    """Immutable PII / change audit log for a BillingAccount.

    Written automatically by the billing app's signal handlers on every
    create / update / deactivate. The table is append-only — no UPDATE or
    DELETE endpoint, no model save() after creation. Same pattern as
    RuleAuditLog (Sprint 14).

    `changed_fields` JSONB carries a `{field: {before, after}}` diff for
    updates; for `created` it's a `{field: {after}}` snapshot of initial
    values; for `deactivated` it captures the deactivated_at change only.
    """

    class Action(models.TextChoices):
        CREATED = 'created', 'Created'
        UPDATED = 'updated', 'Updated'
        DEACTIVATED = 'deactivated', 'Deactivated'

    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name='audit_log_entries',
    )
    actor_user = models.ForeignKey(
        'accounts.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='billing_account_audit_entries',
        help_text='User who triggered the action. Null only for system-initiated changes.',
    )
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )
    changed_fields = models.JSONField(
        default=dict,
        help_text='Per-field before/after diff. See model docstring.',
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at']

    def __str__(self):
        return f'{self.billing_account.name} · {self.action} @ {self.occurred_at:%Y-%m-%d %H:%M}'

    def save(self, *args, **kwargs):
        """Block in-place updates — audit log is append-only."""
        if self.pk is not None:
            raise RuntimeError('BillingAccountAuditLog is immutable; updates are not allowed.')
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Sprint 31 — Billing Run Engine
# ---------------------------------------------------------------------------


class BillingRun(models.Model):
    """A billing period × scope × status record (Sprint 31).

    Created with status=`queued`. The Celery task chain transitions it through
    the four engine steps. On the happy path it ends at `draft` (Sprint 32
    introduces `finalize` and `void`). On any step failure, status becomes
    `failed` and `failed_step` records which step threw — `retry` resumes from
    there; `recompute` (draft only) restarts from `resolve_scope`.

    `aggregate_period` is the IntervalAggregate period the engine reads
    (5m/30m/1h). Operators choose tighter granularity when TOU boundaries
    cross hour boundaries.

    `billing_account_ids` is an explicit filter; an empty array means "every
    active billing account on this site within the run period". Ref SPEC §3
    Billing Runs & Invoicing, ROADMAP Sprint 31 design decisions.
    """

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        COMPUTING = 'computing', 'Computing'
        REVIEW = 'review', 'Review'
        DRAFT = 'draft', 'Draft'
        FINALIZED = 'finalized', 'Finalized'
        VOIDED = 'voided', 'Voided'
        FAILED = 'failed', 'Failed'

    class AggregatePeriod(models.TextChoices):
        FIVE_MIN = '5min', '5 minutes'
        THIRTY_MIN = '30min', '30 minutes'
        ONE_HOUR = '1h', '1 hour'

    class Step(models.TextChoices):
        RESOLVE_SCOPE = 'resolve_scope', 'Resolve scope'
        SNAPSHOT = 'snapshot', 'Snapshot'
        COMPUTE_LINE_ITEMS = 'compute_line_items', 'Compute line items'
        MARK_DRAFT = 'mark_draft', 'Mark draft'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='billing_runs',
    )
    site = models.ForeignKey(
        'devices.Site',
        on_delete=models.PROTECT,
        related_name='billing_runs',
        help_text='Required in v1. Cross-site / portfolio runs deferred (v1.1).',
    )
    billing_account_ids = ArrayField(
        models.IntegerField(),
        default=list,
        blank=True,
        help_text=(
            'Explicit account filter within the site. Empty means "every '
            'active billing account on this site within the run period".'
        ),
    )
    period_start = models.DateTimeField(
        help_text='Run window start, UTC (inclusive).',
    )
    period_end = models.DateTimeField(
        help_text='Run window end, UTC (exclusive).',
    )
    timezone_snapshot = models.CharField(
        max_length=64,
        help_text='Snapshot of tenant.timezone at run create time (IANA).',
    )
    aggregate_period = models.CharField(
        max_length=8,
        choices=AggregatePeriod.choices,
        default=AggregatePeriod.THIRTY_MIN,
        help_text='IntervalAggregate period the engine walks. 30m by default.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    failed_step = models.CharField(
        max_length=30,
        choices=Step.choices,
        null=True,
        blank=True,
        help_text='Which step threw on the last attempt. Used by retry.',
    )
    failure_detail = models.TextField(
        blank=True,
        default='',
        help_text='Exception summary populated on failure.',
    )
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='billing_runs_created',
    )
    finalized_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='billing_runs_finalized',
        help_text='Set when Sprint 32 finalize runs.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['site', 'period_start', 'period_end']),
        ]

    def __str__(self):
        return (
            f'BillingRun(site={self.site_id}, '
            f'{self.period_start:%Y-%m-%d}→{self.period_end:%Y-%m-%d}, {self.status})'
        )


class BillingRunSnapshot(models.Model):
    """Per-stream snapshot of which aggregates the run consumed (Sprint 31).

    Reproducibility contract: re-running the engine against the same set of
    snapshot rows produces the same line items. The Sprint 31 engine reads
    IntervalAggregates only (raw-StreamReading FKs deferred until a tariff
    shape demands them — e.g. cumulative counters in v1.1).
    """

    billing_run = models.ForeignKey(
        BillingRun,
        on_delete=models.CASCADE,
        related_name='snapshots',
    )
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.PROTECT,
        related_name='billing_run_snapshots',
    )
    stream = models.ForeignKey(
        'readings.Stream',
        on_delete=models.PROTECT,
        related_name='billing_run_snapshots',
    )
    interval_aggregate_ids = ArrayField(
        models.BigIntegerField(),
        default=list,
        help_text='IntervalAggregate IDs that contributed to this stream’s total.',
    )
    computed_kwh = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        default=0,
        help_text='Sum of measured kWh across the snapshot intervals.',
    )
    quality_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text='Aggregate counts of source quality flags. Shape: {measured, estimated, substituted, gap}.',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['billing_run', 'billing_account', 'stream'],
                name='billing_snapshot_unique_per_run_account_stream',
            ),
        ]
        indexes = [
            models.Index(fields=['billing_run', 'billing_account']),
        ]

    def __str__(self):
        return f'Snapshot(run={self.billing_run_id}, stream={self.stream_id}, kwh={self.computed_kwh})'


class BillingLineItem(models.Model):
    """One row of an invoice (Sprint 31).

    Sprint 31 emits three line_kinds automatically: `energy` (kWh × rate per
    TOU period), `supply` (daily fixed charge × billable days), and `credit`
    (negative-sign amount on a `billing_role=grid_export` stream when the
    operator has assigned a feed-in tariff). `discount` / `adjustment` are
    reserved for operator-added lines in a later sprint; `common_area_share`
    is B3 territory.

    GST is computed per-line as `amount_cents * tenant.gst_rate` and stored on
    the row. Invoice subtotals/totals are simple sums.
    """

    class LineKind(models.TextChoices):
        ENERGY = 'energy', 'Energy'
        SUPPLY = 'supply', 'Supply charge'
        DISCOUNT = 'discount', 'Discount'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        CREDIT = 'credit', 'Credit (feed-in)'
        COMMON_AREA_SHARE = 'common_area_share', 'Common-area share (B3)'

    billing_run = models.ForeignKey(
        BillingRun,
        on_delete=models.CASCADE,
        related_name='line_items',
    )
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.PROTECT,
        related_name='billing_line_items',
    )
    stream = models.ForeignKey(
        'readings.Stream',
        on_delete=models.PROTECT,
        related_name='billing_line_items',
        null=True,
        blank=True,
        help_text='Null for supply / adjustment lines not tied to a single stream.',
    )
    line_kind = models.CharField(
        max_length=30,
        choices=LineKind.choices,
    )
    period_name = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text='TOU period name from the tariff (peak/off_peak/flat). Blank for non-energy lines.',
    )
    kwh = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Null on non-energy lines (supply, adjustment).',
    )
    rate_cents_per_kwh = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Energy rate applied. Null on non-energy lines.',
    )
    amount_cents = models.IntegerField(
        help_text='Line amount in cents (signed; negative for credits).',
    )
    gst_cents = models.IntegerField(
        default=0,
        help_text='GST on this line in cents. amount_cents * tenant.gst_rate, rounded.',
    )
    quality_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text='Roll-up of source IntervalAggregate quality_breakdown for this line.',
    )
    source_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='Set on common_area_share lines (B3) to link back to the internal account.',
    )

    class Meta:
        ordering = ['billing_account_id', 'line_kind', 'period_name']
        indexes = [
            models.Index(fields=['billing_run', 'billing_account']),
        ]

    def __str__(self):
        return (
            f'LineItem(run={self.billing_run_id}, account={self.billing_account_id}, '
            f'{self.line_kind} {self.period_name} ${self.amount_cents / 100:.2f})'
        )


class BillingSchedule(models.Model):
    """Recurring billing run cadence (Sprint 31).

    The Celery beat task picks up active schedules whose `next_run_at` has
    passed and dispatches a BillingRun for the previous full period (offset
    by `period_offset_days` so end-of-month data can settle). After a
    successful dispatch, `next_run_at` advances to the next cadence boundary.

    `auto_finalize` is informational in Sprint 31; Sprint 32 wires it into
    the finalize endpoint.
    """

    class Cadence(models.TextChoices):
        MONTHLY_CALENDAR = 'monthly_calendar', 'Monthly (calendar)'
        MONTHLY_ANCHOR = 'monthly_anchor', 'Monthly (anchor day)'
        QUARTERLY = 'quarterly', 'Quarterly'
        CUSTOM_CRON = 'custom_cron', 'Custom cron'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='billing_schedules',
    )
    name = models.CharField(max_length=255)
    site = models.ForeignKey(
        'devices.Site',
        on_delete=models.PROTECT,
        related_name='billing_schedules',
    )
    billing_account_ids = ArrayField(
        models.IntegerField(),
        default=list,
        blank=True,
        help_text='Explicit account filter. Empty means every active account on the site.',
    )
    aggregate_period = models.CharField(
        max_length=8,
        choices=BillingRun.AggregatePeriod.choices,
        default=BillingRun.AggregatePeriod.THIRTY_MIN,
    )
    cadence = models.CharField(max_length=30, choices=Cadence.choices)
    anchor_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Day of month for monthly_anchor cadence (1–31).',
    )
    period_offset_days = models.SmallIntegerField(
        default=0,
        help_text=(
            'Days to wait after the period ends before dispatching, '
            'so last-day data has time to land.'
        ),
    )
    custom_cron = models.CharField(
        max_length=120,
        blank=True,
        default='',
        help_text='Standard 5-field cron string when cadence=custom_cron.',
    )
    auto_finalize = models.BooleanField(
        default=False,
        help_text='Sprint 32 hook: finalize the run automatically when computed.',
    )
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Next time the beat dispatcher will fire this schedule.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.cadence})'
