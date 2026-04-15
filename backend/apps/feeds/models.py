"""Models for the feeds app.

Two engines:

FeedProvider engine — API-polled data channels:
  FeedProvider          — platform library; configured by That Place Admin
  FeedChannel           — a named scalar channel produced by a provider
  FeedReading           — a timestamped value on a channel
  TenantFeedSubscription — tenant connection to a scope=tenant provider
  FeedChannelRuleIndex  — stream→rule index equivalent for feed channels

ReferenceDataset engine — admin-managed lookup tables:
  ReferenceDataset       — schema definition (dimension + value columns)
  ReferenceDatasetRow    — a single row of data
  TenantDatasetAssignment — links a site (or tenant) to a subset of rows

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets,
     § Data Model
"""
import logging

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models

from apps.integrations.fields import EncryptedJSONField

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FeedProvider engine
# ---------------------------------------------------------------------------

class FeedProvider(models.Model):
    """Platform-level API-polled data feed configuration.

    Managed by That Place Admin. Scope=system feeds are polled once globally
    and readings are available to all tenants. Scope=tenant feeds require each
    tenant to subscribe with their own credentials.

    The endpoints JSONB array defines what to fetch and how to extract channel
    values via JSONPath. FeedChannel records are auto-populated from this config
    on provider create/update, with dimension values discovered on first poll.

    Ref: SPEC.md § Feature: Feed Providers
    """

    class AuthType(models.TextChoices):
        NONE = 'none', 'None (public endpoint)'
        API_KEY_HEADER = 'api_key_header', 'API Key (Header)'
        BEARER_TOKEN = 'bearer_token', 'Bearer Token'
        OAUTH2_CLIENT_CREDENTIALS = 'oauth2_client_credentials', 'OAuth2 Client Credentials'
        OAUTH2_PASSWORD = 'oauth2_password', 'OAuth2 Password Grant'

    class Scope(models.TextChoices):
        SYSTEM = 'system', 'System — polled once globally, available to all tenants'
        TENANT = 'tenant', 'Tenant — each tenant subscribes with their own credentials'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default='')
    base_url = models.URLField(max_length=500)
    auth_type = models.CharField(
        max_length=40,
        choices=AuthType.choices,
        default=AuthType.NONE,
    )
    auth_param_schema = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Array of credential field definitions for scope=tenant providers. '
            'Each entry: {key, label, type (text/password), required (bool)}. '
            'Leave empty for scope=system providers with no auth.'
        ),
    )
    scope = models.CharField(
        max_length=10,
        choices=Scope.choices,
        default=Scope.SYSTEM,
    )
    poll_interval_seconds = models.PositiveIntegerField(
        default=300,
        validators=[MinValueValidator(60)],
        help_text='How often to poll (seconds). Minimum: 60s, default: 5 minutes (300s).',
    )
    endpoints = models.JSONField(
        default=list,
        help_text=(
            'Array of endpoint configs. Each entry: '
            '{path, method, response_root_jsonpath (optional — JSONPath to iterate rows; '
            'omit for single-object responses), dimension_key (optional — field in each '
            'row that identifies the channel variant, e.g. "REGIONID"), '
            'channels: [{key, label, unit, data_type, value_jsonpath}]}.'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        """Return string representation."""
        return self.name


class FeedChannel(models.Model):
    """A named scalar data channel produced by a FeedProvider.

    Auto-populated from the provider's endpoint channel config on provider
    create/update. For dimensional providers (e.g. AEMO by region), one
    FeedChannel record is created per channel × dimension value combination.
    Dimension values are discovered on the first successful poll.

    Ref: SPEC.md § Feature: Feed Providers, § Data Model — FeedChannel
    """

    class DataType(models.TextChoices):
        NUMERIC = 'numeric', 'Numeric'
        BOOLEAN = 'boolean', 'Boolean'
        STRING = 'string', 'String'

    provider = models.ForeignKey(
        FeedProvider,
        on_delete=models.CASCADE,
        related_name='channels',
    )
    key = models.CharField(
        max_length=100,
        help_text='Machine-readable channel key (e.g. "rrp", "raise_reg_rrp").',
    )
    label = models.CharField(max_length=255)
    unit = models.CharField(max_length=50, blank=True, default='')
    data_type = models.CharField(
        max_length=10,
        choices=DataType.choices,
        default=DataType.NUMERIC,
    )
    dimension_value = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=(
            'Dimension value that identifies this channel instance '
            '(e.g. "NSW1" for a regional channel). Null for dimensionless channels.'
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['provider', 'key', 'dimension_value']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'key', 'dimension_value'],
                name='unique_feed_channel',
            )
        ]

    def __str__(self) -> str:
        """Return string representation."""
        if self.dimension_value:
            return f'{self.provider.slug} / {self.key} / {self.dimension_value}'
        return f'{self.provider.slug} / {self.key}'


