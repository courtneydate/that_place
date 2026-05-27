"""Views for the rules app.

Rule management endpoints are restricted to Tenant Admins — operators and
view-only users cannot manage rules. The per-user my-notification-prefs
endpoint (Sprint 26) is an exception: any targeted tenant user can manage
their own opt-outs regardless of role.

Ref: SPEC.md § Feature: Rules Engine
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsTenantAdmin, IsViewOnly
from apps.notifications.models import RuleNotificationOptOut

from .models import Rule
from .serializers import RuleAuditLogSerializer, RuleSerializer

logger = logging.getLogger(__name__)

CHANNELS = ('in_app', 'email', 'sms', 'push')


class MyNotificationPrefsSerializer(drf_serializers.Serializer):
    """Per-user, per-rule channel preferences. True = will receive, False = opted out."""

    in_app = drf_serializers.BooleanField()
    email = drf_serializers.BooleanField()
    sms = drf_serializers.BooleanField()
    push = drf_serializers.BooleanField()


def _user_is_rule_target(user, rule) -> bool:
    """Return True if the user is currently a target of any notify action on the rule."""
    tenant_user = getattr(user, 'tenantuser', None)
    if tenant_user is None:
        return False
    for rule_action in rule.actions.all():
        if rule_action.action_type != 'notify':
            continue
        if rule_action.user_ids and tenant_user.pk in rule_action.user_ids:
            return True
        if rule_action.group_ids:
            membership_exists = tenant_user.notification_memberships.filter(
                group_id__in=rule_action.group_ids,
            ).exists()
            if membership_exists:
                return True
    return False


class RuleViewSet(viewsets.GenericViewSet):
    """CRUD for tenant automation rules.

    All operations require Tenant Admin role. Rules are always scoped to the
    requesting user's tenant — cross-tenant access returns 404.

    Ref: SPEC.md § Feature: Rules Engine
    """

    serializer_class = RuleSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get_permissions(self):
        """Open `my_notification_prefs` to any authenticated tenant user."""
        if self.action == 'my_notification_prefs':
            return [IsAuthenticated(), IsViewOnly()]
        return super().get_permissions()

    def get_queryset(self):
        """Return rules scoped to the requesting user's tenant."""
        tenant_user = getattr(self.request.user, 'tenantuser', None)
        if tenant_user is None:
            return Rule.objects.none()
        tenant = tenant_user.tenant
        return (
            Rule.objects
            .filter(tenant=tenant)
            .prefetch_related(
                'condition_groups__conditions__stream',
                'actions',
                'audit_logs__changed_by',
            )
            .select_related('created_by', 'tenant')
        )

    def list(self, request):
        """GET /api/v1/rules/ — list all rules for this tenant."""
        serializer = RuleSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def create(self, request):
        """POST /api/v1/rules/ — create a new rule. Tenant Admin only."""
        serializer = RuleSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        tenant = request.user.tenantuser.tenant
        serializer.save(tenant=tenant, created_by=request.user)
        logger.info('Rule "%s" created by %s', serializer.data['name'], request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        """GET /api/v1/rules/:id/ — retrieve a single rule with full detail."""
        rule = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(RuleSerializer(rule).data)

    def update(self, request, pk=None):
        """PUT /api/v1/rules/:id/ — replace a rule's config. Tenant Admin only."""
        rule = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = RuleSerializer(
            rule,
            data=request.data,
            partial=False,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Rule "%s" updated by %s', rule.name, request.user.email)
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        """PATCH /api/v1/rules/:id/ — partial update (e.g. toggle is_active)."""
        rule = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = RuleSerializer(
            rule,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Rule "%s" partially updated by %s', rule.name, request.user.email)
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/rules/:id/ — delete a rule. Tenant Admin only."""
        rule = get_object_or_404(self.get_queryset(), pk=pk)
        name = rule.name
        rule.delete()  # Cascades to groups, conditions, actions, audit logs, index entries
        logger.info('Rule "%s" deleted by %s', name, request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'], url_path='audit-logs')
    def audit_logs(self, request, pk=None):
        """GET /api/v1/rules/:id/audit-logs/ — full audit trail for a rule."""
        rule = get_object_or_404(self.get_queryset(), pk=pk)
        logs = rule.audit_logs.select_related('changed_by').all()
        return Response(RuleAuditLogSerializer(logs, many=True).data)

    @action(detail=True, methods=['get', 'put'], url_path='my-notification-prefs')
    def my_notification_prefs(self, request, pk=None):
        """GET/PUT the requesting user's per-channel opt-outs for this rule.

        Body is `{in_app, email, sms, push}` with True = will receive, False =
        opted out. The opt-out stacks with the user's global per-channel
        preferences and snooze — most-restrictive wins at notification time.

        Returns 403 if the user is not currently a target of any notify action
        on the rule (no one to suppress notifications for).

        Ref: SPEC.md §8 Phase 5b; ROADMAP Sprint 26
        """
        rule = get_object_or_404(self.get_queryset(), pk=pk)
        if not _user_is_rule_target(request.user, rule):
            return Response(
                {'error': {'code': 'not_targeted',
                           'message': 'You are not a target of this rule.'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'GET':
            return Response(_get_my_prefs(request.user, rule))

        serializer = MyNotificationPrefsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _set_my_prefs(request.user, rule, serializer.validated_data)
        logger.info(
            'Rule %d notification prefs updated by %s: %s',
            rule.pk, request.user.email, serializer.validated_data,
        )
        return Response(_get_my_prefs(request.user, rule))


def _get_my_prefs(user, rule) -> dict:
    """Return {channel: True if not opted-out, else False} for this user + rule."""
    opted_out = set(
        RuleNotificationOptOut.objects
        .filter(user=user, rule=rule)
        .values_list('channel', flat=True)
    )
    return {channel: channel not in opted_out for channel in CHANNELS}


def _set_my_prefs(user, rule, prefs: dict) -> None:
    """Reconcile RuleNotificationOptOut rows for this user + rule to match prefs."""
    desired_opt_out = {channel for channel in CHANNELS if not prefs[channel]}
    current_opt_out = set(
        RuleNotificationOptOut.objects
        .filter(user=user, rule=rule)
        .values_list('channel', flat=True)
    )
    to_create = desired_opt_out - current_opt_out
    to_delete = current_opt_out - desired_opt_out
    if to_create:
        RuleNotificationOptOut.objects.bulk_create([
            RuleNotificationOptOut(user=user, rule=rule, channel=c) for c in to_create
        ])
    if to_delete:
        RuleNotificationOptOut.objects.filter(
            user=user, rule=rule, channel__in=to_delete,
        ).delete()
