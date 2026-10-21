from django.urls import path

from compliance import views as v
from compliance import views_public as pub

P = "orgs/<uuid:org_id>/compliance"

urlpatterns = [
    path(f"{P}/me", v.MeView.as_view(), name="v2-compliance-me"),
    path(f"{P}/overview", v.OverviewView.as_view(), name="v2-compliance-overview"),
    path(f"{P}/settings", v.SettingsView.as_view(), name="v2-compliance-settings"),
    path(f"{P}/controls", v.ControlListView.as_view(), name="v2-compliance-controls"),
    path(f"{P}/controls/<str:framework>/<str:control_id>/attestation", v.AttestationView.as_view(), name="v2-compliance-attestation"),
    path(f"{P}/reviews", v.ReviewListView.as_view(), name="v2-compliance-reviews"),
    path(f"{P}/reviews/<uuid:review_id>", v.ReviewDetailView.as_view(), name="v2-compliance-review"),
    path(f"{P}/reviews/<uuid:review_id>/report", v.ReviewReportView.as_view(), name="v2-compliance-review-report"),
    path(f"{P}/reviews/<uuid:review_id>/items/<uuid:item_id>/decision", v.ReviewDecisionView.as_view(), name="v2-compliance-review-decision"),
    path(f"{P}/reviews/<uuid:review_id>/<str:action>", v.ReviewActionView.as_view(), name="v2-compliance-review-action"),
    path(f"{P}/my-reviews", v.MyReviewsView.as_view(), name="v2-compliance-my-reviews"),
    path(f"{P}/evidence", v.EvidenceListView.as_view(), name="v2-compliance-evidence"),
    path(f"{P}/evidence/<uuid:package_id>/download", v.EvidenceDownloadView.as_view(), name="v2-compliance-evidence-download"),
    path(f"{P}/policy-templates", v.PolicyTemplatesView.as_view(), name="v2-compliance-policy-templates"),
    path(f"{P}/policies", v.PolicyListView.as_view(), name="v2-compliance-policies"),
    path(f"{P}/policies/<uuid:policy_id>", v.PolicyDetailView.as_view(), name="v2-compliance-policy"),
    path(f"{P}/policies/<uuid:policy_id>/publish", v.PolicyPublishView.as_view(), name="v2-compliance-policy-publish"),
    path(f"{P}/policies/<uuid:policy_id>/acknowledge", v.PolicyAckView.as_view(), name="v2-compliance-policy-ack"),
    path(f"{P}/my-policies", v.MyPoliciesView.as_view(), name="v2-compliance-my-policies"),
    path(f"{P}/trust", v.TrustSettingsView.as_view(), name="v2-compliance-trust"),
    path(f"{P}/trust/requests", v.TrustRequestListView.as_view(), name="v2-compliance-trust-requests"),
    path(f"{P}/trust/requests/<uuid:request_id>", v.TrustRequestDetailView.as_view(), name="v2-compliance-trust-request"),
    path("public/trust/<str:slug>", pub.PublicTrustView.as_view(), name="v2-public-trust"),
    path("public/trust/<str:slug>/requests", pub.PublicTrustRequestView.as_view(), name="v2-public-trust-requests"),
]
