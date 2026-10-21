from django.urls import path

from platform_api import views, views_external as ext

urlpatterns = [
    path("me/tokens", views.MyTokensView.as_view(), name="v2-my-tokens"),
    path("me/tokens/<uuid:token_id>", views.MyTokenDetailView.as_view(), name="v2-my-token"),
    path("orgs/<uuid:org_id>/webhooks", views.WebhookListView.as_view(), name="v2-webhooks"),
    path("orgs/<uuid:org_id>/webhooks/demo-inbox", views.DemoInboxView.as_view(), name="v2-webhooks-demo-inbox"),
    path("orgs/<uuid:org_id>/webhooks/<uuid:hook_id>", views.WebhookDetailView.as_view(), name="v2-webhook"),
    path("orgs/<uuid:org_id>/webhooks/<uuid:hook_id>/test", views.WebhookTestView.as_view(), name="v2-webhook-test"),
    path(
        "orgs/<uuid:org_id>/webhooks/<uuid:hook_id>/deliveries/<uuid:delivery_id>/retry",
        views.WebhookDeliveryRetryView.as_view(),
        name="v2-webhook-delivery-retry",
    ),
    path("orgs/<uuid:org_id>/external-agents", ext.ExternalAgentListView.as_view(), name="v2-external-agents"),
    path("orgs/<uuid:org_id>/external-agents/allowlist", ext.ExternalAgentAllowlistView.as_view(), name="v2-external-agent-allowlist"),
    path("orgs/<uuid:org_id>/external-agents/allowlist/<uuid:host_id>", ext.ExternalAgentAllowlistDetailView.as_view(), name="v2-external-agent-host"),
    path("orgs/<uuid:org_id>/external-agents/calls", ext.ExternalAgentCallListView.as_view(), name="v2-external-agent-calls"),
    path(
        "orgs/<uuid:org_id>/external-agents/calls/<uuid:call_id>/approve",
        ext.ExternalAgentCallDecisionView.as_view(decision="approve"),
        name="v2-external-agent-call-approve",
    ),
    path(
        "orgs/<uuid:org_id>/external-agents/calls/<uuid:call_id>/reject",
        ext.ExternalAgentCallDecisionView.as_view(decision="reject"),
        name="v2-external-agent-call-reject",
    ),
    path("orgs/<uuid:org_id>/external-agents/<uuid:server_id>", ext.ExternalAgentDetailView.as_view(), name="v2-external-agent"),
    path("orgs/<uuid:org_id>/external-agents/<uuid:server_id>/refresh", ext.ExternalAgentRefreshView.as_view(), name="v2-external-agent-refresh"),
    path("orgs/<uuid:org_id>/external-agents/<uuid:server_id>/approve-tools", ext.ExternalAgentApproveToolsView.as_view(), name="v2-external-agent-approve-tools"),
    path("orgs/<uuid:org_id>/external-agents/<uuid:server_id>/test", ext.ExternalAgentTestView.as_view(), name="v2-external-agent-test"),
    path("orgs/<uuid:org_id>/incidents", views.IncidentListView.as_view(), name="v2-incidents"),
    path("orgs/<uuid:org_id>/incidents/<uuid:incident_id>", views.IncidentDetailView.as_view(), name="v2-incident"),
    path("platform/incidents", views.PlatformIncidentListView.as_view(), name="v2-platform-incidents"),
    path("platform/incidents/<uuid:incident_id>", views.PlatformIncidentDetailView.as_view(), name="v2-platform-incident"),
]
