"""Devices app models.

Sprint 4: Site
Sprint 5: DeviceType, Device
Sprint 21: CommandLog
"""
import logging

from django.db import models
from encrypted_model_fields.fields import EncryptedTextField

logger = logging.getLogger(__name__)


class Site(models.Model):
    """A physical location belonging to a tenant.

    Devices are deployed at Sites. Tenant A's Sites are invisible to Tenant B.
    """

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='sites',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='WGS84 decimal degrees.',
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='WGS84 decimal degrees.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.tenant.name})'


class DeviceType(models.Model):
    """Device type definition managed by That Place Admin.

    Defines the capabilities, stream hints, and command schemas for a
    category of hardware. All devices must be assigned a DeviceType.
    Ref: SPEC.md § Data Model: DeviceType
    """

    class ConnectionType(models.TextChoices):
        MQTT = 'mqtt', 'MQTT (push)'
        API = 'api', '3rd Party API (poll)'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default='')
    connection_type = models.CharField(
        max_length=20,
        choices=ConnectionType.choices,
        default=ConnectionType.MQTT,
    )
    is_push = models.BooleanField(
        default=True,
        help_text='True if the device pushes data (MQTT). False if the platform polls (API).',
    )
    default_offline_threshold_minutes = models.PositiveIntegerField(
        default=10,
        help_text='Minutes of silence before a device of this type is marked offline.',
    )
    command_ack_timeout_seconds = models.PositiveIntegerField(
        default=30,
        help_text='Seconds to wait for a command acknowledgment before marking timed_out.',
    )
    commands = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Array of command definitions. Each entry: '
            '{name, label, description, params: [{name, label, type}]}'
        ),
    )
    stream_type_definitions = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Hint array used during stream auto-discovery. Each entry: '
            '{key, label, data_type, unit}'
        ),
    )
    status_indicator_mappings = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Per-stream status indicator mappings for the Status Indicator dashboard widget. '
            'Keyed by stream key; each value is a list of {value, color, label} entries. '
            'Example: {"motor_status": [{"value": "running", "color": "#22C55E", "label": "Running"}]}'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Device(models.Model):
    """A physical device registered by a tenant.

    Devices start as `pending` after registration and must be approved by a
    That Place Admin before they can submit data. Tenant A's devices are
    never visible to Tenant B.
    Ref: SPEC.md § Data Model: Device
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACTIVE = 'active', 'Active'
        REJECTED = 'rejected', 'Rejected'
        DEACTIVATED = 'deactivated', 'Deactivated'

    class TopicFormat(models.TextChoices):
        LEGACY_V1 = 'legacy_v1', 'Legacy v1'
        THAT_PLACE_V1 = 'that_place_v1', 'That Place v1'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='devices',
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='devices',
    )
    device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.PROTECT,
        related_name='devices',
    )
    name = models.CharField(max_length=255)
    serial_number = models.CharField(
        max_length=255,
        unique=True,
        help_text='Hardware serial number — must be unique across all tenants.',
    )
    gateway_device = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='bridged_devices',
        help_text='Parent Scout that bridges this device over MQTT, if applicable.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    offline_threshold_override_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='If set, overrides the device type default offline threshold for this device.',
    )
    topic_format = models.CharField(
        max_length=20,
        choices=TopicFormat.choices,
        null=True,
        blank=True,
        help_text='Auto-detected from incoming MQTT traffic. Null until first message received.',
    )

    class MQTTAuthMode(models.TextChoices):
        PASSWORD = 'password', 'Username / Password (port 1883)'
        CERTIFICATE = 'certificate', 'Client Certificate / mTLS (port 8883)'

    mqtt_auth_mode = models.CharField(
        max_length=20,
        choices=MQTTAuthMode.choices,
        default=MQTTAuthMode.PASSWORD,
        help_text=(
            'Authentication mode used when this Scout connects to the MQTT broker. '
            'Password: legacy devices or devices without TLS support (port 1883). '
            'Certificate: new That Place v1 Scouts with mTLS support (port 8883).'
        ),
    )
    mqtt_password = EncryptedTextField(
        null=True,
        blank=True,
        help_text=(
            'Encrypted MQTT password (password mode only). '
            'Provide to the device operator for Scout firmware configuration.'
        ),
    )
    mqtt_certificate = models.TextField(
        null=True,
        blank=True,
        help_text=(
            'PEM-encoded client certificate (certificate mode only). '
            'Public — safe to store unencrypted. Provide to the device operator '
            'alongside the private key for Scout firmware configuration.'
        ),
    )
    mqtt_private_key = EncryptedTextField(
        null=True,
        blank=True,
        help_text=(
            'Encrypted PEM-encoded private key (certificate mode only). '
            'Provide to the device operator for Scout firmware configuration. '
            'Clear this field once the operator confirms the key has been loaded.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.serial_number})'


class DeviceHealth(models.Model):
    """Real-time health snapshot for a device.

    Created on first message receipt. Updated on every subsequent message.
    is_online is flipped to False by the offline detection Celery beat task
    when no message has been received within the device's offline threshold.

    battery_level and signal_strength are null for legacy v1 devices (no
    health data in their telemetry payload).

    Ref: SPEC.md § Data Model: DeviceHealth
         SPEC.md § Feature: Device Health Monitoring
    """

    class ActivityLevel(models.TextChoices):
        NORMAL = 'normal', 'Normal'
        DEGRADED = 'degraded', 'Degraded'
        CRITICAL = 'critical', 'Critical'

    device = models.OneToOneField(
        Device,
        on_delete=models.CASCADE,
        related_name='devicehealth',
    )
    is_online = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    first_active_at = models.DateTimeField(null=True, blank=True)
    signal_strength = models.IntegerField(
        null=True, blank=True,
        help_text='Signal strength in dBm. Null for legacy v1 devices.',
    )
    battery_level = models.IntegerField(
        null=True, blank=True,
        help_text='Battery level as a percentage (0–100). Null for legacy v1 devices.',
    )
    activity_level = models.CharField(
        max_length=20,
        choices=ActivityLevel.choices,
        default=ActivityLevel.NORMAL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.device.serial_number} — {self.activity_level} (online={self.is_online})'


class CommandLog(models.Model):
    """Audit record for every command sent to a device.

    Created by the send_device_command Celery task. Status progresses from
    'sent' → 'acknowledged' (on ack receipt) or 'timed_out' (on beat task).
    Ref: SPEC.md § Feature: Device Control — Command history
    """

    class Status(models.TextChoices):
        SENT = 'sent', 'Sent'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        TIMED_OUT = 'timed_out', 'Timed Out'

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='command_logs',
    )
    sent_by = models.ForeignKey(
        'accounts.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sent_commands',
        help_text='User who sent the command. Null if triggered by a rule.',
    )
    triggered_by_rule = models.ForeignKey(
        'rules.Rule',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='triggered_commands',
        help_text='Rule that triggered this command. Null if sent manually.',
    )
    command_name = models.CharField(max_length=255)
    params_sent = models.JSONField(default=dict)
    sent_at = models.DateTimeField(auto_now_add=True)
    ack_received_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SENT,
    )

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f'CommandLog({self.device.serial_number} / {self.command_name} / {self.status})'
