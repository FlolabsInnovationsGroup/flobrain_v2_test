from django.urls import path

from commissions import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/leads", v.LeadListView.as_view(), name="v2-leads"),
    path("orgs/<uuid:org_id>/leads/<uuid:lead_id>", v.LeadDetailView.as_view(), name="v2-lead"),
    path("orgs/<uuid:org_id>/commissions", v.CommissionListView.as_view(), name="v2-commissions"),
    path("orgs/<uuid:org_id>/commissions/summary", v.CommissionSummaryView.as_view(), name="v2-commission-summary"),
    path("orgs/<uuid:org_id>/commissions/<uuid:commission_id>", v.CommissionDetailView.as_view(), name="v2-commission"),
]
