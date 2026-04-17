"""Views for the alerts app.

AlertViewSet provides:
  list    — GET /api/v1/alerts/      ?status=, ?site=, ?rule=
  retrieve — GET /api/v1/alerts/:id/
  acknowledge — POST /api/v1/alerts/:id/acknowledge/
  resolve     — POST /api/v1/alerts/:id/resolve/

List and detail are accessible to all tenant users (ViewOnly+).
Acknowledge and resolve require Operator or Admin role.

Ref: SPEC.md § Feature: Alerts
"""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsOperator, IsViewOnly

from .models import Alert
from .serializers import (
    AlertAcknowledgeSerializer,
    AlertResolveSerializer,
    AlertSerializer,
)

logger = logging.getLogger(__name__)


class AlertViewSet(viewsets.GenericViewSet):
    """Read and state-management endpoints for tenant Alerts.

    All operations are scoped to the requesting user's tenant.
    List/detail: any tenant user (ViewOnly+).
    Acknowledge/resolve: Operator or Admin only.

    Ref: SPEC.md § Feature: Alerts
    """

    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated, IsViewOnly]

    def _get_tenant(self):
        """Resolve the tenant from the requesting user's TenantUser record."""
        return self.request.user.tenantuser.tenant

    def get_queryset(self):
        """Return Alerts scoped to this tenant with all relations prefetched.

        Prefetches rule → condition_groups → conditions → stream → device → site
        so that AlertSerializer.get_site_names() and get_device_names() do not
        trigger N+1 queries.
        """
        return (
            Alert.objects
            .filter(tenant=self._get_tenant())
            .select_related(
                'rule',
                'acknowledged_by',
                'resolved_by',
            )
            .prefetch_related(
                'rule__condition_groups__conditions__stream__device__site',
            )
            .order_by('-triggered_at')
        )

    def list(self, request):
        """GET /api/v1/alerts/ — list alerts for this tenant.

        Query parameters:
          status  — filter by alert status (active/acknowledged/resolved)
          site    — filter by site ID (any alert whose rule references that site)
          rule    — filter by rule ID
        """
        qs = self.get_queryset()

        if status_filter := request.query_params.get('status'):
            qs = qs.filter(status=status_filter)

        if rule_id := request.query_params.get('rule'):
            qs = qs.filter(rule_id=rule_id)

        if site_id := request.query_params.get('site'):
            # Filter to alerts whose rule references at least one stream
            # on a device at the given site.
            from apps.rules.models import RuleCondition
            rule_ids = (
                RuleCondition.objects
                .filter(stream__device__site_id=site_id)
                .values_list('group__rule_id', flat=True)
                .distinct()
            )
            qs = qs.filter(rule_id__in=rule_ids)

        serializer = AlertSerializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/alerts/:id/ — retrieve a single alert."""
        alert = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(AlertSerializer(alert).data)

    @action(
        detail=True,
        methods=['post'],
        url_path='acknowledge',
        permission_classes=[IsAuthenticated, IsOperator],
    )
    def acknowledge(self, request, pk=None):
        """POST /api/v1/alerts/:id/acknowledge/ — acknowledge an active alert.

        Moves the alert from active → acknowledged. Accepts an optional
        free-text troubleshooting note. Idempotent if already acknowledged.

        Ref: SPEC.md § Feature: Alerts — acknowledge action
        """
        alert = get_object_or_404(self.get_queryset(), pk=pk)

        if alert.status != Alert.Status.ACTIVE:
            return Response(
                {'error': {'code': 'invalid_transition', 'message': 'Only active alerts can be acknowledged.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AlertAcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        note = serializer.validated_data.get('note', '') or None

        alert.status = Alert.Status.ACKNOWLEDGED
        alert.acknowledged_by = request.user
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_note = note
        alert.save(update_fields=['status', 'acknowledged_by', 'acknowledged_at', 'acknowledged_note'])

        logger.info(
            'Alert %d acknowledged by %s (rule %d)',
            alert.pk, request.user.email, alert.rule_id,
        )
        return Response(AlertSerializer(alert).data)

    @action(
        detail=True,
        methods=['post'],
        url_path='resolve',
        permission_classes=[IsAuthenticated, IsOperator],
    )
    def resolve(self, request, pk=None):
        """POST /api/v1/alerts/:id/resolve/ — resolve an alert.

        Moves the alert from active or acknowledged → resolved.
        Status transitions are one-directional: cannot re-open a resolved alert.

        Ref: SPEC.md § Feature: Alerts — resolve action
        """
        alert = get_object_or_404(self.get_queryset(), pk=pk)

        if alert.status == Alert.Status.RESOLVED:
            return Response(
                {'error': {'code': 'invalid_transition', 'message': 'Alert is already resolved.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AlertResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        alert.status = Alert.Status.RESOLVED
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.save(update_fields=['status', 'resolved_by', 'resolved_at'])

        logger.info(
            'Alert %d resolved by %s (rule %d)',
            alert.pk, request.user.email, alert.rule_id,
        )
        return Response(AlertSerializer(alert).data)
