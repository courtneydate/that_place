"""Rules models: Rule, RuleConditionGroup, RuleCondition, RuleAction, RuleAuditLog.

Rules are the automation heart of That Place. A rule evaluates one or more
condition groups against live stream data and fires one or more actions when
the overall condition is met.

RuleStreamIndex (the stream→rule lookup table used during ingestion) lives in
the readings app but holds a FK to rules.Rule once this app is migrated.

Ref: SPEC.md § Feature: Rules Engine, § Data Model
"""
import logging

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

logger = logging.getLogger(__name__)


class Rule(models.Model):
    """An automation rule belonging to a tenant.

    Evaluated whenever a referenced stream receives a new reading, or on a
    staleness schedule. Fires actions on the false→true condition transition
    (respecting optional cooldown and schedule gate).

    current_state tracks the last evaluation result and is used to suppress
    re-firing while the rule remains in a triggered state.

    Ref: SPEC.md § Data Model — Rule
    """

    class ConditionGroupOperator(models.TextChoices):
        AND = 'AND', 'AND — all groups must be true'
        OR = 'OR', 'OR — any group being true triggers the rule'

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='rules',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    cooldown_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Minimum minutes between firings. Null = no cooldown.',
    )
    # Schedule gate — null fields mean "no restriction"
    active_days = ArrayField(
        models.IntegerField(),
        null=True,
        blank=True,
        help_text='Days of week the rule may fire: 0=Mon … 6=Sun. Null = all days.',
    )
    active_from = models.TimeField(
        null=True,
        blank=True,
        help_text='Wall-clock start of the daily active window (tenant timezone).',
    )
    active_to = models.TimeField(
        null=True,
        blank=True,
        help_text='Wall-clock end of the daily active window (tenant timezone).',
    )
    condition_group_operator = models.CharField(
        max_length=3,
        choices=ConditionGroupOperator.choices,
        default=ConditionGroupOperator.AND,
        help_text='How multiple condition groups are combined.',
    )
    # Evaluation state — updated by the evaluation engine, not the API
    current_state = models.BooleanField(
        default=False,
        help_text='True if the rule is currently in a triggered state.',
    )
    last_fired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the rule last transitioned to triggered state.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_rules',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return f'Rule({self.id}): {self.name}'


class RuleConditionGroup(models.Model):
    """A logical group of conditions within a rule.

    Conditions within a group are combined with the group's logical_operator.
    Groups are combined with the parent Rule's condition_group_operator.

    Ref: SPEC.md § Data Model — RuleConditionGroup
    """

    class LogicalOperator(models.TextChoices):
        AND = 'AND', 'AND — all conditions must be true'
        OR = 'OR', 'OR — any condition being true satisfies the group'

    rule = models.ForeignKey(
        Rule,
        on_delete=models.CASCADE,
        related_name='condition_groups',
    )
    logical_operator = models.CharField(
        max_length=3,
        choices=LogicalOperator.choices,
        default=LogicalOperator.AND,
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self) -> str:
        return f'Group({self.id}) on Rule {self.rule_id} [{self.logical_operator}]'


