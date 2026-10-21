from django.urls import path

from privacy import insights
from privacy import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/me/privacy", v.MyPrivacyView.as_view(), name="v2-my-privacy"),
    path("orgs/<uuid:org_id>/me/insights", insights.MyInsightsView.as_view(), name="v2-my-insights"),
    path("orgs/<uuid:org_id>/teams/<uuid:team_id>/insights", insights.TeamInsightsView.as_view(), name="v2-team-insights"),
    path("orgs/<uuid:org_id>/privacy/deletion-requests", v.DeletionRequestListView.as_view(), name="v2-deletion-requests"),
    path("orgs/<uuid:org_id>/privacy/deletion-requests/<uuid:request_id>", v.DeletionRequestDetailView.as_view(), name="v2-deletion-request"),
    path("orgs/<uuid:org_id>/privacy/retention", v.RetentionPolicyView.as_view(), name="v2-retention"),
    path("me/data-exports", v.MyDataExportView.as_view(), name="v2-my-data-exports"),
    path("me/data-exports/<uuid:export_id>", v.MyDataExportDetailView.as_view(), name="v2-my-data-export"),
]
