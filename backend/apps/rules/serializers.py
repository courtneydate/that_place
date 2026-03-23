"""Serializers for the rules app.

RuleSerializer supports fully nested create and update:
  - POST /api/v1/rules/ — creates rule + groups + conditions + actions in one
    request; rebuilds RuleStreamIndex and writes audit log entry.
  - PUT /api/v1/rules/:id/ — replaces groups/conditions/actions wholesale;
    rebuilds RuleStreamIndex and writes audit log entry.

Ref: SPEC.md § Feature: Rules Engine, § Feature: Rule Versioning & Audit Trail
"""
import logging

from rest_framework import serializers

from apps.readings.models import RuleStreamIndex, Stream

from .models import Rule, RuleAction, RuleAuditLog, RuleCondition, RuleConditionGroup

logger = logging.getLogger(__name__)

NUMERIC_OPERATORS = {'>', '<', '>=', '<=', '==', '!='}
BOOLEAN_OPERATORS = {'=='}
STRING_OPERATORS = {'==', '!='}

VALID_OPERATORS = {
    Stream.DataType.NUMERIC: NUMERIC_OPERATORS,
    Stream.DataType.BOOLEAN: BOOLEAN_OPERATORS,
    Stream.DataType.STRING: STRING_OPERATORS,
}

VALID_CHANNELS = {'in_app', 'email', 'sms', 'push'}


class RuleConditionSerializer(serializers.ModelSerializer):
    """Serializer for a single condition within a condition group."""

    stream = serializers.PrimaryKeyRelatedField(
        queryset=Stream.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = RuleCondition
        fields = [
            'id', 'condition_type', 'stream', 'operator',
            'threshold_value', 'staleness_minutes', 'order',
        ]

    def validate(self, attrs):
        """Cross-field validation for stream vs staleness conditions."""
        condition_type = attrs.get('condition_type')
        stream = attrs.get('stream')
        operator = attrs.get('operator', '')
        threshold_value = attrs.get('threshold_value')
        staleness_minutes = attrs.get('staleness_minutes')

        if condition_type == RuleCondition.ConditionType.STREAM:
            if not stream:
                raise serializers.ValidationError(
                    {'stream': 'A stream condition requires a stream.'}
                )
            if not operator:
                raise serializers.ValidationError(
                    {'operator': 'A stream condition requires an operator.'}
                )
            allowed = VALID_OPERATORS.get(stream.data_type, set())
            if operator not in allowed:
                raise serializers.ValidationError(
                    {
                        'operator': (
                            f"Operator '{operator}' is not valid for stream data_type "
                            f"'{stream.data_type}'. Allowed: {sorted(allowed)}."
                        )
                    }
                )
            if threshold_value is None:
                raise serializers.ValidationError(
                    {'threshold_value': 'A stream condition requires a threshold_value.'}
                )

        elif condition_type == RuleCondition.ConditionType.STALENESS:
            if not staleness_minutes:
                raise serializers.ValidationError(
                    {'staleness_minutes': 'A staleness condition requires staleness_minutes.'}
                )
            if not stream:
                raise serializers.ValidationError(
                    {'stream': 'A staleness condition requires a stream to monitor.'}
                )

        return attrs


class RuleConditionGroupSerializer(serializers.ModelSerializer):
    """Serializer for a condition group, with its conditions nested inline."""

    conditions = RuleConditionSerializer(many=True)

    class Meta:
        model = RuleConditionGroup
        fields = ['id', 'logical_operator', 'order', 'conditions']


class RuleActionSerializer(serializers.ModelSerializer):
    """Serializer for a rule action (notify or send command)."""

    notification_channels = serializers.ListField(
        child=serializers.CharField(max_length=20),
        default=list,
        required=False,
    )
    group_ids = serializers.ListField(
        child=serializers.IntegerField(),
        default=list,
        required=False,
    )
    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        default=list,
        required=False,
    )

    class Meta:
        model = RuleAction
        fields = [
            'id', 'action_type', 'notification_channels', 'group_ids',
            'user_ids', 'message_template', 'target_device', 'command',
        ]

    def validate_notification_channels(self, value):
        """Ensure all channel values are valid."""
        invalid = set(value) - VALID_CHANNELS
        if invalid:
            raise serializers.ValidationError(
                f"Invalid channels: {sorted(invalid)}. Valid: {sorted(VALID_CHANNELS)}."
            )
        return value

    def validate(self, attrs):
        """Cross-field validation for action_type."""
        action_type = attrs.get('action_type')
        if action_type == RuleAction.ActionType.COMMAND:
            if not attrs.get('target_device'):
                raise serializers.ValidationError(
                    {'target_device': 'A command action requires a target device.'}
                )
            command = attrs.get('command')
            if not command or not isinstance(command, dict) or 'name' not in command:
                raise serializers.ValidationError(
                    {'command': 'A command action requires command = {"name": ..., "params": {...}}.'}
                )
        return attrs


class RuleAuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for a single audit log entry."""

    changed_by_email = serializers.EmailField(
        source='changed_by.email', read_only=True, default=None
    )

    class Meta:
        model = RuleAuditLog
        fields = ['id', 'changed_by', 'changed_by_email', 'changed_at', 'changed_fields']
        read_only_fields = [
            'id', 'changed_by', 'changed_by_email', 'changed_at', 'changed_fields',
        ]


class RuleSerializer(serializers.ModelSerializer):
    """Full serializer for a Rule, with nested groups, conditions, and actions.

    Supports inline creation and full replacement of nested objects on update.
    Automatically rebuilds RuleStreamIndex and creates a RuleAuditLog entry
    on every create/update.
    """

    condition_groups = RuleConditionGroupSerializer(many=True)
    actions = RuleActionSerializer(many=True)
    audit_logs = RuleAuditLogSerializer(many=True, read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    active_days = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Rule
        fields = [
            'id', 'name', 'description', 'is_active', 'cooldown_minutes',
            'active_days', 'active_from', 'active_to', 'condition_group_operator',
            'current_state', 'last_fired_at', 'created_by', 'created_at', 'updated_at',
            'condition_groups', 'actions', 'audit_logs',
        ]
        read_only_fields = [
            'id', 'current_state', 'last_fired_at',
            'created_by', 'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        """Validate that referenced streams and devices belong to the requesting tenant."""
        request = self.context.get('request')
        if not request:
            return attrs

        tenant = request.user.tenantuser.tenant

        for group_data in attrs.get('condition_groups', []):
            for condition_data in group_data.get('conditions', []):
                stream = condition_data.get('stream')
                if stream and stream.device.site.tenant_id != tenant.id:
                    raise serializers.ValidationError(
                        f"Stream {stream.id} does not belong to your tenant."
                    )

        for action_data in attrs.get('actions', []):
            device = action_data.get('target_device')
            if device and device.site.tenant_id != tenant.id:
                raise serializers.ValidationError(
                    f"Device {device.id} does not belong to your tenant."
                )

        return attrs

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _create_groups(self, rule: Rule, groups_data: list) -> None:
        """Create RuleConditionGroups and their RuleConditions for a rule."""
        for group_data in groups_data:
            conditions_data = group_data.pop('conditions', [])
            group = RuleConditionGroup.objects.create(rule=rule, **group_data)
            for condition_data in conditions_data:
                RuleCondition.objects.create(group=group, **condition_data)

    def _create_actions(self, rule: Rule, actions_data: list) -> None:
        """Create RuleActions for a rule."""
        for action_data in actions_data:
            RuleAction.objects.create(rule=rule, **action_data)

    def _rebuild_stream_index(self, rule: Rule) -> None:
        """Rebuild RuleStreamIndex entries for this rule from its current conditions."""
        RuleStreamIndex.objects.filter(rule=rule).delete()
        stream_ids = set()
        for group in rule.condition_groups.all():
            for condition in group.conditions.all():
                if condition.stream_id:
                    stream_ids.add(condition.stream_id)
        if stream_ids:
            RuleStreamIndex.objects.bulk_create([
                RuleStreamIndex(rule=rule, stream_id=sid) for sid in stream_ids
            ])

    def _snapshot(self, rule: Rule) -> dict:
        """Return a plain-dict snapshot of rule state for audit log comparison."""
        return {
            'name': rule.name,
            'description': rule.description,
            'is_active': rule.is_active,
            'cooldown_minutes': rule.cooldown_minutes,
            'active_days': rule.active_days,
            'active_from': str(rule.active_from) if rule.active_from else None,
            'active_to': str(rule.active_to) if rule.active_to else None,
            'condition_group_operator': rule.condition_group_operator,
            'condition_groups': [
                {
                    'logical_operator': g.logical_operator,
                    'order': g.order,
                    'conditions': [
                        {
                            'condition_type': c.condition_type,
                            'stream_id': c.stream_id,
                            'operator': c.operator,
                            'threshold_value': c.threshold_value,
                            'staleness_minutes': c.staleness_minutes,
                            'order': c.order,
                        }
                        for c in g.conditions.all()
                    ],
                }
                for g in rule.condition_groups.prefetch_related('conditions').all()
            ],
            'actions': [
                {
                    'action_type': a.action_type,
                    'notification_channels': a.notification_channels,
                    'group_ids': a.group_ids,
                    'user_ids': a.user_ids,
                    'message_template': a.message_template,
                    'target_device_id': a.target_device_id,
                    'command': a.command,
                }
                for a in rule.actions.all()
            ],
        }

    def _write_audit_log(
        self, rule: Rule, changed_by, before: dict | None
    ) -> None:
        """Create a RuleAuditLog entry capturing before/after state."""
        after = self._snapshot(rule)
        changed_fields = {
            field: {
                'before': before.get(field) if before else None,
                'after': val,
            }
            for field, val in after.items()
        }
        RuleAuditLog.objects.create(
            rule=rule,
            changed_by=changed_by,
            changed_fields=changed_fields,
        )

    # -------------------------------------------------------------------------
    # Create / Update
    # -------------------------------------------------------------------------

    def create(self, validated_data: dict) -> Rule:
        """Create a rule with all nested groups, conditions, and actions."""
        groups_data = validated_data.pop('condition_groups', [])
        actions_data = validated_data.pop('actions', [])

        rule = Rule.objects.create(**validated_data)
        self._create_groups(rule, groups_data)
        self._create_actions(rule, actions_data)
        self._rebuild_stream_index(rule)
        self._write_audit_log(rule, changed_by=rule.created_by, before=None)

        logger.info('Rule "%s" (id=%s) created.', rule.name, rule.id)
        return rule

    def update(self, instance: Rule, validated_data: dict) -> Rule:
        """Replace a rule's nested objects and rebuild index + audit log."""
        groups_data = validated_data.pop('condition_groups', [])
        actions_data = validated_data.pop('actions', [])

        before = self._snapshot(instance)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        instance.condition_groups.all().delete()
        self._create_groups(instance, groups_data)
        instance.actions.all().delete()
        self._create_actions(instance, actions_data)

        self._rebuild_stream_index(instance)

        request = self.context.get('request')
        changed_by = request.user if request else None
        self._write_audit_log(instance, changed_by=changed_by, before=before)

        logger.info('Rule "%s" (id=%s) updated.', instance.name, instance.id)
        return instance