class RuleCondition(models.Model):
    """A single condition within a condition group.

    condition_type='stream': compares the latest stream reading against
      threshold_value using operator.
    condition_type='staleness': true if the stream has not reported within
      staleness_minutes.
    condition_type='feed_channel': compares the latest FeedReading on a
      FeedChannel against threshold_value using operator (numeric only).
    condition_type='reference_value': resolves the current value from a
      ReferenceDataset via the site's TenantDatasetAssignment and compares
      against threshold_value using operator (numeric only).

    Ref: SPEC.md § Data Model — RuleCondition
         SPEC.md § Feature: Feed Providers — Rule integration
         SPEC.md § Feature: Reference Datasets — Rule integration
    """

    class ConditionType(models.TextChoices):
        STREAM = 'stream', 'Stream value comparison'
        STALENESS = 'staleness', 'Stream staleness'
        FEED_CHANNEL = 'feed_channel', 'Feed channel value comparison'
        REFERENCE_VALUE = 'reference_value', 'Reference dataset value comparison'

    group = models.ForeignKey(
        RuleConditionGroup,
        on_delete=models.CASCADE,
        related_name='conditions',
    )
    condition_type = models.CharField(max_length=20, choices=ConditionType.choices)
    # --- stream / staleness fields ---
    stream = models.ForeignKey(
        'readings.Stream',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='rule_conditions',
    )
    # For stream conditions: operator validated against stream.data_type
    # numeric: >, <, >=, <=, ==, !=  |  boolean: ==  |  string: ==, !=
    operator = models.CharField(max_length=10, blank=True)
    threshold_value = models.TextField(null=True, blank=True)
    # For staleness conditions only
    staleness_minutes = models.PositiveIntegerField(null=True, blank=True)
    # --- feed_channel fields ---
    channel = models.ForeignKey(
        'feeds.FeedChannel',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='rule_conditions',
        help_text='FeedChannel to compare against (feed_channel condition type only).',
    )
    # --- reference_value fields ---
    dataset = models.ForeignKey(
        'feeds.ReferenceDataset',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='rule_conditions',
        help_text='ReferenceDataset to resolve value from (reference_value condition type only).',
    )
    value_key = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            'Which value_schema key to compare (reference_value type only). '
            'E.g. "rate_cents_per_kwh".'
        ),
    )
    dimension_overrides = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            'Optional JSONB overrides merged over the site\'s TenantDatasetAssignment '
            'dimension_filter for this condition (reference_value type only).'
        ),
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self) -> str:
        return f'Condition({self.id}) type={self.condition_type}'


class RuleAction(models.Model):
    """An action executed when a rule fires.

    action_type='notify': sends a notification to groups/users via configured channels.
    action_type='command': sends a device command to target_device.

    Ref: SPEC.md § Data Model — RuleAction
    """

    class ActionType(models.TextChoices):
        NOTIFY = 'notify', 'Send notification'
        COMMAND = 'command', 'Send device command'

    rule = models.ForeignKey(
        Rule,
        on_delete=models.CASCADE,
        related_name='actions',
    )
    action_type = models.CharField(max_length=10, choices=ActionType.choices)
    # Notification fields
    notification_channels = ArrayField(
        models.CharField(max_length=20),
        default=list,
        blank=True,
        help_text='Delivery channels: in_app, email, sms, push.',
    )
    group_ids = ArrayField(
        models.IntegerField(),
        default=list,
        blank=True,
        help_text='NotificationGroup PKs to notify.',
    )
    user_ids = ArrayField(
        models.IntegerField(),
        default=list,
        blank=True,
        help_text='TenantUser PKs to notify.',
    )
    message_template = models.TextField(
        blank=True,
        help_text=(
            'Supports variables: {{device_name}}, {{stream_name}}, {{value}}, '
            '{{unit}}, {{triggered_at}}, {{rule_name}}, {{site_name}}.'
        ),
    )
    # Command fields
    target_device = models.ForeignKey(
        'devices.Device',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rule_actions',
    )
    command = models.JSONField(
        null=True,
        blank=True,
        help_text='Command to send: {"name": "command_name", "params": {...}}',
    )

    class Meta:
        ordering = ['id']

    def __str__(self) -> str:
        return f'Action({self.id}) type={self.action_type} on Rule {self.rule_id}'


class RuleAuditLog(models.Model):
    """Immutable audit trail for changes to a rule.

    Created automatically whenever a rule is saved via the API.
    changed_fields records the before and after value of every tracked field.

    Ref: SPEC.md § Feature: Rule Versioning & Audit Trail
         SPEC.md § Key Business Rules — RuleAuditLog entries are immutable
    """

    rule = models.ForeignKey(
        Rule,
        on_delete=models.CASCADE,
        related_name='audit_logs',
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='rule_audit_logs',
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_fields = models.JSONField(
        help_text='Dict of {field: {before, after}} for every tracked field.',
    )

    class Meta:
        ordering = ['-changed_at']

    def __str__(self) -> str:
        return f'AuditLog({self.id}) Rule {self.rule_id} @ {self.changed_at}'
