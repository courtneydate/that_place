"""Serializers for the billing app — Sprint 30.

Three writable serializers (BillingAccount + BillingAccountMeter +
BillingAccountTariffAssignment) plus the read-only audit log + bulk import
serializer for CSV upsert.

All write paths inject `tenant` from `request.user.tenantuser.tenant` —
clients cannot supply a tenant.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
"""
from __future__ import annotations

import csv
import io
import re

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.feeds.models import ReferenceDataset

from .models import (
    BillingAccount,
    BillingAccountAuditLog,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
    BillingInvoice,
    BillingLineItem,
    BillingRun,
    BillingRunSnapshot,
    BillingSchedule,
)

# CSV import limits — mirror feeds / metering for consistency
# (security_risks.md § SR-04).
CSV_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
CSV_MAX_ROWS = 50_000

_ABN_SHAPE = re.compile(r'^\d{11}$')


def _validate_abn(value: str) -> str:
    """Strip whitespace and reject anything that isn't 11 digits."""
    if not value:
        return ''
    cleaned = re.sub(r'\s+', '', value)
    if not _ABN_SHAPE.match(cleaned):
        raise serializers.ValidationError('ABN must be exactly 11 digits.')
    return cleaned


class BillingAccountSerializer(serializers.ModelSerializer):
    """CRUD serializer for BillingAccount."""

    parent_account_name = serializers.CharField(
        source='parent_account.name', read_only=True, allow_null=True,
    )

    class Meta:
        model = BillingAccount
        fields = (
            'id',
            'name',
            'customer_reference',
            'contact_email',
            'contact_phone',
            'billing_address',
            'abn',
            'account_type',
            'parent_account',
            'parent_account_name',
            'invoice_email_recipients',
            'floor_area_sqm',
            'is_active',
            'activated_at',
            'deactivated_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'parent_account_name', 'created_at', 'updated_at')

    def validate_abn(self, value):
        return _validate_abn(value)

    def validate_parent_account(self, parent):
        """Parent must belong to the same tenant and not be self."""
        if parent is None:
            return parent
        request = self.context.get('request')
        if request and not request.user.is_that_place_admin:
            tenant = request.user.tenantuser.tenant
            if parent.tenant_id != tenant.id:
                raise serializers.ValidationError(
                    'Parent account does not belong to your tenant.'
                )
        if self.instance is not None and parent.id == self.instance.id:
            raise serializers.ValidationError('An account cannot be its own parent.')
        return parent

    def validate_billing_address(self, value):
        """Allow blank or any dict; reject scalar values to keep the shape stable."""
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'billing_address must be an object (e.g. {"street": "...", "suburb": "..."}).'
            )
        return value

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError({
                'customer_reference': (
                    'This customer reference is already used in your tenant.'
                ),
            })

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError({
                'customer_reference': (
                    'This customer reference is already used in your tenant.'
                ),
            })


class BillingAccountMeterSerializer(serializers.ModelSerializer):
    """Nested serializer — stream link for a billing account.

    Enforces the Sprint 29 / Sprint 30 invariant that the linked Stream must
    have `billing_role` set; otherwise the billing engine has no idea how to
    treat its kWh.
    """

    stream_label = serializers.CharField(source='stream.label', read_only=True)
    stream_billing_role = serializers.CharField(source='stream.billing_role', read_only=True)
    device_name = serializers.CharField(source='stream.device.name', read_only=True)
    device_serial = serializers.CharField(source='stream.device.serial_number', read_only=True)

    class Meta:
        model = BillingAccountMeter
        fields = (
            'id', 'stream', 'stream_label', 'stream_billing_role',
            'device_name', 'device_serial',
            'effective_from', 'effective_to', 'created_at',
        )
        read_only_fields = (
            'id', 'stream_label', 'stream_billing_role',
            'device_name', 'device_serial', 'created_at',
        )

    def validate_stream(self, stream):
        """Stream must belong to the billing account's tenant and have a billing_role."""
        billing_account = self.context.get('billing_account')
        if billing_account is None and self.instance is not None:
            billing_account = self.instance.billing_account
        if billing_account is None:
            raise serializers.ValidationError('Billing account context is required.')
        if stream.device.tenant_id != billing_account.tenant_id:
            raise serializers.ValidationError(
                'Stream does not belong to this billing account\'s tenant.'
            )
        if not stream.billing_role:
            raise serializers.ValidationError(
                'Stream has no billing_role set. Tag the stream first '
                '(Streams tab → Billing role) before linking it to a billing account.'
            )
        return stream

    def validate(self, attrs):
        from_date = attrs.get('effective_from') or (
            self.instance.effective_from if self.instance else None
        )
        to_date = attrs.get('effective_to', None)
        if 'effective_to' not in attrs and self.instance is not None:
            to_date = self.instance.effective_to
        if from_date and to_date and to_date < from_date:
            raise serializers.ValidationError({
                'effective_to': 'effective_to must not be earlier than effective_from.',
            })
        return attrs


