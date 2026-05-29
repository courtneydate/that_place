"""URL patterns for the billing app — Sprint 30.

Routes:
    GET    /api/v1/billing-accounts/
    POST   /api/v1/billing-accounts/
    GET    /api/v1/billing-accounts/{id}/
    PUT    /api/v1/billing-accounts/{id}/
    PATCH  /api/v1/billing-accounts/{id}/
    DELETE /api/v1/billing-accounts/{id}/
    GET    /api/v1/billing-accounts/{id}/audit-log/
    POST   /api/v1/billing-accounts/bulk/

    GET    /api/v1/billing-accounts/{account_pk}/meters/
    POST   /api/v1/billing-accounts/{account_pk}/meters/
    GET    /api/v1/billing-accounts/{account_pk}/meters/{pk}/
    PUT    /api/v1/billing-accounts/{account_pk}/meters/{pk}/
    PATCH  /api/v1/billing-accounts/{account_pk}/meters/{pk}/
    DELETE /api/v1/billing-accounts/{account_pk}/meters/{pk}/

    GET    /api/v1/billing-accounts/{account_pk}/tariffs/
    POST   /api/v1/billing-accounts/{account_pk}/tariffs/
    GET    /api/v1/billing-accounts/{account_pk}/tariffs/{pk}/
    PUT    /api/v1/billing-accounts/{account_pk}/tariffs/{pk}/
    PATCH  /api/v1/billing-accounts/{account_pk}/tariffs/{pk}/
    DELETE /api/v1/billing-accounts/{account_pk}/tariffs/{pk}/
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BillingAccountMeterView,
    BillingAccountTariffAssignmentView,
    BillingAccountViewSet,
)

router = DefaultRouter()
router.register('billing-accounts', BillingAccountViewSet, basename='billing-account')

app_name = 'billing'

urlpatterns = [
    path('', include(router.urls)),
    path(
        'billing-accounts/<int:account_pk>/meters/',
        BillingAccountMeterView.as_view(),
        name='billing-account-meters-list',
    ),
    path(
        'billing-accounts/<int:account_pk>/meters/<int:pk>/',
        BillingAccountMeterView.as_view(),
        name='billing-account-meters-detail',
    ),
    path(
        'billing-accounts/<int:account_pk>/tariffs/',
        BillingAccountTariffAssignmentView.as_view(),
        name='billing-account-tariffs-list',
    ),
    path(
        'billing-accounts/<int:account_pk>/tariffs/<int:pk>/',
        BillingAccountTariffAssignmentView.as_view(),
        name='billing-account-tariffs-detail',
    ),
]