class FeedReading(models.Model):
    """A timestamped value on a FeedChannel.

    Stored whenever the poller fetches a new value. The unique constraint on
    (channel, timestamp) makes polls idempotent — duplicate readings within the
    same dispatch interval are silently ignored via get_or_create / ignore_conflicts.

    Ref: SPEC.md § Feature: Feed Providers, § Data Model — FeedReading
         § Key Business Rules — FeedReading unique_together
    """

    channel = models.ForeignKey(
        FeedChannel,
        on_delete=models.CASCADE,
        related_name='readings',
    )
    value = models.JSONField(
        help_text='Reading value. Numeric readings stored as float; boolean as bool; string as str.',
    )
    timestamp = models.DateTimeField(
        help_text='Settlement/interval timestamp reported by the provider.',
        db_index=True,
    )
    fetched_at = models.DateTimeField(
        help_text='When this reading was fetched by the poller.',
    )

    class Meta:
        ordering = ['-timestamp']
        constraints = [
            models.UniqueConstraint(
                fields=['channel', 'timestamp'],
                name='unique_feed_reading_per_interval',
            )
        ]

    def __str__(self) -> str:
        """Return string representation."""
        return f'FeedReading({self.channel}, {self.timestamp}, {self.value})'


class TenantFeedSubscription(models.Model):
    """A tenant's subscription to a scope=tenant FeedProvider.

    Stores encrypted credentials for the tenant's account with the provider.
    Only created for scope=tenant providers; scope=system providers are polled
    globally with no subscription records.

    Ref: SPEC.md § Feature: Feed Providers, § Data Model — TenantFeedSubscription
    """

    class PollStatus(models.TextChoices):
        OK = 'ok', 'OK'
        ERROR = 'error', 'Error'
        AUTH_FAILURE = 'auth_failure', 'Auth Failure'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='feed_subscriptions',
    )
    provider = models.ForeignKey(
        FeedProvider,
        on_delete=models.PROTECT,
        related_name='subscriptions',
        limit_choices_to={'scope': FeedProvider.Scope.TENANT},
    )
    credentials = EncryptedJSONField(
        default=dict,
        help_text='Encrypted tenant credentials — filled from provider auth_param_schema.',
    )
    subscribed_channel_ids = ArrayField(
        models.IntegerField(),
        default=list,
        help_text='PKs of FeedChannel records the tenant has subscribed to.',
    )
    is_active = models.BooleanField(default=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_poll_status = models.CharField(
        max_length=20,
        choices=PollStatus.choices,
        null=True,
        blank=True,
    )
    last_poll_error = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-tenant__name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'provider'],
                name='unique_feed_subscription_per_tenant',
            )
        ]

    def __str__(self) -> str:
        """Return string representation."""
        return f'{self.tenant.name} → {self.provider.name}'


class FeedChannelRuleIndex(models.Model):
    """Index mapping FeedChannels to Rules that reference them.

    Maintained automatically on every rule create/edit/delete (same pattern as
    RuleStreamIndex in the readings app). Used by the feed poller to dispatch
    rule evaluation tasks only for rules that reference a given channel, rather
    than evaluating all tenant rules on every reading.

    Ref: SPEC.md § Feature: Feed Providers, § Key Business Rules — FeedChannelRuleIndex
    """

    channel = models.ForeignKey(
        FeedChannel,
        on_delete=models.CASCADE,
        related_name='rule_index_entries',
    )
    rule = models.ForeignKey(
        'rules.Rule',
        on_delete=models.CASCADE,
        related_name='feed_channel_index_entries',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['channel', 'rule'],
                name='unique_feed_channel_rule_index',
            )
        ]

    def __str__(self) -> str:
        """Return string representation."""
        return f'FeedChannelRuleIndex(channel={self.channel_id}, rule={self.rule_id})'


# ---------------------------------------------------------------------------
# ReferenceDataset engine
# ---------------------------------------------------------------------------

