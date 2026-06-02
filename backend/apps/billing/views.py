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
    BillingLineItem,
    BillingRun,
    BillingRunSnapshot,
    BillingSchedule,
)
from .serializers import (
    BillingAccountAuditLogSerializer,
    BillingAccountMeterSerializer,
    BillingAccountSerializer,
    BillingAccountTariffAssignmentSerializer,
    BillingLineItemSerializer,
    BillingRunCreateSerializer,
    BillingRunSerializer,
    BillingRunSnapshotSerializer,
    BillingScheduleSerializer,
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


# ---------------------------------------------------------------------------
# Sprint 31 — BillingRun + BillingSchedule viewsets
# ---------------------------------------------------------------------------


class BillingRunViewSet(viewsets.GenericViewSet):
    """BillingRun CRUD + dispatch + retry + recompute.

    Tenant Admin only for writes; all tenant roles can list and retrieve.
    Cross-tenant access returns 404.
    """

    def get_permissions(self):
        """Read = any tenant user; write = Tenant Admin."""
        if self.action in ('list', 'retrieve', 'line_items', 'snapshot'):
            return [IsAuthenticated(), IsViewOnly()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def _qs(self, request):
        """Return runs scoped to the requesting user's tenant."""
        qs = BillingRun.objects.select_related('tenant', 'site', 'created_by')
        if not request.user.is_that_place_admin:
            qs = qs.filter(tenant=request.user.tenantuser.tenant)
        return qs

    def list(self, request):
        """GET /api/v1/billing-runs/ — list runs in the tenant."""
        site_id = request.query_params.get('site')
        status_param = request.query_params.get('status')
        qs = self._qs(request)
        if site_id:
            qs = qs.filter(site_id=site_id)
        if status_param:
            qs = qs.filter(status=status_param)
        return Response(BillingRunSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/billing-runs/:id/ — return a single run."""
        run = get_object_or_404(self._qs(request), pk=pk)
        return Response(BillingRunSerializer(run).data)

    def create(self, request):
        """POST /api/v1/billing-runs/ — create + dispatch a run.

        Tenant Admin only. The Celery task dispatches asynchronously and
        acquires the per-(site, period) lock; conflicting dispatches mark
        the run failed rather than 409 here.
        """
        from apps.devices.models import Site

        from .tasks import run_billing_run

        tenant = request.user.tenantuser.tenant
        serializer = BillingRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        site = get_object_or_404(Site, pk=data['site'], tenant=tenant)
        run = BillingRun.objects.create(
            tenant=tenant,
            site=site,
            billing_account_ids=data.get('billing_account_ids') or [],
            period_start=data['period_start'],
            period_end=data['period_end'],
            timezone_snapshot=tenant.timezone or 'Australia/Sydney',
            aggregate_period=data.get('aggregate_period')
            or BillingRun.AggregatePeriod.THIRTY_MIN,
            created_by=request.user,
        )
        run_billing_run.delay(run.id)
        logger.info(
            'BillingRun %d dispatched by %s for site %d (%s → %s)',
            run.id, request.user.email, site.id,
            run.period_start, run.period_end,
        )
        return Response(
            BillingRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """POST /api/v1/billing-runs/:id/retry/ — re-dispatch a failed run.

        Refuses unless status=failed. Resumes from `failed_step`.
        """
        from .tasks import retry_billing_run

        run = get_object_or_404(self._qs(request), pk=pk)
        if run.status != BillingRun.Status.FAILED:
            return Response(
                {
                    'error': {
                        'code': 'invalid_status',
                        'message': f'Only failed runs can be retried (current: {run.status}).',
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        retry_billing_run.delay(run.id)
        return Response(BillingRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def recompute(self, request, pk=None):
        """POST /api/v1/billing-runs/:id/recompute/ — rebuild a draft run.

        Refuses unless status=draft. Restarts the pipeline from
        `resolve_scope`; existing snapshot + line items are deleted at the
        start of each step.
        """
        from .tasks import run_billing_run

        run = get_object_or_404(self._qs(request), pk=pk)
        if run.status != BillingRun.Status.DRAFT:
            return Response(
                {
                    'error': {
                        'code': 'invalid_status',
                        'message': f'Only draft runs can be recomputed (current: {run.status}).',
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        run.status = BillingRun.Status.QUEUED
        run.failed_step = None
        run.failure_detail = ''
        run.save(update_fields=['status', 'failed_step', 'failure_detail'])
        run_billing_run.delay(run.id)
        return Response(BillingRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='line-items')
    def line_items(self, request, pk=None):
        """GET /api/v1/billing-runs/:id/line-items/ — list this run's line items."""
        run = get_object_or_404(self._qs(request), pk=pk)
        items = (
            BillingLineItem.objects
            .filter(billing_run=run)
            .select_related('billing_account', 'stream')
        )
        return Response(BillingLineItemSerializer(items, many=True).data)

    @action(detail=True, methods=['get'])
    def snapshot(self, request, pk=None):
        """GET /api/v1/billing-runs/:id/snapshot/ — list this run's snapshots."""
        run = get_object_or_404(self._qs(request), pk=pk)
        snaps = (
            BillingRunSnapshot.objects
            .filter(billing_run=run)
            .select_related('billing_account', 'stream')
        )
        return Response(BillingRunSnapshotSerializer(snaps, many=True).data)


class BillingScheduleViewSet(viewsets.GenericViewSet):
    """CRUD for BillingSchedule.

    Tenant Admin only.
    """

    def get_permissions(self):
        return [IsAuthenticated(), IsTenantAdmin()]

    def _qs(self, request):
        qs = BillingSchedule.objects.select_related('tenant', 'site')
        if not request.user.is_that_place_admin:
            qs = qs.filter(tenant=request.user.tenantuser.tenant)
        return qs

    def list(self, request):
        """GET /api/v1/billing-schedules/ — list schedules for the tenant."""
        return Response(BillingScheduleSerializer(self._qs(request), many=True).data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/billing-schedules/:id/ — return a single schedule."""
        sched = get_object_or_404(self._qs(request), pk=pk)
        return Response(BillingScheduleSerializer(sched).data)

    def create(self, request):
        """POST /api/v1/billing-schedules/ — create a schedule.

        next_run_at defaults to the next cadence boundary in tenant time.
        """
        from .tasks import _next_run_at

        tenant = request.user.tenantuser.tenant
        serializer = BillingScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sched = serializer.save(tenant=tenant)

        from django.utils import timezone as dj_timezone
        sched.next_run_at = _next_run_at(sched, dj_timezone.now())
        sched.save(update_fields=['next_run_at'])
        return Response(BillingScheduleSerializer(sched).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/billing-schedules/:id/ — update a schedule."""
        sched = get_object_or_404(self._qs(request), pk=pk)
        serializer = BillingScheduleSerializer(sched, data=request.data)
        serializer.is_valid(raise_exception=True)
        sched = serializer.save()
        return Response(BillingScheduleSerializer(sched).data)

    def partial_update(self, request, pk=None):
        """PATCH /api/v1/billing-schedules/:id/ — partial update."""
        sched = get_object_or_404(self._qs(request), pk=pk)
        serializer = BillingScheduleSerializer(sched, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        sched = serializer.save()
        return Response(BillingScheduleSerializer(sched).data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/billing-schedules/:id/ — delete a schedule."""
        sched = get_object_or_404(self._qs(request), pk=pk)
        sched.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# Lint silences: BillingAccountMeter / BillingAccountAuditLog /
# BillingAccountTariffAssignment imports document the module surface but
# are only referenced via the queryset traversals above.
_ = BillingAccountMeter
_ = BillingAccountAuditLog
_ = BillingAccountTariffAssignment
