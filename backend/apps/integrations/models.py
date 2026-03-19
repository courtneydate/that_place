"""Models for the integrations app.

Sprint 10: ThirdPartyAPIProvider, DataSource, DataSourceDevice.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import logging

from django.core.validators import MinValueValidator
from django.db import models

from .fields import EncryptedJSONField

logger = logging.getLogger(__name__)


class ThirdPartyAPIProvider(models.Model):
    """Platform-level 3rd party API provider configuration.

    Managed by Fieldmouse Admin. Defines how the platform connects to a
    provider's API including authentication, device discovery, and data polling.
    Tenant Admins see name/description only — internal schemas are hidden.

    Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
    """

    class AuthType(models.TextChoices):
        API_KEY_HEADER = 'api_key_header', 'API Key (Header)'
        API_KEY_QUERY = 'api_key_query', 'API Key (Query Parameter)'
        BEARER_TOKEN = 'bearer_token', 'Bearer Token'
        BASIC_AUTH = 'basic_auth', 'Basic Auth (Username/Password)'
        OAUTH2_CLIENT_CREDENTIALS = 'oauth2_client_credentials', 'OAuth2 Client Credentials'
        OAUTH2_PASSWORD = 'oauth2_password', 'OAuth2 Password Grant'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default='')
    logo = models.ImageField(
        upload_to='providers/logos/',
        null=True,
        blank=True,
        help_text='Provider logo — stored in configured object storage (S3/MinIO).',
    )
    base_url = models.URLField(max_length=500)
    auth_type = models.CharField(max_length=40, choices=AuthType.choices)
    token_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        help_text=(
            'Token endpoint for OAuth2 auth types. '
            'Leave blank for non-OAuth2 providers.'
        ),
    )
    refresh_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        help_text=(
            'Separate refresh endpoint, if different from token_url '
            '(e.g. SoilScout uses /auth/token/refresh/). '
            'Leave blank to reuse token_url for refresh.'
        ),
    )
    auth_param_schema = models.JSONField(
        default=list,
        help_text=(
            'Array of credential field definitions. Each entry: '
            '{key, label, type (text/password), required (bool)}. '
            'Used to auto-generate the credential entry form for tenants.'
        ),
    )
    discovery_endpoint = models.JSONField(
        default=dict,
        help_text=(
            'Discovery endpoint config: {path, method, device_id_jsonpath, '
            'device_name_jsonpath (optional)}.'
        ),
    )
    detail_endpoint = models.JSONField(
        default=dict,
        help_text=(
            'Detail endpoint config: {path_template (with {device_id}), method}. '
            'Called per device to retrieve current readings.'
        ),
    )
    available_streams = models.JSONField(
        default=list,
        help_text=(
            'Array of stream definitions. Each entry: '
            '{key, label, unit, data_type, jsonpath}.'
        ),
    )
    default_poll_interval_seconds = models.PositiveIntegerField(
        default=300,
        validators=[MinValueValidator(30)],
        help_text='How often to poll each connected device (seconds). Minimum: 30s, default: 5 minutes (300s).',
    )
    max_requests_per_second = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Provider API rate limit (requests/second). Leave blank for no rate limiting.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        """Return string representation."""
        return self.name


class DataSource(models.Model):
    """A tenant's connection to a 3rd party API provider.

    Stores encrypted credentials for the tenant's account with the provider.
    One DataSource may have many connected DataSourceDevices.

    Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
    """

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='data_sources',
    )
    provider = models.ForeignKey(
        ThirdPartyAPIProvider,
        on_delete=models.PROTECT,
        related_name='data_sources',
    )
    name = models.CharField(max_length=255)
    credentials = EncryptedJSONField(
        default=dict,
        help_text='Encrypted tenant credentials — filled from provider auth_param_schema.',
    )
    auth_token_cache = EncryptedJSONField(
        default=dict,
        blank=True,
        help_text='Encrypted token cache for oauth2 auth types (access/refresh tokens + expiry).',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        """Return string representation."""
        return f'{self.name} ({self.tenant.name})'


class DataSourceDevice(models.Model):
    """A single device connected via a DataSource.

    Links an external device ID (from the provider's discovery endpoint) to a
    virtual Device record in Fieldmouse. Tracks polling state and failure count.

    Removing a device sets is_active=False (polling stops; virtual Device record
    and all StreamReadings are retained for history).

    Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
    """

    class PollStatus(models.TextChoices):
        OK = 'ok', 'OK'
        ERROR = 'error', 'Error'
        AUTH_FAILURE = 'auth_failure', 'Auth Failure'

    datasource = models.ForeignKey(
        DataSource,
        on_delete=models.CASCADE,
        related_name='devices',
    )
    external_device_id = models.CharField(
        max_length=500,
        help_text='Device ID as returned by the provider discovery endpoint.',
    )
    external_device_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Device name as returned by the provider discovery endpoint.',
    )
    virtual_device = models.OneToOneField(
        'devices.Device',
        on_delete=models.CASCADE,
        related_name='datasource_device',
        help_text='The virtual Device record representing this external device.',
    )
    active_stream_keys = models.JSONField(
        default=list,
        help_text='Subset of provider available_streams keys the tenant has activated.',
    )
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_poll_status = models.CharField(
        max_length=20,
        choices=PollStatus.choices,
        null=True,
        blank=True,
    )
    last_poll_error = models.TextField(null=True, blank=True)
    consecutive_poll_failures = models.PositiveIntegerField(
        default=0,
        help_text='Consecutive poll failures. Reset to 0 on success.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='False = deactivated. Polling stops but history is retained.',
    )

    class Meta:
        ordering = ['-datasource__created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['datasource', 'external_device_id'],
                name='unique_device_per_datasource',
            )
        ]

    def __str__(self) -> str:
        """Return string representation."""
        name = self.external_device_name or self.external_device_id
        return f'{name} (ds={self.datasource_id})'
