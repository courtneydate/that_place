"""Views for the feeds app.

FeedProviderViewSet        — That Place Admin CRUD; Tenant Admin list/retrieve.
FeedChannelViewSet         — read-only; nested under providers.
FeedReadingViewSet         — read-only; nested under channels.
TenantFeedSubscriptionViewSet — Tenant Admin CRUD for scope=tenant providers.
ReferenceDatasetViewSet    — That Place Admin CRUD; Tenant Admin list/retrieve.
ReferenceDatasetRowViewSet — That Place Admin CRUD + bulk import + CSV export.
TenantDatasetAssignmentViewSet — Tenant Admin CRUD + resolve action.

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets,
     § Key Endpoints (MVP)
     security_risks.md § SR-04 — CSV Bulk Import Injection and Resource Exhaustion
"""
import csv
import io
import logging

from django.http import HttpResponse
from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsTenantAdmin, IsThatPlaceAdmin

from .models import (
    FeedChannel,
    FeedProvider,
    ReferenceDataset,
    ReferenceDatasetRow,
    TenantDatasetAssignment,
    TenantFeedSubscription,
)
from .resolution import ResolutionError, resolve_dataset_assignment
from .serializers import (
    BulkRowImportSerializer,
    FeedChannelSerializer,
    FeedProviderAdminSerializer,
    FeedProviderPublicSerializer,
    FeedReadingSerializer,
    ReferenceDatasetAdminSerializer,
    ReferenceDatasetPublicSerializer,
    ReferenceDatasetRowSerializer,
    TenantDatasetAssignmentSerializer,
    TenantFeedSubscriptionSerializer,
)

logger = logging.getLogger(__name__)