class ReferenceDataset(models.Model):
    """Schema definition for an admin-managed lookup table.

    The admin defines the structure once (dimension columns = lookup keys,
    value columns = the actual numbers). Rows are then managed via the admin
    UI or bulk CSV upload. No code changes are needed to add new datasets,
    new distributors, new tariff types, or new dataset categories.

    Ref: SPEC.md § Feature: Reference Datasets, § Data Model — ReferenceDataset
    """

    class Scope(models.TextChoices):
        SYSTEM = 'system', 'System — managed by That Place Admin, shared across all tenants'
        TENANT = 'tenant', 'Tenant — each tenant manages their own rows (future use)'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default='')
    dimension_schema = models.JSONField(
        default=list,
        help_text=(
            'Array defining lookup key columns. Each entry: {key, label, type}. '
            'Example: [{key: "distributor_slug", label: "Distributor", type: "string"}, '
            '{key: "tariff_code", label: "Tariff Code", type: "string"}, '
            '{key: "period_name", label: "Period", type: "string"}].'
        ),
    )
    value_schema = models.JSONField(
        default=list,
        help_text=(
            'Array defining value columns. Each entry: {key, label, type, unit}. '
            'Example: [{key: "rate_cents_per_kwh", label: "Rate", type: "decimal", unit: "c/kWh"}, '
            '{key: "daily_supply_cents", label: "Daily Supply", type: "decimal", unit: "c/day"}].'
        ),
    )
    has_time_of_use = models.BooleanField(
        default=False,
        help_text=(
            'When true, rows carry applicable_days, time_from, and time_to. '
            'The row resolver filters by current day/time in tenant timezone.'
        ),
    )
    has_version = models.BooleanField(
        default=False,
        help_text=(
            'When true, rows carry a version label (e.g. "2025-26"). '
            'Used for annually-updated datasets like network tariffs.'
        ),
    )
    scope = models.CharField(
        max_length=10,
        choices=Scope.choices,
        default=Scope.SYSTEM,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        """Return string representation."""
        return self.name


class ReferenceDatasetRow(models.Model):
    """A single row of data in a ReferenceDataset.

    dimensions JSONB must match the dataset's dimension_schema keys.
    values JSONB must match the dataset's value_schema keys.

    For has_time_of_use datasets, applicable_days/time_from/time_to define
    when this row is active (resolved in tenant timezone).
    For has_version datasets, version is required (e.g. "2025-26").

    Ref: SPEC.md § Feature: Reference Datasets, § Data Model — ReferenceDatasetRow
    """

    dataset = models.ForeignKey(
        ReferenceDataset,
        on_delete=models.CASCADE,
        related_name='rows',
    )
    version = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Financial year or period label (e.g. "2025-26"). Required when dataset.has_version is true.',
    )
    dimensions = models.JSONField(
        help_text=(
            'Lookup key values matching dataset.dimension_schema. '
            'Example: {distributor_slug: "ausgrid", tariff_code: "EA305", period_name: "peak"}.'
        ),
    )
    values = models.JSONField(
        help_text=(
            'Actual data values matching dataset.value_schema. '
            'Example: {rate_cents_per_kwh: 32.50, daily_supply_cents: 110.0}.'
        ),
    )
    # Time-of-use fields — only used when dataset.has_time_of_use is true
    applicable_days = ArrayField(
        models.IntegerField(),
        null=True,
        blank=True,
        help_text='Days of week this row applies: 0=Mon … 6=Sun. Null = all days.',
    )
    time_from = models.TimeField(
        null=True,
        blank=True,
        help_text='Start of the applicable time window (wall-clock, not UTC).',
    )
    time_to = models.TimeField(
        null=True,
        blank=True,
        help_text='End of the applicable time window (wall-clock, not UTC).',
    )
    # Optional date-bounded validity (independent of versioning)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['dataset', 'version', 'id']

    def __str__(self) -> str:
        """Return string representation."""
        version_str = f' [{self.version}]' if self.version else ''
        return f'{self.dataset.slug}{version_str} {self.dimensions}'


class TenantDatasetAssignment(models.Model):
    """Links a tenant site (or tenant-wide) to specific rows of a ReferenceDataset.

    dimension_filter identifies which rows apply to this site — it is matched
    against each ReferenceDatasetRow's dimensions at evaluation time.

    A site-specific assignment (non-null site) overrides a tenant-wide assignment
    (null site) for that site.

    Ref: SPEC.md § Feature: Reference Datasets, § Data Model — TenantDatasetAssignment
         § Key Business Rules — TenantDatasetAssignment
    """

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='dataset_assignments',
    )
    site = models.ForeignKey(
        'devices.Site',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='dataset_assignments',
        help_text='Null = tenant-wide assignment. Site-specific overrides tenant-wide.',
    )
    dataset = models.ForeignKey(
        ReferenceDataset,
        on_delete=models.PROTECT,
        related_name='tenant_assignments',
    )
    dimension_filter = models.JSONField(
        help_text=(
            'Dimension values identifying the applicable rows for this site. '
            'Example: {distributor_slug: "ausgrid", tariff_code: "EA305"}. '
            'Rows whose dimensions contain all keys in this filter are candidates.'
        ),
    )
    version = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=(
            'Pinned version label (e.g. "2025-26"). When null, the resolver '
            'always uses the latest active version.'
        ),
    )
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text='Null = currently active. Expired assignments are retained for audit.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        """Return string representation."""
        scope = self.site.name if self.site_id else 'tenant-wide'
        return f'{self.tenant.name} / {self.dataset.slug} ({scope})'
