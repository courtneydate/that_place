"""Billing app models — Sprint 30 (accounts) + Sprint 31 (runs) + Sprint 32 (invoices).

Sprint 30 models the customer the operator-tenant invoices: BillingAccount,
BillingAccountMeter (links to billable Streams), BillingAccountTariffAssignment
(links to PPA / retail tariffs), BillingAccountAuditLog.

Sprint 31 adds the billing engine — BillingRun (a period × scope × status
record), BillingRunSnapshot (the exact aggregates used so the run is
reproducible), BillingLineItem (per-(account, stream, TOU period) energy /
supply / credit lines with per-line GST), and BillingSchedule (recurring
runs via Celery beat).

Sprint 32 adds invoice rendering and delivery — InvoicePDFTemplate (per-tenant
HTML/CSS templates), BillingInvoice (one per account per run; atomic invoice
number; PDF stored in object storage; email delivery lifecycle). Also adds
void_reason to BillingRun and wires BillingSchedule.auto_finalize.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
     SPEC.md § Feature: Billing Runs & Invoicing
     SPEC.md § Data Model — BillingAccount / BillingAccountMeter /
         BillingAccountTariffAssignment / BillingAccountAuditLog
         BillingRun / BillingRunSnapshot / BillingLineItem / BillingSchedule
         InvoicePDFTemplate / BillingInvoice
     ROADMAP.md § Sprint 30, Sprint 31, Sprint 32
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
    applies_to_role = models.CharField(
        max_length=30,
        blank=True,
        default='',
        help_text=(
            'Sprint 33: which billing leg this tariff prices. Mirrors '
            'readings.Stream.BillingRole values — e.g. "consumption_from_solar" '
            'for the solar-allocated leg of an embedded-network tenant invoice, '
            '"consumption" for the remaining grid leg. Blank means the assignment '
            'applies regardless of leg (the single-rate PPA path).'
        ),
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
# Sprint 32 — Invoice PDF Templates
# ---------------------------------------------------------------------------


class InvoicePDFTemplate(models.Model):
    """Per-tenant HTML/CSS invoice template (Sprint 32).

    Tenant.invoice_pdf_template_id (raw int, nullable) points to one of these.
    Null means the platform default applies — the renderer falls back to the
    bundled default.html template in apps/billing/templates/invoices/.

    Sprint 35 adds the template management UI and multiple-templates-per-tenant
    support. Sprint 32 ships the model and the default template.
    """

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='invoice_pdf_templates',
        help_text='Null = platform-wide default (accessible to all tenants).',
    )
    name = models.CharField(max_length=120)
    html_content = models.TextField(
        help_text='Full HTML/CSS template rendered by WeasyPrint. May use Django template tags.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        tenant_label = self.tenant.slug if self.tenant_id else 'platform default'
        return f'{self.name} ({tenant_label})'


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
        ALLOCATE_SOLAR = 'allocate_solar', 'Allocate solar (hierarchical)'
        COMPUTE_LINE_ITEMS = 'compute_line_items', 'Compute line items'
        RECONCILE = 'reconcile', 'Reconcile (hierarchical)'
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
    void_reason = models.TextField(
        blank=True,
        default='',
        help_text='Operator-supplied reason captured when the run is voided (Sprint 32).',
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Free-text operator notes. Sprint 34: records the mandatory '
            'justification when a run over reconciliation tolerance is '
            'force-finalized.'
        ),
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


# ---------------------------------------------------------------------------
# Sprint 32 — Invoices
# ---------------------------------------------------------------------------


class BillingInvoice(models.Model):
    """One invoice per BillingAccount per BillingRun (Sprint 32).

    Lifecycle (status):
      draft     — created at finalize time, before email is sent.
      delivered — first successful email send to at least one recipient.
      void      — parent BillingRun was voided.

    Delivery tracking (delivery_status):
      pending   — not yet attempted.
      sent      — Celery task completed successfully (v1 success terminal).
      delivered — reserved for future SES bounce/receipt integration.
      failed    — SMTP error on last attempt; resend resets to pending.

    invoice_number is unique per tenant and allocated atomically via
    SELECT FOR UPDATE on Tenant.invoice_number_sequence at finalize time.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        DELIVERED = 'delivered', 'Delivered'
        VOID = 'void', 'Void'

    class DeliveryStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered (receipt confirmed)'
        FAILED = 'failed', 'Failed'

    billing_run = models.ForeignKey(
        BillingRun,
        on_delete=models.CASCADE,
        related_name='invoices',
    )
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.PROTECT,
        related_name='invoices',
    )
    invoice_number = models.CharField(
        max_length=120,
        help_text='Formatted per Tenant.invoice_number_format; unique per tenant.',
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    subtotal_cents = models.IntegerField(default=0)
    gst_cents = models.IntegerField(default=0)
    total_cents = models.IntegerField(default=0)
    pdf_object_key = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='S3/MinIO object key where the PDF is stored.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    issued_at = models.DateTimeField(
        auto_now_add=True,
        help_text='When the invoice record was created (at run finalize).',
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the first successful email send completed.',
    )
    voided_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the parent run was voided.',
    )

    class Meta:
        ordering = ['-issued_at']
        constraints = [
            models.UniqueConstraint(
                fields=['billing_run', 'billing_account'],
                name='billing_invoice_unique_per_run_account',
            ),
        ]
        indexes = [
            models.Index(fields=['billing_run', 'billing_account']),
        ]

    def __str__(self) -> str:
        return f'{self.invoice_number} ({self.billing_account.name})'


