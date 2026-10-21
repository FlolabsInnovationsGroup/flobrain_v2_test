from django.urls import path

from bridges import views, views_hooks

urlpatterns = [
    path("orgs/<uuid:org_id>/bridges", views.OverviewView.as_view(), name="v2-bridges"),
    path("orgs/<uuid:org_id>/bridges/slack/install", views.SlackInstallView.as_view(), name="v2-bridges-slack-install"),
    path("orgs/<uuid:org_id>/bridges/slack/confirm", views.SlackConfirmView.as_view(), name="v2-bridges-slack-confirm"),
    path("orgs/<uuid:org_id>/bridges/teams/connect", views.TeamsConnectView.as_view(), name="v2-bridges-teams-connect"),
    path("orgs/<uuid:org_id>/bridges/teams/manifest", views.TeamsManifestView.as_view(), name="v2-bridges-teams-manifest"),
    path("orgs/<uuid:org_id>/bridges/workspaces/<uuid:workspace_id>", views.WorkspaceDetailView.as_view(), name="v2-bridges-workspace"),
    path("orgs/<uuid:org_id>/bridges/workspaces/<uuid:workspace_id>/test", views.WorkspaceTestView.as_view(), name="v2-bridges-workspace-test"),
    path("orgs/<uuid:org_id>/bridges/links", views.LinkListView.as_view(), name="v2-bridges-links"),
    path("orgs/<uuid:org_id>/bridges/links/<uuid:link_id>", views.LinkDetailView.as_view(), name="v2-bridges-link"),
    path("orgs/<uuid:org_id>/bridges/links/<uuid:link_id>/confirm", views.LinkConfirmView.as_view(), name="v2-bridges-link-confirm"),
    path("orgs/<uuid:org_id>/bridges/demo/simulate", views.DemoSimulateView.as_view(), name="v2-bridges-demo-simulate"),
    path("orgs/<uuid:org_id>/bridges/demo/decide", views.DemoDecideView.as_view(), name="v2-bridges-demo-decide"),
    path("bridges/slack/oauth/callback", views_hooks.SlackOAuthCallbackView.as_view(), name="v2-bridges-slack-callback"),
    path("hooks/slack/events", views_hooks.SlackEventsView.as_view(), name="v2-hook-slack-events"),
    path("hooks/slack/commands", views_hooks.SlackCommandsView.as_view(), name="v2-hook-slack-commands"),
    path("hooks/slack/interactions", views_hooks.SlackInteractionsView.as_view(), name="v2-hook-slack-interactions"),
    path("hooks/teams/messages", views_hooks.TeamsMessagesView.as_view(), name="v2-hook-teams-messages"),
]
