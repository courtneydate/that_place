"""Views for the billing app — Sprint 30.

The viewset-level dance with `set_audit_actor` is what lets the signal
handler tag every audit log row with the user that triggered the change —
Django signals don't see request context on their own.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
     ROADMAP.md § Sprint 30
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTenantAdmin, IsViewOnly

from .models import (
    BillingAccount,
    BillingAccountAuditLog,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
)
from .serializers import (
    BillingAccountAuditLogSerializer,
    BillingAccountMeterSerializer,
    BillingAccountSerializer,
    BillingAccountTariffAssignmentSerializer,
    BulkBillingAccountImportSerializer,
)
from .signals import clear_audit_actor, set_audit_actor

logger = logging.getLogger(__name__)


def _tenant(request):
    """Return the request user's tenant, or None for That Place Admins."""
    if request.user.is_that_place_admin:
        return None
    return request.user.tenantuser.tenant


def _resolve_account(request, account_pk):
    """Get a BillingAccount in the request user's tenant, or 404."""
    qs = BillingAccount.objects.select_related('tenant')
    if not request.user.is_that_place_admin:
        qs = qs.filter(tenant=request.user.tenantuser.tenant)
    return get_object_or_404(qs, pk=account_pk)


class BillingAccountViewSet(viewsets.GenericViewSet):
    """CRUD for BillingAccount.

    Tenant Admin write, all tenant roles read. The audit-actor threadlocal
    is set before every mutating call so the signal handler can attribute
    the change correctly.
    """

    serializer_class = BillingAccountSerializer

    def get_permissions(self):
        """Reads available to all tenant users; writes require Tenant Admin."""
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'bulk_import'):
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated(), IsViewOnly()]

    def get_queryset(self):
        if self.request.user.is_that_place_admin:
            return BillingAccount.objects.select_related('tenant', 'parent_account').all()
        tenant = self.request.user.tenantuser.tenant
        return (
            BillingAccount.objects
            .select_related('tenant', 'parent_account')
            .filter(tenant=tenant)
        )

    def list(self, request):
        """GET /api/v1/billing-accounts/."""
        qs = self.get_queryset()
        account_type = request.query_params.get('account_type')
        if account_type:
            qs = qs.filter(account_type=account_type)
        active = request.query_params.get('is_active')
        if active in ('true', 'false'):
            qs = qs.filter(is_active=(active == 'true'))
        return Response(BillingAccountSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        account = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(BillingAccountSerializer(account).data)

    def create(self, request):
        tenant = _tenant(request)
        if tenant is None:
            return Response(
                {'error': {'code': 'tenant_required',
                           'message': 'Use a tenant account to create billing accounts.'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = BillingAccountSerializer(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        set_audit_actor(request.user)
        try:
            serializer.save(tenant=tenant)
        finally:
            clear_audit_actor()
        logger.info('BillingAccount "%s" created by %s', serializer.instance.name, request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        return self._update(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, *, partial: bool):
        account = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = BillingAccountSerializer(
            account, data=request.data, partial=partial, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        set_audit_actor(request.user)
        try:
            serializer.save()
        finally:
            clear_audit_actor()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/billing-accounts/:id/ — soft-style: marks deactivated_at + is_active=False.

        A hard delete would orphan the audit log and any future
        BillingRun/Invoice rows. Deactivation preserves the historical trail
        and matches SPEC.md's "deactivated_at drives a pro-rata final
        invoice" intent.
        """
        from django.utils import timezone
        account = get_object_or_404(self.get_queryset(), pk=pk)
        if not account.is_active and account.deactivated_at:
            return Response(status=status.HTTP_204_NO_CONTENT)
        account.is_active = False
        account.deactivated_at = account.deactivated_at or timezone.now()
        set_audit_actor(request.user)
        try:
            account.save(update_fields=['is_active', 'deactivated_at', 'updated_at'])
        finally:
            clear_audit_actor()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'], url_path='bulk', parser_classes=[parsers.MultiPartParser])
    def bulk_import(self, request):
        """POST /api/v1/billing-accounts/bulk/ — CSV upsert."""
        tenant = _tenant(request)
        if tenant is None:
            return Response(
                {'error': {'code': 'tenant_required',
                           'message': 'Use a tenant account to bulk-import billing accounts.'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = BulkBillingAccountImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_audit_actor(request.user)
        try:
            result = serializer.import_rows(tenant)
        finally:
            clear_audit_actor()
        http_status = status.HTTP_200_OK if result['imported'] > 0 else status.HTTP_400_BAD_REQUEST
        logger.info(
            'BillingAccount bulk import by %s: imported=%s errors=%s',
            request.user.email, result['imported'], len(result['errors']),
        )
        return Response(result, status=http_status)

    @action(detail=True, methods=['get'], url_path='audit-log')
    def audit_log(self, request, pk=None):
        """GET /api/v1/billing-accounts/:id/audit-log/ — append-only history."""
        account = get_object_or_404(self.get_queryset(), pk=pk)
        entries = account.audit_log_entries.select_related('actor_user').all()
        return Response(BillingAccountAuditLogSerializer(entries, many=True).data)


class BillingAccountMeterView(APIView):
    """Nested meter-link endpoints.

    GET    /api/v1/billing-accounts/:account_pk/meters/        — list
    POST   /api/v1/billing-accounts/:account_pk/meters/        — create
    PUT    /api/v1/billing-accounts/:account_pk/meters/:pk/    — replace
    PATCH  /api/v1/billing-accounts/:account_pk/meters/:pk/    — partial
    DELETE /api/v1/billing-accounts/:account_pk/meters/:pk/    — remove
    """

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD'):
            return [IsAuthenticated(), IsViewOnly()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def get(self, request, account_pk, pk=None):
        account = _resolve_account(request, account_pk)
        if pk is None:
            qs = account.meter_links.select_related('stream', 'stream__device').all()
            return Response(BillingAccountMeterSerializer(qs, many=True).data)
        link = get_object_or_404(account.meter_links, pk=pk)
        return Response(BillingAccountMeterSerializer(link).data)

    def post(self, request, account_pk):
        account = _resolve_account(request, account_pk)
        serializer = BillingAccountMeterSerializer(
            data=request.data, context={'billing_account': account},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(billing_account=account)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def put(self, request, account_pk, pk):
        return self._update(request, account_pk, pk, partial=False)

    def patch(self, request, account_pk, pk):
        return self._update(request, account_pk, pk, partial=True)

    def _update(self, request, account_pk, pk, *, partial: bool):
        account = _resolve_account(request, account_pk)
        link = get_object_or_404(account.meter_links, pk=pk)
        serializer = BillingAccountMeterSerializer(
            link, data=request.data, partial=partial,
            context={'billing_account': account},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, account_pk, pk):
        account = _resolve_account(request, account_pk)
        link = get_object_or_404(account.meter_links, pk=pk)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BillingAccountTariffAssignmentView(APIView):
    """Nested tariff assignment endpoints — same shape as meter view."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD'):
            return [IsAuthenticated(), IsViewOnly()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def get(self, request, account_pk, pk=None):
        account = _resolve_account(request, account_pk)
        if pk is None:
            qs = account.tariff_assignments.select_related('dataset', 'stream').all()
            return Response(BillingAccountTariffAssignmentSerializer(qs, many=True).data)
        assignment = get_object_or_404(account.tariff_assignments, pk=pk)
        return Response(BillingAccountTariffAssignmentSerializer(assignment).data)

    def post(self, request, account_pk):
        account = _resolve_account(request, account_pk)
        serializer = BillingAccountTariffAssignmentSerializer(
            data=request.data, context={'billing_account': account},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(billing_account=account)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def put(self, request, account_pk, pk):
        return self._update(request, account_pk, pk, partial=False)

    def patch(self, request, account_pk, pk):
        return self._update(request, account_pk, pk, partial=True)

    def _update(self, request, account_pk, pk, *, partial: bool):
        account = _resolve_account(request, account_pk)
        assignment = get_object_or_404(account.tariff_assignments, pk=pk)
        serializer = BillingAccountTariffAssignmentSerializer(
            assignment, data=request.data, partial=partial,
            context={'billing_account': account},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, account_pk, pk):
        account = _resolve_account(request, account_pk)
        assignment = get_object_or_404(account.tariff_assignments, pk=pk)
        assignment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# Lint silences: BillingAccountMeter / BillingAccountAuditLog /
# BillingAccountTariffAssignment imports document the module surface but
# are only referenced via the queryset traversals above.
_ = BillingAccountMeter
_ = BillingAccountAuditLog
_ = BillingAccountTariffAssignment
