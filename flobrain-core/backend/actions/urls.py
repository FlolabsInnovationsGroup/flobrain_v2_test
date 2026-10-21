from django.urls import path

from actions.views import (
    ActionDecisionView,
    ActionDetailView,
    ActionListView,
    TeamReportGenerateView,
    TeamReportListView,
    TeamReportPostView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/actions", ActionListView.as_view(), name="v2-actions"),
    path("orgs/<uuid:org_id>/actions/<uuid:proposal_id>", ActionDetailView.as_view(), name="v2-action-detail"),
    path(
        "orgs/<uuid:org_id>/actions/<uuid:proposal_id>/<str:decision>",
        ActionDecisionView.as_view(),
        name="v2-action-decision",
    ),
    path("orgs/<uuid:org_id>/teams/<uuid:team_id>/reports", TeamReportListView.as_view(), name="v2-team-reports"),
    path(
        "orgs/<uuid:org_id>/teams/<uuid:team_id>/reports/generate",
        TeamReportGenerateView.as_view(),
        name="v2-team-reports-generate",
    ),
    path(
        "orgs/<uuid:org_id>/teams/<uuid:team_id>/reports/<uuid:report_id>/post",
        TeamReportPostView.as_view(),
        name="v2-team-report-post",
    ),
]
