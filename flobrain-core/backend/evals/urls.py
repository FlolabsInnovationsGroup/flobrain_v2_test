from django.urls import path

from evals import views

P = "orgs/<uuid:org_id>/evals"

urlpatterns = [
    path(f"{P}/overview", views.OverviewView.as_view(), name="v2-evals-overview"),
    path(f"{P}/sets", views.SetListView.as_view(), name="v2-evals-sets"),
    path(f"{P}/sets/<uuid:set_id>", views.SetDetailView.as_view(), name="v2-evals-set"),
    path(f"{P}/sets/<uuid:set_id>/cases", views.CaseListView.as_view(), name="v2-evals-cases"),
    path(f"{P}/sets/<uuid:set_id>/suggest", views.SuggestView.as_view(), name="v2-evals-suggest"),
    path(f"{P}/sets/<uuid:set_id>/runs", views.RunListView.as_view(), name="v2-evals-runs"),
    path(f"{P}/cases/<uuid:case_id>", views.CaseDetailView.as_view(), name="v2-evals-case"),
    path(f"{P}/runs/<uuid:run_id>", views.RunDetailView.as_view(), name="v2-evals-run"),
    path(f"{P}/gate-check", views.GateCheckView.as_view(), name="v2-evals-gate-check"),
    path(f"{P}/gate-events", views.GateEventListView.as_view(), name="v2-evals-gate-events"),
    path(f"{P}/settings", views.SettingsView.as_view(), name="v2-evals-settings"),
    path(f"{P}/documents", views.DocumentPickView.as_view(), name="v2-evals-documents"),
]
