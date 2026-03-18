"""Views for the dashboards app.

Ref: SPEC.md § Feature: Dashboards & Visualisation
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsOperator, IsViewOnly

from .models import Dashboard, DashboardWidget
from .serializers import DashboardSerializer, DashboardWidgetSerializer

logger = logging.getLogger(__name__)


class DashboardViewSet(viewsets.GenericViewSet):
    """CRUD for tenant dashboards.

    All tenant users (including View-Only) can list and retrieve dashboards.
    Tenant Admin and Operator can create, update, and delete dashboards.
    Dashboards are always scoped to the requesting user's tenant.

    Ref: SPEC.md § Feature: Dashboards & Visualisation
    """

    serializer_class = DashboardSerializer

    def get_permissions(self):
        """Reads: any authenticated tenant user. Writes: Tenant Admin or Operator."""
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated(), IsViewOnly()]
        return [IsAuthenticated(), IsOperator()]

    def get_queryset(self):
        """Return dashboards scoped to the requesting user's tenant."""
        tenant = self.request.user.tenantuser.tenant
        return (
            Dashboard.objects
            .filter(tenant=tenant)
            .prefetch_related('widgets')
        )

    def list(self, request):
        """GET /api/v1/dashboards/ — list all dashboards for this tenant."""
        serializer = DashboardSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def create(self, request):
        """POST /api/v1/dashboards/ — create a new dashboard. Operator+."""
        serializer = DashboardSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        tenant = request.user.tenantuser.tenant
        serializer.save(tenant=tenant, created_by=request.user)
        logger.info('Dashboard "%s" created by %s', serializer.data['name'], request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        """GET /api/v1/dashboards/:id/ — retrieve a single dashboard with its widgets."""
        dashboard = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(DashboardSerializer(dashboard).data)

    def update(self, request, pk=None):
        """PUT /api/v1/dashboards/:id/ — update dashboard name or column count. Operator+."""
        dashboard = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DashboardSerializer(
            dashboard, data=request.data, partial=False, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Dashboard "%s" updated by %s', dashboard.name, request.user.email)
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/dashboards/:id/ — delete a dashboard and all its widgets. Operator+."""
        dashboard = get_object_or_404(self.get_queryset(), pk=pk)
        name = dashboard.name
        dashboard.delete()
        logger.info('Dashboard "%s" deleted by %s', name, request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DashboardWidgetViewSet(viewsets.GenericViewSet):
    """CRUD for widgets within a dashboard.

    Widgets are always accessed via their parent dashboard URL.
    Tenant Admin and Operator can create, update, and delete widgets.

    Ref: SPEC.md § Feature: Dashboards & Visualisation
    """

    serializer_class = DashboardWidgetSerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsOperator()]

    def _get_dashboard(self, request, dashboard_pk):
        """Return the dashboard scoped to this tenant. 404 if not found or wrong tenant."""
        tenant = request.user.tenantuser.tenant
        return get_object_or_404(Dashboard, pk=dashboard_pk, tenant=tenant)

    def create(self, request, dashboard_pk=None):
        """POST /api/v1/dashboards/:id/widgets/ — add a widget to a dashboard. Operator+."""
        dashboard = self._get_dashboard(request, dashboard_pk)
        serializer = DashboardWidgetSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save(dashboard=dashboard)
        logger.info(
            'Widget added to dashboard "%s" by %s', dashboard.name, request.user.email
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, dashboard_pk=None, pk=None):
        """PUT /api/v1/dashboards/:id/widgets/:widget_id/ — update a widget. Operator+."""
        dashboard = self._get_dashboard(request, dashboard_pk)
        widget = get_object_or_404(DashboardWidget, pk=pk, dashboard=dashboard)
        serializer = DashboardWidgetSerializer(
            widget, data=request.data, partial=False, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, dashboard_pk=None, pk=None):
        """DELETE /api/v1/dashboards/:id/widgets/:widget_id/ — remove a widget. Operator+."""
        dashboard = self._get_dashboard(request, dashboard_pk)
        widget = get_object_or_404(DashboardWidget, pk=pk, dashboard=dashboard)
        widget.delete()
        logger.info(
            'Widget %s removed from dashboard "%s" by %s',
            pk, dashboard.name, request.user.email,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