class BillingAccountTariffAssignmentSerializer(serializers.ModelSerializer):
    """Nested serializer — tariff dataset assignment for a billing account."""

    dataset_name = serializers.CharField(source='dataset.name', read_only=True)
    dataset_slug = serializers.CharField(source='dataset.slug', read_only=True)
    stream_label = serializers.CharField(
        source='stream.label', read_only=True, allow_null=True,
    )

    class Meta:
        model = BillingAccountTariffAssignment
        fields = (
            'id', 'dataset', 'dataset_name', 'dataset_slug',
            'stream', 'stream_label',
            'dimension_filter', 'version',
            'effective_from', 'effective_to', 'created_at',
        )
        read_only_fields = (
            'id', 'dataset_name', 'dataset_slug', 'stream_label', 'created_at',
        )

    def validate_dataset(self, dataset: ReferenceDataset):
        """Only scope=tenant datasets can be assigned to a billing account.

        scope=system datasets (network tariffs, CO2 factors) are platform
        reference data — they're for the analytics engine, not customer
        billing. Pinning a system dataset to a billing account would conflate
        the two and risk leaking platform updates into invoices mid-period.
        """
        if dataset.scope != ReferenceDataset.Scope.TENANT:
            raise serializers.ValidationError(
                'Only scope=tenant ReferenceDatasets can be assigned as tariffs.'
            )
        return dataset

    def validate_stream(self, stream):
        """Optional stream scope must belong to the same tenant if set."""
        if stream is None:
            return stream
        billing_account = self.context.get('billing_account')
        if billing_account is None and self.instance is not None:
            billing_account = self.instance.billing_account
        if billing_account and stream.device.tenant_id != billing_account.tenant_id:
            raise serializers.ValidationError(
                'Stream does not belong to this billing account\'s tenant.'
            )
        return stream

    def validate(self, attrs):
        from_date = attrs.get('effective_from') or (
            self.instance.effective_from if self.instance else None
        )
        to_date = attrs.get('effective_to', None)
        if 'effective_to' not in attrs and self.instance is not None:
            to_date = self.instance.effective_to
        if from_date and to_date and to_date < from_date:
            raise serializers.ValidationError({
                'effective_to': 'effective_to must not be earlier than effective_from.',
            })
        return attrs


class BillingAccountAuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for the audit log."""

    actor_email = serializers.CharField(
        source='actor_user.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = BillingAccountAuditLog
        fields = ('id', 'action', 'changed_fields', 'actor_email', 'occurred_at')
        read_only_fields = fields


class BulkBillingAccountImportSerializer(serializers.Serializer):
    """CSV upsert serializer for BillingAccount (Sprint 30).

    Match key is `customer_reference`. Rows without one are *created*, never
    updated — bulk import isn't an identity-creation tool. To update an
    existing customer-reference-less account, edit it in the UI.

    Columns (header row required):
      name                       (required)
      customer_reference         (recommended — upsert key)
      account_type               (required — ppa_host / en_tenant / internal)
      contact_email              (optional)
      contact_phone              (optional)
      abn                        (optional)
      address_street             (optional, mapped into billing_address)
      address_suburb             (optional)
      address_state              (optional)
      address_postcode           (optional)
      address_country            (optional)
      invoice_email_recipients   (optional — comma-separated emails)
      floor_area_sqm             (optional)
      activated_at               (optional — ISO 8601)
      deactivated_at             (optional — ISO 8601)
      parent_customer_reference  (optional — resolved to parent_account)

    Returns: {imported: N, errors: [{row: N, error: "..."}]}.
    """

    file = serializers.FileField()

    def validate_file(self, value):
        if not value.name.endswith('.csv'):
            raise serializers.ValidationError('Only CSV files are accepted.')
        if value.size > CSV_MAX_UPLOAD_BYTES:
            limit_mb = CSV_MAX_UPLOAD_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                f'File too large. Maximum upload size is {limit_mb} MB.'
            )
        return value

    def import_rows(self, tenant) -> dict:
        file = self.validated_data['file']
        try:
            text = file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            return {'imported': 0, 'errors': [{'row': 0, 'error': 'File is not valid UTF-8.'}]}

        reader = csv.DictReader(io.StringIO(text))
        all_rows = list(reader)
        if len(all_rows) > CSV_MAX_ROWS:
            return {
                'imported': 0,
                'errors': [{
                    'row': 0,
                    'error': (
                        f'File contains {len(all_rows):,} rows; '
                        f'maximum allowed is {CSV_MAX_ROWS:,}.'
                    ),
                }],
            }

        valid_types = {choice for choice, _ in BillingAccount.AccountType.choices}
        imported = 0
        errors: list[dict] = []

        for row_num, raw in enumerate(all_rows, start=2):
            try:
                name = (raw.get('name') or '').strip()
                if not name:
                    raise ValueError('name is required')
                account_type = (raw.get('account_type') or '').strip()
                if account_type not in valid_types:
                    raise ValueError(
                        f'account_type "{account_type}" is not a valid choice'
                    )

                cust_ref = (raw.get('customer_reference') or '').strip()
                abn_raw = (raw.get('abn') or '').strip()
                if abn_raw:
                    try:
                        abn_raw = _validate_abn(abn_raw)
                    except serializers.ValidationError as exc:
                        raise ValueError(exc.detail[0])

                address = {
                    k: (raw.get(f'address_{k}') or '').strip()
                    for k in ('street', 'suburb', 'state', 'postcode', 'country')
                }
                address = {k: v for k, v in address.items() if v}

                recipients_raw = (raw.get('invoice_email_recipients') or '').strip()
                recipients = [
                    e.strip() for e in recipients_raw.split(',') if e.strip()
                ]

                floor_area_raw = (raw.get('floor_area_sqm') or '').strip()
                floor_area = float(floor_area_raw) if floor_area_raw else None

                parent_cust_ref = (raw.get('parent_customer_reference') or '').strip()
                parent_account = None
                if parent_cust_ref:
                    parent_account = BillingAccount.objects.filter(
                        tenant=tenant, customer_reference=parent_cust_ref,
                    ).first()
                    if parent_account is None:
                        raise ValueError(
                            f'parent_customer_reference "{parent_cust_ref}" '
                            'not found in this tenant'
                        )

                payload = {
                    'name': name,
                    'account_type': account_type,
                    'customer_reference': cust_ref,
                    'contact_email': (raw.get('contact_email') or '').strip(),
                    'contact_phone': (raw.get('contact_phone') or '').strip(),
                    'abn': abn_raw,
                    'billing_address': address,
                    'invoice_email_recipients': recipients,
                    'floor_area_sqm': floor_area,
                    'activated_at': (raw.get('activated_at') or '').strip() or None,
                    'deactivated_at': (raw.get('deactivated_at') or '').strip() or None,
                    'parent_account': parent_account.id if parent_account else None,
                }

                # Upsert lookup: if customer_reference is set and matches an
                # existing row, update it; otherwise create a new account.
                instance = None
                if cust_ref:
                    instance = BillingAccount.objects.filter(
                        tenant=tenant, customer_reference=cust_ref,
                    ).first()

                with transaction.atomic():
                    serializer = BillingAccountSerializer(
                        instance=instance,
                        data=payload,
                        partial=instance is not None,
                    )
                    serializer.is_valid(raise_exception=True)
                    serializer.save(tenant=tenant)
                imported += 1

            except serializers.ValidationError as exc:
                errors.append({'row': row_num, 'error': _flatten_error(exc.detail)})
            except Exception as exc:
                errors.append({'row': row_num, 'error': str(exc)})

        return {'imported': imported, 'errors': errors}


def _flatten_error(detail) -> str:
    """Render a DRF ValidationError detail as a single-line string."""
    if isinstance(detail, dict):
        parts = []
        for field, msgs in detail.items():
            if isinstance(msgs, (list, tuple)):
                parts.append(f'{field}: {"; ".join(str(m) for m in msgs)}')
            else:
                parts.append(f'{field}: {msgs}')
        return ' | '.join(parts)
    if isinstance(detail, (list, tuple)):
        return '; '.join(str(m) for m in detail)
    return str(detail)


# ---------------------------------------------------------------------------
# Sprint 31 — billing run + schedule serializers
# ---------------------------------------------------------------------------


class BillingLineItemSerializer(serializers.ModelSerializer):
    """Read-only line item serializer."""

    class Meta:
        model = BillingLineItem
        fields = (
            'id',
            'billing_account',
            'stream',
            'line_kind',
            'period_name',
            'kwh',
            'rate_cents_per_kwh',
            'amount_cents',
            'gst_cents',
            'quality_summary',
            'source_account',
        )
        read_only_fields = fields


class BillingRunSnapshotSerializer(serializers.ModelSerializer):
    """Read-only snapshot serializer."""

    class Meta:
        model = BillingRunSnapshot
        fields = (
            'id',
            'billing_account',
            'stream',
            'interval_aggregate_ids',
            'computed_kwh',
            'quality_summary',
        )
        read_only_fields = fields


class BillingRunSerializer(serializers.ModelSerializer):
    """Read serializer for BillingRun. Writes go through `BillingRunCreateSerializer`."""

    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None,
    )
    finalized_by_email = serializers.EmailField(
        source='finalized_by.email', read_only=True, default=None,
    )

    class Meta:
        model = BillingRun
        fields = (
            'id',
            'tenant',
            'site',
            'billing_account_ids',
            'period_start',
            'period_end',
            'timezone_snapshot',
            'aggregate_period',
            'status',
            'failed_step',
            'failure_detail',
            'created_by',
            'created_by_email',
            'finalized_by',
            'finalized_by_email',
            'created_at',
            'computed_at',
            'finalized_at',
            'voided_at',
        )
        read_only_fields = fields


class BillingRunCreateSerializer(serializers.Serializer):
    """Validates POST /api/v1/billing-runs/ input."""

    site = serializers.IntegerField()
    billing_account_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text='Optional explicit account filter within the site. Empty = all active.',
    )
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    aggregate_period = serializers.ChoiceField(
        choices=BillingRun.AggregatePeriod.choices,
        default=BillingRun.AggregatePeriod.THIRTY_MIN,
    )

    def validate(self, attrs):
        """Enforce period_end > period_start."""
        if attrs['period_end'] <= attrs['period_start']:
            raise serializers.ValidationError(
                {'period_end': 'period_end must be strictly after period_start.'},
            )
        return attrs


class BillingScheduleSerializer(serializers.ModelSerializer):
    """CRUD serializer for BillingSchedule."""

    class Meta:
        model = BillingSchedule
        fields = (
            'id',
            'tenant',
            'name',
            'site',
            'billing_account_ids',
            'aggregate_period',
            'cadence',
            'anchor_day',
            'period_offset_days',
            'custom_cron',
            'auto_finalize',
            'is_active',
            'last_run_at',
            'next_run_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'tenant', 'last_run_at', 'created_at', 'updated_at')

    def validate(self, attrs):
        """Enforce anchor_day required for monthly_anchor; custom_cron for custom_cron."""
        cadence = attrs.get('cadence') or getattr(self.instance, 'cadence', None)
        if cadence == BillingSchedule.Cadence.MONTHLY_ANCHOR:
            anchor = attrs.get('anchor_day')
            if anchor is None and not getattr(self.instance, 'anchor_day', None):
                raise serializers.ValidationError(
                    {'anchor_day': 'anchor_day is required for monthly_anchor cadence.'},
                )
            if anchor is not None and not (1 <= anchor <= 31):
                raise serializers.ValidationError(
                    {'anchor_day': 'anchor_day must be between 1 and 31.'},
                )
        if cadence == BillingSchedule.Cadence.CUSTOM_CRON:
            cron = attrs.get('custom_cron') or getattr(self.instance, 'custom_cron', '')
            if not cron:
                raise serializers.ValidationError(
                    {'custom_cron': 'custom_cron is required for custom_cron cadence.'},
                )
        return attrs


class BillingInvoiceSerializer(serializers.ModelSerializer):
    """Read-only serializer for BillingInvoice (Sprint 32)."""

    billing_account_name = serializers.CharField(
        source='billing_account.name', read_only=True,
    )
    billing_run_period_start = serializers.DateTimeField(
        source='billing_run.period_start', read_only=True,
    )
    billing_run_period_end = serializers.DateTimeField(
        source='billing_run.period_end', read_only=True,
    )

    class Meta:
        model = BillingInvoice
        fields = (
            'id',
            'billing_run',
            'billing_account',
            'billing_account_name',
            'billing_run_period_start',
            'billing_run_period_end',
            'invoice_number',
            'period_start',
            'period_end',
            'subtotal_cents',
            'gst_cents',
            'total_cents',
            'pdf_object_key',
            'status',
            'delivery_status',
            'issued_at',
            'delivered_at',
            'voided_at',
        )
        read_only_fields = fields
