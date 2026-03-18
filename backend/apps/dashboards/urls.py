"""URL patterns for the dashboards app.

Ref: SPEC.md § API Routes
"""
from django.urls import path

from .views import DashboardViewSet, DashboardWidgetViewSet

app_name = 'dashboards'

dashboard_list = DashboardViewSet.as_view({'get': 'list', 'post': 'create'})
dashboard_detail = DashboardViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'})
widget_list = DashboardWidgetViewSet.as_view({'post': 'create'})
widget_detail = DashboardWidgetViewSet.as_view({'put': 'update', 'delete': 'destroy'})

urlpatterns = [
    path('dashboards/', dashboard_list, name='dashboard-list'),
    path('dashboards/<int:pk>/', dashboard_detail, name='dashboard-detail'),
    path('dashboards/<int:dashboard_pk>/widgets/', widget_list, name='widget-list'),
    path('dashboards/<int:dashboard_pk>/widgets/<int:pk>/', widget_detail, name='widget-detail'),
]
