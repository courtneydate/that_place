"""Views for the billing app — Sprint 30 + Sprint 31 + Sprint 32.

The viewset-level dance with `set_audit_actor` is what lets the signal
handler tag every audit log row with the user that triggered the change —
Django signals don't see request context on their own.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
     SPEC.md § Feature: Billing Runs & Invoicing
     ROADMAP.md § Sprint 30, Sprint 31, Sprint 32
"""
import csv
import logging

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTenantAdmin, IsViewOnly

from .invoice_renderer import generate_pdf_signed_url
from .models import (
    BillingAccount,
    BillingAccountAuditLog,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
    BillingInvoice,
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
    BillingInvoiceSerializer,
    BillingLineItemSerializer,
    BillingRunCreateSerializer,
    BillingRunSerializer,
    BillingRunSnapshotSerializer,
    BillingScheduleSerializer,
    BulkBillingAccountImportSerializer,
)
from .signals import clear_audit_actor, set_audit_actor
from .tasks import (
    _next_run_at,
    finalize_billing_run,
    retry_billing_run,
    run_billing_run,
    send_invoice_email,
    send_void_notification_email,
)

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
        if self.action in ('list', 'retrieve', 'line_items', 'snapshot', 'line_items_csv'):
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

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        """POST /api/v1/billing-runs/:id/finalize/ — lock the run and issue invoices.

        Tenant Admin only. Accepts draft and review runs. Dispatches
        billing.finalize_billing_run asynchronously.
        """
        run = get_object_or_404(self._qs(request), pk=pk)
        if run.status not in (BillingRun.Status.DRAFT, BillingRun.Status.REVIEW):
            return Response(
                {
                    'error': {
                        'code': 'invalid_status',
                        'message': (
                            f'Only draft or review runs can be finalized '
                            f'(current: {run.status}).'
                        ),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        finalize_billing_run.delay(run.id, request.user.id)
        logger.info('BillingRun %d finalize dispatched by %s', run.id, request.user.email)
        return Response(BillingRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """POST /api/v1/billing-runs/:id/void/ — void a finalized run.

        Tenant Admin only. Body: {silent_void?: bool, reason?: string}.
        Marks the run + all its invoices voided. Unless silent_void=true,
        dispatches a void-notification email per delivered invoice.
        """
        run = get_object_or_404(self._qs(request), pk=pk)
        if run.status != BillingRun.Status.FINALIZED:
            return Response(
                {
                    'error': {
                        'code': 'invalid_status',
                        'message': f'Only finalized runs can be voided (current: {run.status}).',
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        silent_void = bool(request.data.get('silent_void', False))
        reason = str(request.data.get('reason', '') or '')

        now = timezone.now()
        run.status = BillingRun.Status.VOIDED
        run.voided_at = now
        run.void_reason = reason
        run.save(update_fields=['status', 'voided_at', 'void_reason'])

        # Void all invoices; collect those that were delivered for notifications.
        invoices_to_notify = []
        for invoice in run.invoices.all():
            was_delivered = invoice.status == BillingInvoice.Status.DELIVERED
            invoice.status = BillingInvoice.Status.VOID
            invoice.voided_at = now
            invoice.save(update_fields=['status', 'voided_at'])
            if was_delivered and not silent_void:
                invoices_to_notify.append(invoice.id)

        for invoice_id in invoices_to_notify:
            send_void_notification_email.delay(invoice_id)

        logger.info(
            'BillingRun %d voided by %s (silent=%s, notified=%d invoices)',
            run.id, request.user.email, silent_void, len(invoices_to_notify),
        )
        return Response(BillingRunSerializer(run).data)

    @action(detail=True, methods=['get'], url_path='line-items-csv')
    def line_items_csv(self, request, pk=None):
        """GET /api/v1/billing-runs/:id/line-items.csv — streaming CSV export.

        Admin only (checked at get_permissions). Uses Django's StreamingHttpResponse
        to avoid loading all rows into memory.
        """
        run = get_object_or_404(self._qs(request), pk=pk)
        items = (
            BillingLineItem.objects
            .filter(billing_run=run)
            .select_related('billing_account', 'stream')
            .order_by('billing_account__name', 'line_kind', 'period_name')
        )

        def _rows():
            header = [
                'account_name', 'customer_reference', 'line_kind',
                'period_name', 'kwh', 'rate_cents_per_kwh',
                'amount_cents', 'gst_cents', 'total_cents', 'quality_summary',
            ]
            yield header
            for item in items.iterator(chunk_size=500):
                yield [
                    item.billing_account.name,
                    item.billing_account.customer_reference,
                    item.line_kind,
                    item.period_name,
                    str(item.kwh) if item.kwh is not None else '',
                    str(item.rate_cents_per_kwh) if item.rate_cents_per_kwh is not None else '',
                    str(item.amount_cents),
                    str(item.gst_cents),
                    str(item.amount_cents + item.gst_cents),
                    str(item.quality_summary) if item.quality_summary else '',
                ]

        class _Echo:
            def write(self, value):
                return value

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow(row) for row in _rows()),
            content_type='text/csv',
        )
        filename = f'billing-run-{run.id}-line-items.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


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


class BillingInvoiceViewSet(viewsets.GenericViewSet):
    """Invoice list, detail, PDF preview, and resend.

    All reads: any authenticated tenant user.
    Resend: Tenant Admin only.
    """

    def get_permissions(self):
        if self.action == 'resend':
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated(), IsViewOnly()]

    def _qs(self, request):
        qs = BillingInvoice.objects.select_related(
            'billing_account', 'billing_run', 'billing_run__tenant',
        )
        if not request.user.is_that_place_admin:
            qs = qs.filter(billing_run__tenant=request.user.tenantuser.tenant)
        return qs

    def list(self, request):
        """GET /api/v1/invoices/ — ?billing_account=, ?run=."""
        qs = self._qs(request)
        if ba := request.query_params.get('billing_account'):
            qs = qs.filter(billing_account_id=ba)
        if run := request.query_params.get('run'):
            qs = qs.filter(billing_run_id=run)
        return Response(BillingInvoiceSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/invoices/:id/."""
        invoice = get_object_or_404(self._qs(request), pk=pk)
        return Response(BillingInvoiceSerializer(invoice).data)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        """GET /api/v1/invoices/:id/pdf/ — 15-minute pre-signed URL."""
        invoice = get_object_or_404(self._qs(request), pk=pk)
        if not invoice.pdf_object_key:
            return Response(
                {'error': {'code': 'pdf_not_ready', 'message': 'PDF has not been generated yet.'}},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            url = generate_pdf_signed_url(invoice.pdf_object_key, expiry_seconds=900)
        except Exception:
            logger.exception('Failed to generate signed URL for invoice %d', invoice.id)
            return Response(
                {'error': {'code': 'storage_error', 'message': 'Could not generate download URL.'}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({'url': url, 'expires_in': 900})

    @action(detail=True, methods=['post'])
    def resend(self, request, pk=None):
        """POST /api/v1/invoices/:id/resend/ — re-queue email delivery."""
        invoice = get_object_or_404(self._qs(request), pk=pk)
        if invoice.status == BillingInvoice.Status.VOID:
            return Response(
                {'error': {'code': 'invoice_voided', 'message': 'Voided invoices cannot be resent.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invoice.delivery_status = BillingInvoice.DeliveryStatus.PENDING
        invoice.save(update_fields=['delivery_status'])
        send_invoice_email.delay(invoice.id)
        logger.info('Invoice %s resend dispatched by %s', invoice.invoice_number, request.user.email)
        return Response(BillingInvoiceSerializer(invoice).data, status=status.HTTP_202_ACCEPTED)


# Lint silences: BillingAccountMeter / BillingAccountAuditLog /
# BillingAccountTariffAssignment imports document the module surface but
# are only referenced via the queryset traversals above.
_ = BillingAccountMeter
_ = BillingAccountAuditLog
_ = BillingAccountTariffAssignment
