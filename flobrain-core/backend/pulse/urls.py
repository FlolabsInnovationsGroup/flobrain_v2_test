from django.urls import path

from pulse import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/pulse/overview", v.OverviewView.as_view(), name="v2-pulse-overview"),
    path("orgs/<uuid:org_id>/pulse/models", v.ModelsView.as_view(), name="v2-pulse-models"),
    path("orgs/<uuid:org_id>/pulse/surfaces", v.SurfacesView.as_view(), name="v2-pulse-surfaces"),
    path("orgs/<uuid:org_id>/pulse/agents", v.AgentsView.as_view(), name="v2-pulse-agents"),
    path("orgs/<uuid:org_id>/pulse/cost", v.CostView.as_view(), name="v2-pulse-cost"),
    path("orgs/<uuid:org_id>/pulse/governance", v.GovernanceView.as_view(), name="v2-pulse-governance"),
    path("orgs/<uuid:org_id>/pulse/incidents", v.IncidentsView.as_view(), name="v2-pulse-incidents"),
    path("orgs/<uuid:org_id>/pulse/traces", v.TraceListView.as_view(), name="v2-pulse-traces"),
    path("orgs/<uuid:org_id>/pulse/traces/<uuid:trace_id>", v.TraceDetailView.as_view(), name="v2-pulse-trace"),
    path("orgs/<uuid:org_id>/pulse/suites", v.SuiteListView.as_view(), name="v2-pulse-suites"),
    path("orgs/<uuid:org_id>/pulse/suites/<uuid:suite_id>/run", v.SuiteRunView.as_view(), name="v2-pulse-suite-run"),
    path("orgs/<uuid:org_id>/pulse/runs/<uuid:run_id>", v.RunDetailView.as_view(), name="v2-pulse-run"),
    path("orgs/<uuid:org_id>/pulse/routing", v.RoutingView.as_view(), name="v2-pulse-routing"),
    path("orgs/<uuid:org_id>/pulse/routing/preview", v.RoutingPreviewView.as_view(), name="v2-pulse-routing-preview"),
    path("orgs/<uuid:org_id>/pulse/alerts", v.AlertListView.as_view(), name="v2-pulse-alerts"),
    path("orgs/<uuid:org_id>/pulse/alerts/<uuid:rule_id>", v.AlertDetailView.as_view(), name="v2-pulse-alert"),
]
