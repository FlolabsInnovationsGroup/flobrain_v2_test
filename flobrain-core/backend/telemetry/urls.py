from django.urls import path

from telemetry.v2_views import (
    BudgetDetailView,
    BudgetStatusView,
    BudgetView,
    MyBudgetsView,
    UsageExportView,
    UsageListView,
    UsageSummaryView,
)
from telemetry.views import (
    AdminAnalyticsView,
    AdminFeedbackDetailView,
    AdminFeedbackListView,
    FeedbackCreateView,
    ProductEventCreateView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/usage", UsageListView.as_view(), name="v2-usage"),
    path("orgs/<uuid:org_id>/budgets", BudgetView.as_view(), name="v2-budgets"),
    path("orgs/<uuid:org_id>/usage/summary", UsageSummaryView.as_view(), name="v2-usage-summary"),
    path("orgs/<uuid:org_id>/usage/export", UsageExportView.as_view(), name="v2-usage-export"),
    path("orgs/<uuid:org_id>/budgets/status", BudgetStatusView.as_view(), name="v2-budget-status"),
    path("orgs/<uuid:org_id>/budgets/mine", MyBudgetsView.as_view(), name="v2-budgets-mine"),
    path("orgs/<uuid:org_id>/budgets/<uuid:budget_id>", BudgetDetailView.as_view(), name="v2-budget-detail"),
    path("orgs/<uuid:org_id>/events", ProductEventCreateView.as_view(), name="v2-events"),
    path("orgs/<uuid:org_id>/feedback", FeedbackCreateView.as_view(), name="v2-feedback"),
    path("orgs/<uuid:org_id>/admin/feedback", AdminFeedbackListView.as_view(), name="v2-admin-feedback"),
    path("orgs/<uuid:org_id>/admin/feedback/<uuid:item_id>", AdminFeedbackDetailView.as_view(), name="v2-admin-feedback-detail"),
    path("orgs/<uuid:org_id>/admin/analytics", AdminAnalyticsView.as_view(), name="v2-admin-analytics"),
]
