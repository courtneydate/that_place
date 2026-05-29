"""Signal receivers for the billing app — Sprint 30.

Audit log auto-write. The receivers run inside the same DB transaction as
the originating BillingAccount save / delete, so a rollback of the parent
also rolls back the log entry — no orphaned half-written audit rows.

The actor (`actor_user`) is resolved via threadlocal storage that the views
populate before saving — Django signals don't have request context, so we
plumb it manually. If the threadlocal is empty (e.g. management command,
shell), `actor_user` is left null.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs — Audit
"""
from __future__ import annotations

import threading
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import BillingAccount, BillingAccountAuditLog

User = get_user_model()

# Threadlocal carrying the acting user for the current request — populated
# in BillingAccount views via `set_audit_actor()`, cleared on tear-down.
_audit_context = threading.local()


def set_audit_actor(user) -> None:
    """Mark the user that initiated the current operation."""
    _audit_context.actor = user


def clear_audit_actor() -> None:
    """Clear the actor — call from a finally block in views."""
    _audit_context.actor = None


def _current_actor() -> Optional['User']:
    return getattr(_audit_context, 'actor', None)


AUDITABLE_FIELDS = (
    'name', 'customer_reference', 'contact_email', 'contact_phone',
    'billing_address', 'abn', 'account_type', 'parent_account_id',
    'invoice_email_recipients', 'floor_area_sqm', 'is_active',
    'activated_at', 'deactivated_at',
)


@receiver(pre_save, sender=BillingAccount)
def _capture_pre_save_snapshot(sender, instance: BillingAccount, **kwargs):
    """Stash the pre-save field values on the instance for the post_save diff.

    On create the snapshot is None, signalling the post_save hook to emit a
    `created` log entry rather than an `updated` diff.
    """
    if instance.pk is None:
        instance._audit_pre_save = None
        return
    try:
        prior = BillingAccount.objects.get(pk=instance.pk)
    except BillingAccount.DoesNotExist:
        instance._audit_pre_save = None
        return
    instance._audit_pre_save = {f: getattr(prior, f) for f in AUDITABLE_FIELDS}


@receiver(post_save, sender=BillingAccount)
def _write_audit_log(sender, instance: BillingAccount, created: bool, **kwargs):
    """Emit an audit log entry on every BillingAccount save.

    `created` → snapshot of initial values.
    Existing → field diff; if deactivated_at transitioned null→datetime the
    action is `deactivated`, otherwise `updated`. No-op if nothing changed.
    """
    actor = _current_actor()
    pre = getattr(instance, '_audit_pre_save', None)

    if created:
        snapshot = {f: {'after': _serialise(getattr(instance, f))} for f in AUDITABLE_FIELDS}
        BillingAccountAuditLog.objects.create(
            billing_account=instance,
            actor_user=actor,
            action=BillingAccountAuditLog.Action.CREATED,
            changed_fields=snapshot,
        )
        return

    if pre is None:
        return

    diff: dict = {}
    for field in AUDITABLE_FIELDS:
        before = pre.get(field)
        after = getattr(instance, field)
        if before != after:
            diff[field] = {'before': _serialise(before), 'after': _serialise(after)}

    if not diff:
        return

    action = BillingAccountAuditLog.Action.UPDATED
    if 'deactivated_at' in diff and pre.get('deactivated_at') is None and instance.deactivated_at is not None:
        action = BillingAccountAuditLog.Action.DEACTIVATED

    BillingAccountAuditLog.objects.create(
        billing_account=instance,
        actor_user=actor,
        action=action,
        changed_fields=diff,
    )


def _serialise(value):
    """Render a field value as something JSON-safe for storage in changed_fields."""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return str(value)
