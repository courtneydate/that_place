"""URL patterns for the feeds app.

Feed Providers (That Place Admin write, all authenticated read):
    GET    /api/v1/feed-providers/
    POST   /api/v1/feed-providers/
    GET    /api/v1/feed-providers/{id}/
    PUT    /api/v1/feed-providers/{id}/
    PATCH  /api/v1/feed-providers/{id}/
    DELETE /api/v1/feed-providers/{id}/
    GET    /api/v1/feed-providers/{id}/channels/

Feed Channels (read-only, all authenticated):
    GET    /api/v1/feed-channels/{id}/
    GET    /api/v1/feed-channels/{id}/readings/

Tenant Feed Subscriptions (Tenant Admin):
    GET    /api/v1/feed-subscriptions/
    POST   /api/v1/feed-subscriptions/
    GET    /api/v1/feed-subscriptions/{id}/
    PUT    /api/v1/feed-subscriptions/{id}/
    PATCH  /api/v1/feed-subscriptions/{id}/
    DELETE /api/v1/feed-subscriptions/{id}/

Reference Datasets (That Place Admin write, all authenticated read):
    GET    /api/v1/reference-datasets/
    POST   /api/v1/reference-datasets/
    GET    /api/v1/reference-datasets/{id}/
    PUT    /api/v1/reference-datasets/{id}/
    DELETE /api/v1/reference-datasets/{id}/
    GET    /api/v1/reference-datasets/{id}/rows/
    POST   /api/v1/reference-datasets/{id}/rows/
    PUT    /api/v1/reference-datasets/{id}/rows/{row_id}/
    PATCH  /api/v1/reference-datasets/{id}/rows/{row_id}/
    DELETE /api/v1/reference-datasets/{id}/rows/{row_id}/
    POST   /api/v1/reference-datasets/{id}/rows/bulk/

Tenant Dataset Assignments (Tenant Admin):
    GET    /api/v1/dataset-assignments/
    POST   /api/v1/dataset-assignments/
    GET    /api/v1/dataset-assignments/{id}/
    PUT    /api/v1/dataset-assignments/{id}/
    PATCH  /api/v1/dataset-assignments/{id}/
    DELETE /api/v1/dataset-assignments/{id}/
    GET    /api/v1/dataset-assignments/{id}/resolve/
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    FeedChannelViewSet,
    FeedProviderViewSet,
    ReferenceDatasetRowViewSet,
    ReferenceDatasetViewSet,
    TenantDatasetAssignmentViewSet,
    TenantFeedSubscriptionViewSet,
)

router = DefaultRouter()
router.register('feed-providers', FeedProviderViewSet, basename='feed-provider')
router.register('feed-channels', FeedChannelViewSet, basename='feed-channel')
router.register('feed-subscriptions', TenantFeedSubscriptionViewSet, basename='feed-subscription')
router.register('reference-datasets', ReferenceDatasetViewSet, basename='reference-dataset')
router.register('dataset-assignments', TenantDatasetAssignmentViewSet, basename='dataset-assignment')

app_name = 'feeds'

urlpatterns = [
    path('', include(router.urls)),
    # Nested row endpoints: /reference-datasets/{dataset_pk}/rows/
    path(
        'reference-datasets/<int:dataset_pk>/rows/',
        ReferenceDatasetRowViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='dataset-rows-list',
    ),
    path(
        'reference-datasets/<int:dataset_pk>/rows/bulk/',
        ReferenceDatasetRowViewSet.as_view({'post': 'bulk_import'}),
        name='dataset-rows-bulk',
    ),
    path(
        'reference-datasets/<int:dataset_pk>/rows/export/',
        ReferenceDatasetRowViewSet.as_view({'get': 'export_csv'}),
        name='dataset-rows-export',
    ),
    path(
        'reference-datasets/<int:dataset_pk>/rows/<int:pk>/',
        ReferenceDatasetRowViewSet.as_view({
            'put': 'update',
            'patch': 'partial_update',
            'delete': 'destroy',
        }),
        name='dataset-rows-detail',
    ),
]
