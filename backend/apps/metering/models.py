"""Metering app models — Sprint 29.

MeterProfile is the optional 1:1 sidecar to Device that promotes a device to
a billing meter and records its metering attributes. Devices without a profile
are unaffected — billing only operates on devices that have one.

Ref: SPEC.md § Feature: Metering Model — Meter Profiles
     SPEC.md § Data Model — MeterProfile
     ROADMAP.md § Sprint 29 — Meter Profiles & Billing Roles
"""
from django.db import models


class MeterProfile(models.Model):
    """Billing-meter sidecar for a Device.

    A `Device` becomes a meter by having a MeterProfile. The profile carries
    the billing-relevant attributes — NMI, role in the metering hierarchy,
    parent meter (for embedded networks), phases, pattern approval — that the
    Phase B billing engine reads.

    `tenant` is denormalised from the underlying Device so the
    `(tenant, nmi)` uniqueness can be enforced at the database level when
    NMI is set. PostgreSQL allows multiple NULLs in a UNIQUE column, so the
    constraint only bites when an actual NMI is provided.

    `parent_meter` points to the parent Device (not the parent MeterProfile)
    — matching SPEC.md's wording ("self-FK via Device"). The referenced
    Device must itself have a MeterProfile with `meter_role=gate` on the
    same Site as this device.
    """

    class MeterRole(models.TextChoices):
        GATE = 'gate', 'Gate (embedded-network parent)'
        CHILD = 'child', 'Child (embedded-network tenant)'
        GENERATION = 'generation', 'Generation (solar)'
        STORAGE = 'storage', 'Storage (BESS)'
        CONSUMPTION = 'consumption', 'Consumption (single-tier host)'
        COMMON_AREA = 'common_area', 'Common area / landlord'
        SUB_CHECK = 'sub_check', 'Sub-check (informational)'

    class Phases(models.IntegerChoices):
        SINGLE = 1, 'Single phase'
        THREE = 3, 'Three phase'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='meter_profiles',
        help_text='Denormalised from device.tenant — used for (tenant, nmi) uniqueness.',
    )
    device = models.OneToOneField(
        'devices.Device',
        on_delete=models.CASCADE,
        related_name='meter_profile',
    )
    nmi = models.CharField(
        max_length=11,
        null=True,
        blank=True,
        help_text='10/11-digit National Meter Identifier — unique per tenant when set.',
    )
    meter_role = models.CharField(
        max_length=20,
        choices=MeterRole.choices,
    )
    parent_meter = models.ForeignKey(
        'devices.Device',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='child_meters',
        help_text=(
            'For child/common_area meters at a hierarchical site: the Device that '
            'holds the gate MeterProfile. Must be on the same site.'
        ),
    )
    pattern_approval = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text='e.g. "NMI-M6". Informational — surfaces on invoice footers and audit reports.',
    )
    phases = models.PositiveSmallIntegerField(
        choices=Phases.choices,
        default=Phases.SINGLE,
    )
    install_date = models.DateField(null=True, blank=True)
    serial_number_secondary = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=(
            'Secondary serial number for bundled meter cases '
            '(e.g. CET PMC serial in a WW 6M+One installation).'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'nmi'],
                condition=models.Q(nmi__isnull=False),
                name='meter_profile_unique_nmi_per_tenant',
            ),
        ]
        ordering = ['device__name']

    def __str__(self):
        return f'MeterProfile({self.device.serial_number} · {self.meter_role})'
