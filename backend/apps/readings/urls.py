"""URL patterns for the readings app.

Ref: SPEC.md § API Routes
"""
from django.urls import path

from .views import ExportHistoryView, ExportStreamView, StreamViewSet

app_name = 'readings'

stream_detail = StreamViewSet.as_view({'get': 'retrieve', 'put': 'update'})
stream_readings = StreamViewSet.as_view({'get': 'readings'})

urlpatterns = [
    path('streams/<int:pk>/', stream_detail, name='stream-detail'),
    path('streams/<int:pk>/readings/', stream_readings, name='stream-readings'),
    path('exports/', ExportHistoryView.as_view(), name='export-history'),
    path('exports/stream/', ExportStreamView.as_view(), name='export-stream'),
]
