"""Views for the rules app.

All endpoints are restricted to Tenant Admins — operators and view-only users
cannot manage rules.

Ref: SPEC.md § Feature: Rules Engine
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsTenantAdmin

from .models import Rule
from .serializers import RuleAuditLogSerializer, RuleSerializer

logger = logging.getLogger(__name__)


class RuleViewSet(viewsets.GenericViewSet):
    """CRUD for tenant automation rules.

    All operations require Tenant Admin role. Rules are always scoped to the
    requesting user's tenant — cross-tenant access returns 404.

    Ref: SPEC.md § Feature: Rules Engine
    """

    serializer_class = RuleSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get_queryset(self):
        """Return rules scoped to the requesting user's tenant."""
        tenant = self.request.user.tenantuser.tenant
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
