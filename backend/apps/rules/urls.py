"""URL patterns for the rules app.

Routes:
  GET  /api/v1/rules/                              — list all rules
  POST /api/v1/rules/                              — create a rule (Tenant Admin)
  GET  /api/v1/rules/:id/                          — retrieve a rule
  PUT  /api/v1/rules/:id/                          — replace a rule (Tenant Admin)
  PATCH /api/v1/rules/:id/                         — partial update (Tenant Admin)
  DELETE /api/v1/rules/:id/                        — delete a rule (Tenant Admin)
  GET  /api/v1/rules/:id/audit-logs/               — full audit trail
  GET  /api/v1/rules/:id/my-notification-prefs/    — current user's per-channel opt-outs
  PUT  /api/v1/rules/:id/my-notification-prefs/    — set current user's per-channel opt-outs

Ref: SPEC.md § API Endpoints — Rules Engine
"""
from django.urls import path

from .views import RuleViewSet

app_name = 'rules'

rule_list = RuleViewSet.as_view({'get': 'list', 'post': 'create'})
rule_detail = RuleViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy',
})
audit_logs = RuleViewSet.as_view({'get': 'audit_logs'})
my_notification_prefs = RuleViewSet.as_view({
    'get': 'my_notification_prefs',
    'put': 'my_notification_prefs',
})

urlpatterns = [
    path('rules/', rule_list, name='rule-list'),
    path('rules/<int:pk>/', rule_detail, name='rule-detail'),
    path('rules/<int:pk>/audit-logs/', audit_logs, name='rule-audit-logs'),
    path('rules/<int:pk>/my-notification-prefs/', my_notification_prefs,
         name='rule-my-notification-prefs'),
]
