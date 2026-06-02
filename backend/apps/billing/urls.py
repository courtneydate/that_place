"""URL patterns for the billing app — Sprint 30 + Sprint 31.

Sprint 30 routes (BillingAccount + meters + tariff assignments):
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

Sprint 31 routes (BillingRun + BillingSchedule):
    GET    /api/v1/billing-runs/                       — list runs
    POST   /api/v1/billing-runs/                       — create + dispatch
    GET    /api/v1/billing-runs/{id}/                  — retrieve
    POST   /api/v1/billing-runs/{id}/retry/            — retry failed run
    POST   /api/v1/billing-runs/{id}/recompute/        — rebuild draft run
    GET    /api/v1/billing-runs/{id}/line-items/       — list line items
    GET    /api/v1/billing-runs/{id}/snapshot/         — list snapshots

    GET    /api/v1/billing-schedules/
    POST   /api/v1/billing-schedules/
    GET    /api/v1/billing-schedules/{id}/
    PUT    /api/v1/billing-schedules/{id}/
    PATCH  /api/v1/billing-schedules/{id}/
    DELETE /api/v1/billing-schedules/{id}/
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BillingAccountMeterView,
    BillingAccountTariffAssignmentView,
    BillingAccountViewSet,
    BillingRunViewSet,
    BillingScheduleViewSet,
)

router = DefaultRouter()
router.register('billing-accounts', BillingAccountViewSet, basename='billing-account')
router.register('billing-runs', BillingRunViewSet, basename='billing-run')
router.register('billing-schedules', BillingScheduleViewSet, basename='billing-schedule')

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
