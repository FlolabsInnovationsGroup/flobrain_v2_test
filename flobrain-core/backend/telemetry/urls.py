from django.urls import path

from telemetry.v2_views import BudgetStatusView, BudgetView, UsageListView
from telemetry.views import (
    AdminAnalyticsView,
    AdminFeedbackListView,
    FeedbackCreateView,
    ProductEventCreateView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/usage", UsageListView.as_view(), name="v2-usage"),
    path("orgs/<uuid:org_id>/budgets", BudgetView.as_view(), name="v2-budgets"),
    path("orgs/<uuid:org_id>/budgets/status", BudgetStatusView.as_view(), name="v2-budget-status"),
    path("orgs/<uuid:org_id>/events", ProductEventCreateView.as_view(), name="v2-events"),
    path("orgs/<uuid:org_id>/feedback", FeedbackCreateView.as_view(), name="v2-feedback"),
    path("orgs/<uuid:org_id>/admin/feedback", AdminFeedbackListView.as_view(), name="v2-admin-feedback"),
    path("orgs/<uuid:org_id>/admin/analytics", AdminAnalyticsView.as_view(), name="v2-admin-analytics"),
]
