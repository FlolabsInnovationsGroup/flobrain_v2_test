from django.urls import path

from automations import views

P = "orgs/<uuid:org_id>/automations"

urlpatterns = [
    path(P, views.WorkflowListView.as_view(), name="v2-automations"),
    path(f"{P}/templates", views.TemplateListView.as_view(), name="v2-automations-templates"),
    path(f"{P}/templates/<slug:key>/install", views.TemplateInstallView.as_view(), name="v2-automations-template-install"),
    path(f"{P}/draft", views.DraftView.as_view(), name="v2-automations-draft"),
    path(f"{P}/settings", views.SettingsView.as_view(), name="v2-automations-settings"),
    path(f"{P}/me", views.MyBriefView.as_view(), name="v2-automations-me"),
    path(f"{P}/runs", views.RunListView.as_view(), name="v2-automations-runs"),
    path(f"{P}/runs/<uuid:run_id>", views.RunDetailView.as_view(), name="v2-automations-run"),
    path(f"{P}/<uuid:workflow_id>", views.WorkflowDetailView.as_view(), name="v2-automation"),
    path(f"{P}/<uuid:workflow_id>/enable", views.WorkflowEnableView.as_view(), name="v2-automation-enable"),
    path(f"{P}/<uuid:workflow_id>/run", views.WorkflowRunNowView.as_view(), name="v2-automation-run-now"),
    path(f"{P}/<uuid:workflow_id>/runs", views.WorkflowRunsView.as_view(), name="v2-automation-runs"),
    path(f"{P}/<uuid:workflow_id>/hook", views.WorkflowHookView.as_view(), name="v2-automation-hook"),
    path("hooks/automations/<uuid:workflow_id>", views.InboundHookView.as_view(), name="v2-automations-inbound-hook"),
]
