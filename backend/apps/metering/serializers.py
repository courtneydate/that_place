"""Serializers for the metering app — Sprint 29.

MeterProfileSerializer carries the write-time invariants that the billing
engine (Phase B) relies on:

  • A `gate` meter has no parent.
  • A `child` or `common_area` meter at a hierarchical site must point to a
    `gate` meter on the same site via `parent_meter`.
  • At most one `gate` meter per site in v1.
  • All other roles (`generation`, `storage`, `consumption`, `sub_check`)
    must not carry a `parent_meter`.
  • NMI is unique per tenant (when set) — enforced at the DB layer too.

Ref: SPEC.md § Feature: Metering Model — Meter Profiles
     ROADMAP.md § Sprint 29 — Meter Profiles & Billing Roles
"""
from __future__ import annotations

import csv
import io

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.devices.models import Device

from .models import MeterProfile

# CSV import safety constants — mirror the feeds bulk-import limits
# (security_risks.md § SR-04).
CSV_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
CSV_MAX_ROWS = 50_000

PARENT_REQUIRED_ROLES = {
    MeterProfile.MeterRole.CHILD,
    MeterProfile.MeterRole.COMMON_AREA,
}
PARENT_FORBIDDEN_ROLES = {
    MeterProfile.MeterRole.GATE,
    MeterProfile.MeterRole.GENERATION,
    MeterProfile.MeterRole.STORAGE,
    MeterProfile.MeterRole.CONSUMPTION,
    MeterProfile.MeterRole.SUB_CHECK,
}


class MeterProfileSerializer(serializers.ModelSerializer):
    """Create, read, and update a MeterProfile for a Device.

    The `device` is supplied by the URL (nested under `/api/v1/devices/:id/`)
    and is injected by the view via `serializer.save(device=device, tenant=…)`.
    `tenant` is denormalised from the Device — never accepted from the client.
    """

    parent_meter_serial = serializers.SerializerMethodField()
    site_id = serializers.IntegerField(source='device.site_id', read_only=True)
    site_is_hierarchical = serializers.BooleanField(
        source='device.site.is_hierarchical', read_only=True,
    )

    class Meta:
        model = MeterProfile
        fields = (
            'id',
            'device',
            'site_id',
            'site_is_hierarchical',
            'nmi',
            'meter_role',
            'parent_meter',
            'parent_meter_serial',
            'pattern_approval',
            'phases',
            'install_date',
            'serial_number_secondary',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id', 'device', 'site_id', 'site_is_hierarchical',
            'parent_meter_serial', 'created_at', 'updated_at',
        )

    def get_parent_meter_serial(self, obj):
        """Return the parent device's serial number, or None."""
        return obj.parent_meter.serial_number if obj.parent_meter_id else None

    def validate_nmi(self, value):
        """Normalise blank NMI to None so the unique constraint behaves correctly."""
        if value in (None, ''):
            return None
        value = value.strip()
        if not value:
            return None
        if not value.isdigit() or len(value) not in (10, 11):
            raise serializers.ValidationError(
                'NMI must be a 10 or 11 digit numeric string.'
            )
        return value

    def validate(self, attrs):
        """Apply the Sprint 29 write-time invariants.

        These rules are the *gate* between freeform device metadata and the
        billing engine. Phase B reads these fields and trusts them; if a
        misconfiguration leaks past, the billing run will compute the wrong
        numbers. So the validation is strict and explicit.
        """
        # The view injects `device` (and therefore `tenant`) via .save() kwargs
        # on create. On update, the device is already on `self.instance`.
        device = self.context.get('device') or (
            self.instance.device if self.instance else None
        )
        if device is None:
            raise serializers.ValidationError('Device context is required.')

        meter_role = attrs.get('meter_role') or (
            self.instance.meter_role if self.instance else None
        )
        parent_meter = attrs.get('parent_meter', None)
        if 'parent_meter' not in attrs and self.instance is not None:
            parent_meter = self.instance.parent_meter

        # 1. Role/parent invariants
        if meter_role in PARENT_FORBIDDEN_ROLES and parent_meter is not None:
            raise serializers.ValidationError({
                'parent_meter': (
                    f'Role "{meter_role}" must not have a parent meter — only '
                    '`child` and `common_area` meters carry a parent.'
                ),
            })

        site = device.site
        if meter_role in PARENT_REQUIRED_ROLES:
            if site.is_hierarchical and parent_meter is None:
                raise serializers.ValidationError({
                    'parent_meter': (
                        f'A `{meter_role}` meter at a hierarchical site requires '
                        'a parent gate meter.'
                    ),
                })
            if parent_meter is not None:
                if parent_meter.site_id != site.id:
                    raise serializers.ValidationError({
                        'parent_meter': 'Parent meter must be on the same site.',
                    })
                parent_profile = getattr(parent_meter, 'meter_profile', None)
                if parent_profile is None or parent_profile.meter_role != MeterProfile.MeterRole.GATE:
                    raise serializers.ValidationError({
                        'parent_meter': 'Parent meter must be a gate meter.',
                    })
                if parent_meter.id == device.id:
                    raise serializers.ValidationError({
                        'parent_meter': 'A meter cannot be its own parent.',
                    })

        # 2. At most one gate per site (v1)
        if meter_role == MeterProfile.MeterRole.GATE:
            existing_gates = MeterProfile.objects.filter(
                device__site_id=site.id,
                meter_role=MeterProfile.MeterRole.GATE,
            )
            if self.instance is not None:
                existing_gates = existing_gates.exclude(pk=self.instance.pk)
            if existing_gates.exists():
                raise serializers.ValidationError({
                    'meter_role': 'This site already has a gate meter (v1 allows at most one).',
                })

        # 3. Role transitions on an existing profile that would break invariants
        if self.instance is not None and meter_role != MeterProfile.MeterRole.GATE:
            # Was this a gate that had children?
            if self.instance.meter_role == MeterProfile.MeterRole.GATE:
                children_qs = MeterProfile.objects.filter(parent_meter_id=device.id)
                if children_qs.exists():
                    raise serializers.ValidationError({
                        'meter_role': (
                            'Cannot change role of a gate meter while child meters '
                            'still point to it. Reassign or remove the children first.'
                        ),
                    })

        return attrs

    def create(self, validated_data):
        """Wrap create to surface DB-level NMI uniqueness as a clean 400."""
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError({
                'nmi': 'This NMI is already used by another meter in your tenant.',
            })

    def update(self, instance, validated_data):
        """Same uniqueness surface-up for update."""
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError({
                'nmi': 'This NMI is already used by another meter in your tenant.',
            })


