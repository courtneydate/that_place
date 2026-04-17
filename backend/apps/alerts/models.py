"""Alert models for That Place.

An Alert is created each time a Rule fires (false→true transition). Its status
progresses one-way: active → acknowledged → resolved.

Ref: SPEC.md § Feature: Alerts
     SPEC.md § Data Model — Alert
"""
from django.conf import settings
from django.db import models


class Alert(models.Model):
    """Represents a single firing of a Rule.

    Created atomically with the Rule.current_state update in the evaluate_rule
    Celery task. Status transitions are one-directional and enforced by the
    acknowledge/resolve API actions.

    Ref: SPEC.md § Feature: Alerts
    """

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        RESOLVED = 'resolved', 'Resolved'

    rule = models.ForeignKey(
        'rules.Rule',
        on_delete=models.CASCADE,
        related_name='alerts',
    )
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='alerts',
    )
    triggered_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='acknowledged_alerts',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_note = models.TextField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='resolved_alerts',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-triggered_at']

    def __str__(self) -> str:
        """Return a human-readable description of the alert."""
        return f'Alert({self.pk}) rule={self.rule_id} status={self.status}'
