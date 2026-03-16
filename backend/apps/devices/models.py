"""Devices app models.

Sprint 4: Site
Sprint 5: DeviceType, Device
"""
import logging

from django.db import models

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
    """Device type definition managed by Fieldmouse Admin.

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
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Device(models.Model):
    """A physical device registered by a tenant.

    Devices start as `pending` after registration and must be approved by a
    Fieldmouse Admin before they can submit data. Tenant A's devices are
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
        FIELDMOUSE_V2 = 'fieldmouse_v2', 'Fieldmouse v2'

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.serial_number})'