class FeedProviderViewSet(viewsets.GenericViewSet):
    """Feed provider library.

    That Place Admin: full CRUD with all fields.
    Tenant Admin / authenticated users: list + retrieve (name/description only).

    Ref: SPEC.md § Feature: Feed Providers
    """

    queryset = FeedProvider.objects.all().order_by('name')

    def get_serializer_class(self):
        """Return full serializer for admins, public for everyone else."""
        if self.request.user.is_that_place_admin:
            return FeedProviderAdminSerializer
        return FeedProviderPublicSerializer

    def get_permissions(self):
        """CRUD requires That Place Admin; list/retrieve requires authentication."""
        if self.action in ('list', 'retrieve', 'channels'):
            return [IsAuthenticated()]
        return [IsThatPlaceAdmin()]

    def list(self, request):
        """List all active feed providers."""
        qs = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve a single feed provider."""
        provider = self.get_object()
        serializer = self.get_serializer(provider)
        return Response(serializer.data)

    def create(self, request):
        """Create a new feed provider (That Place Admin only)."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _sync_channels_from_config(provider)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """Update a feed provider (That Place Admin only)."""
        provider = self.get_object()
        serializer = self.get_serializer(provider, data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _sync_channels_from_config(provider)
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        """Partially update a feed provider (That Place Admin only)."""
        provider = self.get_object()
        serializer = self.get_serializer(provider, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _sync_channels_from_config(provider)
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """Delete a feed provider (That Place Admin only)."""
        provider = self.get_object()
        provider.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'], url_path='channels')
    def channels(self, request, pk=None):
        """List all channels for this provider."""
        provider = self.get_object()
        channels = provider.channels.filter(is_active=True).prefetch_related(
            'readings'
        )
        serializer = FeedChannelSerializer(channels, many=True, context={'request': request})
        return Response(serializer.data)


class FeedChannelViewSet(viewsets.GenericViewSet):
    """Feed channel readings — read-only.

    Ref: SPEC.md § Key Endpoints — GET /api/v1/feed-channels/:id/readings/
    """

    queryset = FeedChannel.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]
    serializer_class = FeedChannelSerializer

    def retrieve(self, request, pk=None):
        """Retrieve a single channel with latest reading."""
        channel = self.get_object()
        serializer = self.get_serializer(channel)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='readings')
    def readings(self, request, pk=None):
        """List readings for a channel. Supports ?from=&to=&limit= filtering."""
        channel = self.get_object()
        qs = channel.readings.order_by('-timestamp')

        from_ts = request.query_params.get('from')
        to_ts = request.query_params.get('to')
        limit = request.query_params.get('limit', 100)

        if from_ts:
            qs = qs.filter(timestamp__gte=from_ts)
        if to_ts:
            qs = qs.filter(timestamp__lte=to_ts)
        try:
            qs = qs[:int(limit)]
        except (ValueError, TypeError):
            qs = qs[:100]

        serializer = FeedReadingSerializer(qs, many=True)
        return Response(serializer.data)


class TenantFeedSubscriptionViewSet(viewsets.GenericViewSet):
    """Tenant feed subscriptions for scope=tenant providers.

    Scoped to the requesting tenant — a tenant can only see/manage their own subscriptions.

    Ref: SPEC.md § Feature: Feed Providers — Tenant-scope feeds
    """

    serializer_class = TenantFeedSubscriptionSerializer
    permission_classes = [IsTenantAdmin]

    def get_queryset(self):
        """Return subscriptions for the requesting tenant only."""
        return TenantFeedSubscription.objects.filter(
            tenant=self.request.user.tenantuser.tenant
        ).select_related('provider')

    def list(self, request):
        """List all feed subscriptions for this tenant."""
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve a single subscription."""
        subscription = self.get_object()
        serializer = self.get_serializer(subscription)
        return Response(serializer.data)

    def create(self, request):
        """Subscribe this tenant to a scope=tenant provider."""
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """Update a subscription (e.g. change subscribed channels or credentials)."""
        subscription = self.get_object()
        serializer = self.get_serializer(
            subscription, data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        """Partially update a subscription."""
        subscription = self.get_object()
        serializer = self.get_serializer(
            subscription, data=request.data, partial=True, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """Delete a subscription."""
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReferenceDatasetViewSet(viewsets.GenericViewSet):
    """Reference dataset library.

    That Place Admin: full CRUD.
    Tenant Admin: list + retrieve (schema visible; used to configure assignments).

    Ref: SPEC.md § Feature: Reference Datasets
    """

    queryset = ReferenceDataset.objects.all().order_by('name')

    def get_serializer_class(self):
        """Return full serializer for admins, public for everyone else."""
        if self.request.user.is_that_place_admin:
            return ReferenceDatasetAdminSerializer
        return ReferenceDatasetPublicSerializer

    def get_permissions(self):
        """CRUD requires That Place Admin; list/retrieve requires authentication."""
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsThatPlaceAdmin()]

    def list(self, request):
        """List all active reference datasets."""
        qs = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve a single dataset."""
        dataset = self.get_object()
        serializer = self.get_serializer(dataset)
        return Response(serializer.data)

    def create(self, request):
        """Create a new reference dataset (That Place Admin only)."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """Update a reference dataset (That Place Admin only)."""
        dataset = self.get_object()
        serializer = self.get_serializer(dataset, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """Delete a reference dataset (That Place Admin only)."""
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReferenceDatasetRowViewSet(viewsets.GenericViewSet):
    """Reference dataset row management (That Place Admin only).

    Includes bulk CSV import via POST /rows/bulk/.

    Ref: SPEC.md § Feature: Reference Datasets
    """

    serializer_class = ReferenceDatasetRowSerializer
    permission_classes = [IsThatPlaceAdmin]
    parser_classes = [parsers.MultiPartParser, parsers.JSONParser]

    def _get_dataset(self, dataset_pk):
        """Return the parent dataset or 404."""
        from django.shortcuts import get_object_or_404
        return get_object_or_404(ReferenceDataset, pk=dataset_pk)

    def get_queryset(self):
        """Return rows for the parent dataset."""
        dataset_pk = self.kwargs.get('dataset_pk')
        return ReferenceDatasetRow.objects.filter(dataset_id=dataset_pk).order_by('version', 'id')

    def list(self, request, dataset_pk=None):
        """List rows for a dataset. Supports ?version= filter."""
        qs = self.get_queryset()
        version = request.query_params.get('version')
        if version:
            qs = qs.filter(version=version)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def create(self, request, dataset_pk=None):
        """Create a row for a dataset."""
        dataset = self._get_dataset(dataset_pk)
        data = {**request.data, 'dataset': dataset.pk}
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, dataset_pk=None, pk=None):
        """Update a row."""
        row = self.get_object()
        serializer = self.get_serializer(row, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, dataset_pk=None, pk=None):
        """Partially update a row."""
        row = self.get_object()
        serializer = self.get_serializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, dataset_pk=None, pk=None):
        """Delete a row."""
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=False,
        methods=['post'],
        url_path='bulk',
        parser_classes=[parsers.MultiPartParser],
    )
    def bulk_import(self, request, dataset_pk=None):
        """Bulk upsert rows from a CSV file upload.

        CSV columns: all dimension_schema keys + all value_schema keys +
        optionally: version, applicable_days, time_from, time_to, valid_from, valid_to.

        applicable_days: comma-separated integers (0=Mon…6=Sun).

        Limits: max 10 MB file size, max 50,000 rows.

        Returns: {imported: N, errors: [{row: N, error: "..."}]}
        """
        dataset = self._get_dataset(dataset_pk)
        serializer = BulkRowImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.import_rows(dataset)
        http_status = status.HTTP_200_OK if result['imported'] > 0 else status.HTTP_400_BAD_REQUEST
        return Response(result, status=http_status)

    @action(
        detail=False,
        methods=['get'],
        url_path='export',
    )
    def export_csv(self, request, dataset_pk=None):
        """Export all rows for this dataset as a CSV file.

        Supports ?version= to filter by version.

        Cell values that begin with formula-triggering characters (=, +, -, @)
        are prefixed with a tab character to prevent CSV injection when the
        file is opened in Excel or Google Sheets.

        Ref: security_risks.md § SR-04 — CSV injection mitigation
        """
        from .serializers import sanitize_csv_cell

        dataset = self._get_dataset(dataset_pk)
        dim_keys = list((dataset.dimension_schema or {}).keys())
        val_keys = list((dataset.value_schema or {}).keys())

        qs = self.get_queryset()
        version_filter = request.query_params.get('version')
        if version_filter:
            qs = qs.filter(version=version_filter)

        # Build CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        header = []
        if dataset.has_version:
            header.append('version')
        header += dim_keys + val_keys
        if dataset.has_time_of_use:
            header += ['applicable_days', 'time_from', 'time_to']
        header += ['valid_from', 'valid_to', 'is_active']
        writer.writerow(header)

        # Data rows — sanitise every string cell
        for row in qs:
            cells = []
            if dataset.has_version:
                cells.append(sanitize_csv_cell(row.version or ''))
            for k in dim_keys:
                cells.append(sanitize_csv_cell(str(row.dimensions.get(k, ''))))
            for k in val_keys:
                raw = row.values.get(k, '')
                cells.append(sanitize_csv_cell(str(raw)) if raw is not None else '')
            if dataset.has_time_of_use:
                days = ','.join(str(d) for d in (row.applicable_days or []))
                cells.append(sanitize_csv_cell(days))
                cells.append(str(row.time_from or ''))
                cells.append(str(row.time_to or ''))
            cells.append(str(row.valid_from or ''))
            cells.append(str(row.valid_to or ''))
            cells.append('true' if row.is_active else 'false')
            writer.writerow(cells)

        filename = f'{dataset.slug}-rows.csv'
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TenantDatasetAssignmentViewSet(viewsets.GenericViewSet):
    """Tenant dataset assignments — per site or tenant-wide.

    Scoped to the requesting tenant.

    Ref: SPEC.md § Feature: Reference Datasets — Tenant-level
    """

    serializer_class = TenantDatasetAssignmentSerializer
    permission_classes = [IsTenantAdmin]

    def get_queryset(self):
        """Return assignments for the requesting tenant only."""
        qs = TenantDatasetAssignment.objects.filter(
            tenant=self.request.user.tenantuser.tenant
        ).select_related('dataset', 'site')
        site_id = self.request.query_params.get('site')
        if site_id:
            qs = qs.filter(site_id=site_id)
        return qs

    def list(self, request):
        """List all dataset assignments for this tenant. Supports ?site= filter."""
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve a single assignment."""
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)

    def create(self, request):
        """Create a dataset assignment."""
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """Update a dataset assignment."""
        assignment = self.get_object()
        serializer = self.get_serializer(
            assignment, data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        """Partially update a dataset assignment."""
        assignment = self.get_object()
        serializer = self.get_serializer(
            assignment, data=request.data, partial=True, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """Delete a dataset assignment."""
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'], url_path='resolve')
    def resolve(self, request, pk=None):
        """Preview the currently resolved row values for this assignment.

        Returns the values dict that a rule condition would see right now,
        including TOU resolution in the tenant's timezone.
        """
        assignment = self.get_object()
        try:
            values = resolve_dataset_assignment(assignment)
        except ResolutionError as exc:
            return Response(
                {'error': {'code': 'RESOLUTION_ERROR', 'message': str(exc)}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response({'resolved_values': values})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sync_channels_from_config(provider: FeedProvider) -> None:
    """Create FeedChannel records from the provider's endpoint channel config.

    Called after provider create/update. Existing channels are updated in-place;
    new channels are created. Dimension values are not pre-created here —
    they are discovered and created on the first successful poll.

    Only creates dimensionless channels (dimension_value=None) at this stage.
    Dimensional channels (e.g. one per NEM region) are added by the poller.
    """
    for endpoint in (provider.endpoints or []):
        for ch_def in (endpoint.get('channels') or []):
            FeedChannel.objects.update_or_create(
                provider=provider,
                key=ch_def['key'],
                dimension_value=None,
                defaults={
                    'label': ch_def.get('label', ch_def['key']),
                    'unit': ch_def.get('unit', ''),
                    'data_type': ch_def.get('data_type', FeedChannel.DataType.NUMERIC),
                    'is_active': True,
                },
            )
