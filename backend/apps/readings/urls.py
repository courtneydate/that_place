"""URL patterns for the readings app.

Ref: SPEC.md § API Routes
"""
from django.urls import path

from .views import (
    DerivedStreamViewSet,
    ExportHistoryView,
    ExportStreamView,
    StreamViewSet,
)

app_name = 'readings'

stream_detail = StreamViewSet.as_view({
    'get': 'retrieve', 'put': 'update', 'patch': 'partial_update',
})
stream_readings = StreamViewSet.as_view({'get': 'readings'})
stream_aggregates = StreamViewSet.as_view({'get': 'aggregates'})
stream_aggregates_backfill = StreamViewSet.as_view({'post': 'aggregates_backfill'})

derived_stream_list = DerivedStreamViewSet.as_view({'get': 'list', 'post': 'create'})
derived_stream_detail = DerivedStreamViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy',
})
derived_stream_backfill = DerivedStreamViewSet.as_view({'post': 'backfill'})

urlpatterns = [
    path('streams/<int:pk>/', stream_detail, name='stream-detail'),
    path('streams/<int:pk>/readings/', stream_readings, name='stream-readings'),
    path('streams/<int:pk>/aggregates/', stream_aggregates, name='stream-aggregates'),
    path('streams/<int:pk>/aggregates/backfill/', stream_aggregates_backfill, name='stream-aggregates-backfill'),
    path('exports/', ExportHistoryView.as_view(), name='export-history'),
    path('exports/stream/', ExportStreamView.as_view(), name='export-stream'),
    path('derived-streams/', derived_stream_list, name='derived-stream-list'),
    path('derived-streams/<int:pk>/', derived_stream_detail, name='derived-stream-detail'),
    path('derived-streams/<int:pk>/backfill/', derived_stream_backfill, name='derived-stream-backfill'),
]
