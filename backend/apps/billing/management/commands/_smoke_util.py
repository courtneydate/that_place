"""Shared helpers for the Phase B smoke-check management commands.

The leading underscore keeps Django's command loader from treating this as a
runnable command — it is a helper module imported by ``smoke_b1`` / ``smoke_b2``.

Design goals:
  * Repeatable — every scenario runs inside a savepoint that is always rolled
    back, so re-running the command never accumulates data or hits unique-slug
    collisions. Nothing is persisted to the dev database.
  * Honest — each assertion is recorded as PASS / FAIL / SKIP with a short
    detail. An unexpected exception inside a scenario is caught and reported as
    a FAIL rather than aborting the whole run.
  * Faithful — scenarios exercise the real engine, tasks, serializers, and API
    endpoints (via DRF's in-process APIClient), not reimplementations.

Ref: ROADMAP Phase B1 / B2 sign-off checklists.
"""
from __future__ import annotations

import traceback
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import Stream

User = get_user_model()


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------

class Reporter:
    """Collects PASS / FAIL / SKIP results and prints them as they happen."""

    def __init__(self, stdout, style):
        self._stdout = stdout
        self._style = style
        self.rows: list[tuple[str, str, str]] = []

    def _emit(self, status: str, name: str, detail: str) -> None:
        self.rows.append((status, name, detail))
        colour = {
            'PASS': self._style.SUCCESS,
            'FAIL': self._style.ERROR,
            'SKIP': self._style.WARNING,
        }[status]
        line = f'  {colour(status.ljust(4))}  {name}'
        if detail:
            line += f'  — {detail}'
        self._stdout.write(line)

    def check(self, name: str, condition: bool, detail: str = '') -> bool:
        """Record PASS if condition is truthy, else FAIL."""
        self._emit('PASS' if condition else 'FAIL', name, detail)
        return bool(condition)

    def skip(self, name: str, detail: str = '') -> None:
        self._emit('SKIP', name, detail)

    def section(self, title: str) -> None:
        self._stdout.write('')
        self._stdout.write(self._style.MIGRATE_HEADING(title))

    @property
    def fail_count(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == 'FAIL')

    def summarize(self) -> None:
        passed = sum(1 for s, _, _ in self.rows if s == 'PASS')
        failed = self.fail_count
        skipped = sum(1 for s, _, _ in self.rows if s == 'SKIP')
        self._stdout.write('')
        summary = f'{passed} passed, {failed} failed, {skipped} skipped'
        style = self._style.ERROR if failed else self._style.SUCCESS
        self._stdout.write(style(summary))


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def disable_mqtt_provisioning() -> None:
    """Disconnect the Device post_save MQTT-provisioning signal.

    Device creation would otherwise call out to the Mosquitto broker to
    provision per-device credentials — a side effect that does NOT roll back
    with the savepoint and would accumulate runtime clients on every run.
    Disconnecting affects only this ephemeral process, never the live services.
    """
    from django.db.models.signals import post_save

    from apps.devices.models import Device
    from apps.devices.signals import handle_device_status_change

    post_save.disconnect(handle_device_status_change, sender=Device)


@contextmanager
def scenario(reporter: Reporter, label: str):
    """Run a scenario body in a savepoint that is always rolled back.

    Requires an ambient transaction (the command wraps everything in one).
    Any unexpected exception is caught and reported as a FAIL so remaining
    scenarios still run.
    """
    reporter.section(label)
    sid = transaction.savepoint()
    try:
        yield
    except Exception:  # noqa: BLE001 — surface as a FAIL, keep going
        last = traceback.format_exc().strip().splitlines()[-1]
        reporter.check(f'{label}: no unexpected error', False, last)
    finally:
        transaction.savepoint_rollback(sid)


# ---------------------------------------------------------------------------
# Shared builders (match the patterns in the sprint test suites)
# ---------------------------------------------------------------------------

def make_tenant(name='Smoke Co', tz='Australia/Sydney', **extra) -> Tenant:
    return Tenant.objects.create(
        name=name, slug=slugify(name), timezone=tz, **extra,
    )


def make_admin(tenant, email='smoke-admin@example.test') -> User:
    user = User.objects.create_user(email=email, password='pass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=TenantUser.Role.ADMIN)
    return user


def auth_client(user) -> APIClient:
    client = APIClient()
    resp = client.post(
        '/api/v1/auth/login/',
        {'email': user.email, 'password': 'pass123'},
    )
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_site(tenant, *, hierarchical=False, name='Site A') -> Site:
    return Site.objects.create(
        tenant=tenant, name=name, is_hierarchical=hierarchical,
    )


def make_device(tenant, site, serial, *, dt_slug='smoke-meter') -> Device:
    dt, _ = DeviceType.objects.get_or_create(
        slug=dt_slug,
        defaults={
            'name': 'Smoke Meter', 'connection_type': 'mqtt',
            'is_push': True, 'stream_type_definitions': [], 'commands': [],
        },
    )
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name=f'Dev {serial}', serial_number=serial,
        status=Device.Status.ACTIVE, topic_format='that_place_v1',
    )


def make_stream(device, *, key, billing_role='', unit='kWh', data_type='numeric') -> Stream:
    return Stream.objects.create(
        device=device, key=key, label=key, unit=unit,
        data_type=data_type, billing_role=billing_role,
        aggregation_kind_default=Stream.AggregationKind.SUM,
    )