# ---------------------------------------------------------------------------
# Sprint 33 — Embedded-network solar allocation
# ---------------------------------------------------------------------------


class SolarAllocationRecord(models.Model):
    """Per-interval, per-child solar allocation for a hierarchical billing run.

    Written by the engine's `allocate_solar` step (only for sites where
    `Site.is_hierarchical`). For each interval the engine computes the solar
    pool that stayed inside the embedded network — `Σ generation − gate_export`
    (`bess_discharge` is excluded because it carries its own billing_role and
    is never tagged `generation`) — and allocates it across active child
    accounts pro-rata by each child's `grid_import` for that interval.

    Storing `pool_kwh` and `child_grid_import_kwh` alongside `allocated_kwh`
    makes every allocation reproducible from the record alone — the AER and
    tenants both scrutinise the method, so the inputs are persisted, not just
    the output. (Richer-than-SPEC-§4 shape, agreed at Sprint 33 kickoff.)

    Reproducibility contract: re-running `allocate_solar` against the same
    aggregates wipes and rewrites this run's rows to the identical end state.
    """

    class AllocationMethod(models.TextChoices):
        PRO_RATA_CONSUMPTION = 'pro_rata_consumption', 'Pro-rata by consumption'
        EQUAL_SHARE = 'equal_share', 'Equal share'
        FIXED_PROPORTION = 'fixed_proportion', 'Fixed proportion'

    billing_run = models.ForeignKey(
        BillingRun,
        on_delete=models.CASCADE,
        related_name='solar_allocations',
    )
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.PROTECT,
        related_name='solar_allocations',
        help_text='The child (embedded-network tenant) account receiving the allocation.',
    )
    interval_start = models.DateTimeField(
        help_text='UTC start of the interval this allocation covers (aligned to the run aggregate_period).',
    )
    allocated_kwh = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        help_text='Solar kWh allocated to this child for this interval.',
    )
    pool_kwh = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        help_text=(
            'The allocatable solar pool for this interval (max(0, Σ generation '
            '− gate_export), clamped to total child import). Σ allocated_kwh '
            'across children equals this value exactly.'
        ),
    )
    child_grid_import_kwh = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        help_text="This child's grid_import for the interval — the pro-rata weight.",
    )
    allocation_method = models.CharField(
        max_length=30,
        choices=AllocationMethod.choices,
        default=AllocationMethod.PRO_RATA_CONSUMPTION,
    )

    class Meta:
        ordering = ['interval_start', 'billing_account_id']
        constraints = [
            models.UniqueConstraint(
                fields=['billing_run', 'billing_account', 'interval_start'],
                name='solar_allocation_unique_per_run_account_interval',
            ),
        ]
        indexes = [
            models.Index(fields=['billing_run', 'billing_account']),
        ]

    def __str__(self) -> str:
        return (
            f'SolarAllocation(run={self.billing_run_id}, '
            f'account={self.billing_account_id}, {self.interval_start:%Y-%m-%d %H:%M}, '
            f'{self.allocated_kwh} kWh)'
        )


# ---------------------------------------------------------------------------
# Sprint 34 — Reconciliation
# ---------------------------------------------------------------------------


class ReconciliationReport(models.Model):
    """Energy-balance check for a hierarchical billing run (Sprint 34).

    Computed by the engine's ``reconcile`` step (draft-time, so the variance is
    visible before finalize) and re-checked at finalize. For the whole run
    period it balances what entered the embedded network against what was
    metered out:

        input  = gate_import + Σ generation − gate_export
        output = Σ child_grid_import + common_area
        losses = input − output            (unaccounted: line losses, unmetered)
        variance_percent = |losses| / input × 100

    ``within_tolerance`` is ``variance_percent <= Site.reconciliation_tolerance_percent``.
    When false, finalize is blocked (run set to ``review``) until the operator
    recomputes with corrected data or force-finalizes with a note.

    One report per run (rewritten on every reconcile — reproducible).

    Ref: SPEC.md § Feature: Embedded-Network Billing (Reconciliation)
         ROADMAP Sprint 34
    """

    class ReconStatus(models.TextChoices):
        OK = 'ok', 'Within tolerance'
        EXCEEDED = 'exceeded', 'Variance exceeded'

    billing_run = models.OneToOneField(
        BillingRun,
        on_delete=models.CASCADE,
        related_name='reconciliation_report',
    )
    site = models.ForeignKey(
        'devices.Site',
        on_delete=models.PROTECT,
        related_name='reconciliation_reports',
    )
    gate_import_kwh = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    generation_kwh = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    gate_export_kwh = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    child_grid_import_total_kwh = models.DecimalField(
        max_digits=18, decimal_places=6, default=0,
    )
    common_area_total_kwh = models.DecimalField(
        max_digits=18, decimal_places=6, default=0,
    )
    computed_losses_kwh = models.DecimalField(
        max_digits=18, decimal_places=6, default=0,
        help_text='input − output; the unaccounted residual (may be negative).',
    )
    variance_percent = models.DecimalField(
        max_digits=9, decimal_places=4, default=0,
        help_text='|losses| / input × 100.',
    )
    within_tolerance = models.BooleanField(default=True)
    status = models.CharField(
        max_length=12,
        choices=ReconStatus.choices,
        default=ReconStatus.OK,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return (
            f'ReconciliationReport(run={self.billing_run_id}, '
            f'variance={self.variance_percent}%, '
            f'{"ok" if self.within_tolerance else "exceeded"})'
        )
