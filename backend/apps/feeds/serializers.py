"""Serializers for the feeds app.

FeedProvider has two serializers:
  FeedProviderAdminSerializer  — full fields (That Place Admin)
  FeedProviderPublicSerializer — name/description only (Tenant Admin)

ReferenceDataset has two serializers:
  ReferenceDatasetAdminSerializer  — full schema fields (That Place Admin)
  ReferenceDatasetPublicSerializer — name/description/schema (Tenant Admin — read)

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets
     security_risks.md § SR-04 — CSV Bulk Import Injection and Resource Exhaustion
"""
import csv
import io
import logging

from rest_framework import serializers

# ---------------------------------------------------------------------------
# SR-04 — CSV injection / resource exhaustion constants
# ---------------------------------------------------------------------------

# Maximum CSV upload size accepted by the bulk import endpoint (bytes).
CSV_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Maximum number of data rows (excluding header) accepted per bulk import.
CSV_MAX_ROWS = 50_000

# Characters that trigger formula evaluation in Excel / Google Sheets when
# they appear at the start of a cell value.
# Ref: OWASP CSV Injection — https://owasp.org/www-community/attacks/CSV_Injection
_FORMULA_PREFIXES = frozenset('=+-@')


def sanitize_csv_cell(value: str) -> str:
    """Prefix formula-triggering characters with a tab to prevent CSV injection.

    Any cell value that begins with ``=``, ``+``, ``-``, or ``@`` is prefixed
    with a tab character so that spreadsheet applications treat it as a text
    value rather than a formula.

    Use this on every cell when writing CSV output — never on import (the raw
    value should be stored faithfully; sanitisation only applies to export).

    Ref: security_risks.md § SR-04
    """
    if value and value[0] in _FORMULA_PREFIXES:
        return '\t' + value
    return value

