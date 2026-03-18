"""Dashboards app models.

Sprint 11: Dashboard + DashboardWidget

Ref: SPEC.md § Feature: Dashboards & Visualisation
"""
from django.db import models


class Dashboard(models.Model):
    """A configurable dashboard belonging to a tenant.

    Dashboards are shared across all users in the tenant — all roles can view them.
    Tenant Admin and Operator can create, edit, and delete dashboards.
    View-Only users can view but not modify.

    Ref: SPEC.md § Data Model: Dashboard
    """

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='dashboards',
    )
    name = models.CharField(max_length=255)
    columns = models.PositiveSmallIntegerField(
        default=2,
        help_text='Number of columns in the fixed grid layout (1, 2, or 3).',
    )
    created_by = models.ForeignKey(
        'accounts.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_dashboards',
        help_text='User who created the dashboard. Nulled if the user is later deleted.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.tenant.name})'


class DashboardWidget(models.Model):
    """A widget placed on a dashboard canvas.

    Each widget is bound to one or more streams via stream_ids (list of Stream PKs).
    Widget-specific settings are stored in config (JSONB).
    Ordering within the grid is stored in position (JSONB) as {"order": N}.

    Ref: SPEC.md § Data Model: DashboardWidget
    """

    class WidgetType(models.TextChoices):
        VALUE_CARD = 'value_card', 'Value Card'
        LINE_CHART = 'line_chart', 'Line Chart'
        GAUGE = 'gauge', 'Gauge'
        STATUS_INDICATOR = 'status_indicator', 'Status Indicator'
        HEALTH_UPTIME_CHART = 'health_uptime_chart', 'Health / Uptime Chart'

    dashboard = models.ForeignKey(
        Dashboard,
        on_delete=models.CASCADE,
        related_name='widgets',
    )
    widget_type = models.CharField(
        max_length=30,
        choices=WidgetType.choices,
        default=WidgetType.VALUE_CARD,
    )
    stream_ids = models.JSONField(
        default=list,
        blank=True,
        help_text='Array of Stream PKs this widget is bound to.',
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Widget-specific configuration (label override, min/max, thresholds, etc.).',
    )
    position = models.JSONField(
        default=dict,
        blank=True,
        help_text='Position within the dashboard grid. Format: {"order": 0}.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.widget_type} on "{self.dashboard.name}"'