class BulkMeterProfileImportSerializer(serializers.Serializer):
    """Accepts a CSV upload for bulk MeterProfile upsert (Sprint 29).

    The CSV upsert key is `device_serial` — one row per Device. Rows match on
    Device (and the existing tenant scope); existing MeterProfiles for matched
    devices are updated, missing ones are created.

    Columns (header row required):
      device_serial            (required)
      meter_role               (required — one of the enum values)
      nmi                      (optional)
      parent_meter_serial      (optional — serial number of the parent Device)
      pattern_approval         (optional)
      phases                   (optional — 1 or 3, defaults to 1)
      install_date             (optional — ISO 8601 date, e.g. 2026-05-01)
      serial_number_secondary  (optional)

    Returns: {imported: N, errors: [{row: N, error: "..."}]}
    """

    file = serializers.FileField()

    def validate_file(self, value):
        """Reject non-CSV / oversized files."""
        if not value.name.endswith('.csv'):
            raise serializers.ValidationError('Only CSV files are accepted.')
        if value.size > CSV_MAX_UPLOAD_BYTES:
            limit_mb = CSV_MAX_UPLOAD_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                f'File too large. Maximum upload size is {limit_mb} MB.'
            )
        return value

    def import_rows(self, tenant) -> dict:
        """Parse CSV and upsert MeterProfile records within the tenant.

        Each row is validated through MeterProfileSerializer so the full
        invariant suite is enforced; any failing row is reported individually
        and does not abort the whole batch.
        """
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

        imported = 0
        errors: list[dict] = []
        valid_roles = {choice for choice, _ in MeterProfile.MeterRole.choices}

        for row_num, raw in enumerate(all_rows, start=2):  # row 1 = header
            try:
                serial = (raw.get('device_serial') or '').strip()
                if not serial:
                    raise ValueError('device_serial is required')
                meter_role = (raw.get('meter_role') or '').strip()
                if meter_role not in valid_roles:
                    raise ValueError(
                        f'meter_role "{meter_role}" is not a valid choice'
                    )

                device = Device.objects.filter(
                    tenant=tenant, serial_number=serial,
                ).select_related('site').first()
                if device is None:
                    raise ValueError(
                        f'No device with serial "{serial}" in this tenant'
                    )

                parent_serial = (raw.get('parent_meter_serial') or '').strip()
                parent_meter = None
                if parent_serial:
                    parent_meter = Device.objects.filter(
                        tenant=tenant, serial_number=parent_serial,
                    ).first()
                    if parent_meter is None:
                        raise ValueError(
                            f'parent_meter_serial "{parent_serial}" not found in this tenant'
                        )

                payload: dict = {
                    'meter_role': meter_role,
                    'nmi': (raw.get('nmi') or '').strip() or None,
                    'parent_meter': parent_meter.id if parent_meter else None,
                    'pattern_approval': (raw.get('pattern_approval') or '').strip(),
                    'serial_number_secondary': (raw.get('serial_number_secondary') or '').strip(),
                }
                phases_raw = (raw.get('phases') or '').strip()
                if phases_raw:
                    payload['phases'] = int(phases_raw)
                install_date = (raw.get('install_date') or '').strip()
                if install_date:
                    payload['install_date'] = install_date

                with transaction.atomic():
                    instance = getattr(device, 'meter_profile', None)
                    serializer = MeterProfileSerializer(
                        instance=instance,
                        data=payload,
                        partial=instance is not None,
                        context={'device': device},
                    )
                    serializer.is_valid(raise_exception=True)
                    serializer.save(device=device, tenant=tenant)
                imported += 1

            except serializers.ValidationError as exc:
                errors.append({'row': row_num, 'error': _flatten_error(exc.detail)})
            except Exception as exc:
                errors.append({'row': row_num, 'error': str(exc)})

        return {'imported': imported, 'errors': errors}


def _flatten_error(detail) -> str:
    """Render a DRF ValidationError detail as a single-line string for CSV reports."""
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