from .models import (
    FeedChannel,
    FeedProvider,
    FeedReading,
    ReferenceDataset,
    ReferenceDatasetRow,
    TenantDatasetAssignment,
    TenantFeedSubscription,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FeedProvider serializers
# ---------------------------------------------------------------------------

class FeedProviderAdminSerializer(serializers.ModelSerializer):
    """Full FeedProvider serializer for That Place Admin."""

    class Meta:
        model = FeedProvider
        fields = [
            'id', 'name', 'slug', 'description', 'base_url',
            'auth_type', 'auth_param_schema', 'scope',
            'poll_interval_seconds', 'endpoints', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class FeedProviderPublicSerializer(serializers.ModelSerializer):
    """Limited FeedProvider serializer for Tenant Admins (name + description only)."""

    class Meta:
        model = FeedProvider
        fields = ['id', 'name', 'slug', 'description', 'scope', 'is_active']
        read_only_fields = fields


class FeedChannelSerializer(serializers.ModelSerializer):
    """FeedChannel serializer — read-only for API consumers."""

    provider_name = serializers.CharField(source='provider.name', read_only=True)
    latest_reading = serializers.SerializerMethodField()

    def get_latest_reading(self, obj) -> dict | None:
        """Return the most recent FeedReading for this channel, or None."""
        reading = obj.readings.order_by('-timestamp').first()
        if reading is None:
            return None
        return {
            'value': reading.value,
            'timestamp': reading.timestamp,
            'fetched_at': reading.fetched_at,
        }

    class Meta:
        model = FeedChannel
        fields = [
            'id', 'provider', 'provider_name', 'key', 'label', 'unit',
            'data_type', 'dimension_value', 'is_active', 'latest_reading',
        ]
        read_only_fields = fields


class FeedReadingSerializer(serializers.ModelSerializer):
    """FeedReading serializer."""

    class Meta:
        model = FeedReading
        fields = ['id', 'channel', 'value', 'timestamp', 'fetched_at']
        read_only_fields = fields


class TenantFeedSubscriptionSerializer(serializers.ModelSerializer):
    """TenantFeedSubscription serializer.

    credentials is write-only — never returned in responses.
    """

    credentials = serializers.JSONField(write_only=True, required=False, default=dict)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    subscribed_channels = FeedChannelSerializer(many=True, read_only=True, source='_subscribed_channel_objs')

    def validate_provider(self, provider: FeedProvider) -> FeedProvider:
        """Only scope=tenant providers can be subscribed to."""
        if provider.scope != FeedProvider.Scope.TENANT:
            raise serializers.ValidationError(
                'Only scope=tenant providers can have tenant subscriptions. '
                'scope=system providers are polled globally.'
            )
        return provider

    def validate(self, attrs: dict) -> dict:
        """Inject tenant from request context."""
        request = self.context['request']
        attrs['tenant'] = request.user.tenantuser.tenant
        return attrs

    class Meta:
        model = TenantFeedSubscription
        fields = [
            'id', 'provider', 'provider_name', 'credentials',
            'subscribed_channel_ids', 'subscribed_channels',
            'is_active', 'last_polled_at', 'last_poll_status', 'last_poll_error',
        ]
        read_only_fields = [
            'id', 'provider_name', 'subscribed_channels',
            'last_polled_at', 'last_poll_status', 'last_poll_error',
        ]


# ---------------------------------------------------------------------------
# ReferenceDataset serializers
# ---------------------------------------------------------------------------

class ReferenceDatasetAdminSerializer(serializers.ModelSerializer):
    """Full ReferenceDataset serializer for That Place Admin."""

    class Meta:
        model = ReferenceDataset
        fields = [
            'id', 'name', 'slug', 'description',
            'dimension_schema', 'value_schema',
            'has_time_of_use', 'has_version', 'scope',
            'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ReferenceDatasetPublicSerializer(serializers.ModelSerializer):
    """Public ReferenceDataset serializer for Tenant Admins (read-only)."""

    class Meta:
        model = ReferenceDataset
        fields = [
            'id', 'name', 'slug', 'description',
            'dimension_schema', 'value_schema',
            'has_time_of_use', 'has_version',
        ]
        read_only_fields = fields


class ReferenceDatasetRowSerializer(serializers.ModelSerializer):
    """ReferenceDatasetRow serializer — used by That Place Admin for row management."""

    def validate(self, attrs: dict) -> dict:
        """Validate version required when dataset.has_version is true."""
        dataset = attrs.get('dataset') or (self.instance.dataset if self.instance else None)
        if dataset and dataset.has_version and not attrs.get('version'):
            raise serializers.ValidationError(
                {'version': 'version is required for this dataset (has_version=true).'}
            )
        return attrs

    class Meta:
        model = ReferenceDatasetRow
        fields = [
            'id', 'dataset', 'version', 'dimensions', 'values',
            'applicable_days', 'time_from', 'time_to',
            'valid_from', 'valid_to', 'is_active',
        ]
        read_only_fields = ['id']


class BulkRowImportSerializer(serializers.Serializer):
    """Accepts a CSV file upload for bulk upsert of ReferenceDatasetRows.

    CSV columns must match: all dimension_schema keys + all value_schema keys,
    plus optionally: version, applicable_days, time_from, time_to, valid_from, valid_to.

    Returns: {imported: N, errors: [{row: N, error: "..."}]}
    """

    file = serializers.FileField()

    def validate_file(self, value):
        """Reject non-CSV files and files that exceed the size limit."""
        if not value.name.endswith('.csv'):
            raise serializers.ValidationError('Only CSV files are accepted.')
        if value.size > CSV_MAX_UPLOAD_BYTES:
            limit_mb = CSV_MAX_UPLOAD_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                f'File too large. Maximum upload size is {limit_mb} MB.'
            )
        return value

    def import_rows(self, dataset: ReferenceDataset) -> dict:
        """Parse CSV and upsert rows. Returns import summary."""
        file = self.validated_data['file']
        try:
            text = file.read().decode('utf-8-sig')  # strip BOM if present
        except UnicodeDecodeError:
            return {'imported': 0, 'errors': [{'row': 0, 'error': 'File is not valid UTF-8.'}]}

        reader = csv.DictReader(io.StringIO(text))
        dim_keys = list((dataset.dimension_schema or {}).keys())
        val_keys = list((dataset.value_schema or {}).keys())

        # Materialise rows upfront so we can enforce the count limit before
        # touching the database. This also prevents streaming exhaustion attacks.
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

        imported = 0
        errors = []

        for row_num, row in enumerate(all_rows, start=2):  # row 1 is header
            try:
                # Build dimensions dict
                dimensions = {}
                for k in dim_keys:
                    if k not in row:
                        raise ValueError(f'Missing column "{k}"')
                    dimensions[k] = row[k].strip()

                # Build values dict
                values = {}
                for k in val_keys:
                    if k not in row:
                        raise ValueError(f'Missing column "{k}"')
                    raw = row[k].strip()
                    try:
                        values[k] = float(raw) if raw else None
                    except ValueError:
                        values[k] = raw  # keep as string for non-numeric columns

                # Optional fields
                version = row.get('version', '').strip() or None
                applicable_days_raw = row.get('applicable_days', '').strip()
                applicable_days = None
                if applicable_days_raw:
                    applicable_days = [int(d.strip()) for d in applicable_days_raw.split(',') if d.strip()]
                time_from = row.get('time_from', '').strip() or None
                time_to = row.get('time_to', '').strip() or None
                valid_from = row.get('valid_from', '').strip() or None
                valid_to = row.get('valid_to', '').strip() or None

                # Upsert — match on dataset + dimensions + version
                obj, created = ReferenceDatasetRow.objects.update_or_create(
                    dataset=dataset,
                    dimensions=dimensions,
                    version=version,
                    defaults={
                        'values': values,
                        'applicable_days': applicable_days,
                        'time_from': time_from,
                        'time_to': time_to,
                        'valid_from': valid_from,
                        'valid_to': valid_to,
                        'is_active': True,
                    },
                )
                imported += 1

            except Exception as exc:
                errors.append({'row': row_num, 'error': str(exc)})

        return {'imported': imported, 'errors': errors}


class TenantDatasetAssignmentSerializer(serializers.ModelSerializer):
    """TenantDatasetAssignment serializer for Tenant Admins."""

    dataset_name = serializers.CharField(source='dataset.name', read_only=True)
    dataset_slug = serializers.CharField(source='dataset.slug', read_only=True)
    site_name = serializers.CharField(source='site.name', read_only=True, allow_null=True)
    resolved = serializers.SerializerMethodField()

    def get_resolved(self, obj) -> dict | None:
        """Return currently resolved row values for preview, or None."""
        from .resolution import resolve_dataset_assignment
        try:
            result = resolve_dataset_assignment(obj)
            return result
        except Exception:
            return None

    def validate(self, attrs: dict) -> dict:
        """Inject tenant from request context; validate site belongs to tenant."""
        request = self.context['request']
        tenant = request.user.tenantuser.tenant
        attrs['tenant'] = tenant
        site = attrs.get('site')
        if site and site.tenant_id != tenant.id:
            raise serializers.ValidationError({'site': 'Site does not belong to your tenant.'})
        return attrs

    class Meta:
        model = TenantDatasetAssignment
        fields = [
            'id', 'dataset', 'dataset_name', 'dataset_slug',
            'site', 'site_name',
            'dimension_filter', 'version',
            'effective_from', 'effective_to',
            'created_at', 'resolved',
        ]
        read_only_fields = ['id', 'dataset_name', 'dataset_slug', 'site_name', 'created_at', 'resolved']
