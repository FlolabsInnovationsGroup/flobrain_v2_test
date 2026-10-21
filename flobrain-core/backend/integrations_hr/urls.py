from django.urls import path

from integrations_hr.views import HRApplicantWebhookView
from integrations_hr.views_pending import PendingMemberDecideView, PendingMemberListView

urlpatterns = [
    path("integrations/hr/applicants", HRApplicantWebhookView.as_view(), name="v2-hr-applicants"),
    path("orgs/<uuid:org_id>/pending-members", PendingMemberListView.as_view(), name="v2-pending-members"),
    path(
        "orgs/<uuid:org_id>/pending-members/<uuid:user_id>/<str:decision>",
        PendingMemberDecideView.as_view(),
        name="v2-pending-member-decide",
    ),
]
