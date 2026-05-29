"""Billing app models — Sprint 30.

A BillingAccount is the end customer that an operator-tenant invoices: PPA
hosts, embedded-network tenants, and internal accounts for common-area
energy. The operator's own platform Tenant is *not* the customer — they are
the invoicer.

The billing engine (Sprint 31) treats Stream + billing_role (Sprint 29) as
the source of "billable energy" and walks the BillingAccountMeter +
BillingAccountTariffAssignment graph to figure out which account pays which
tariff for which kWh.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
     SPEC.md § Data Model — BillingAccount / BillingAccountMeter /
         BillingAccountTariffAssignment / BillingAccountAuditLog
     ROADMAP.md § Sprint 30
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
