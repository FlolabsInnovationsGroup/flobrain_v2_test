from django.urls import path

from channels import views, views_hooks, views_public

urlpatterns = [
    path("orgs/<uuid:org_id>/channels/connections", views.ConnectionListView.as_view(), name="v2-channel-connections"),
    path("orgs/<uuid:org_id>/channels/connections/<uuid:connection_id>", views.ConnectionDetailView.as_view(), name="v2-channel-connection"),
    path("orgs/<uuid:org_id>/channels/connections/<uuid:connection_id>/test", views.ConnectionTestView.as_view(), name="v2-channel-connection-test"),
    path("orgs/<uuid:org_id>/channels/links", views.LinkListView.as_view(), name="v2-channel-links"),
    path("orgs/<uuid:org_id>/channels/links/<uuid:link_id>", views.LinkDetailView.as_view(), name="v2-channel-link"),
    path("orgs/<uuid:org_id>/channels/customer-settings", views.CustomerSettingsView.as_view(), name="v2-channel-customer-settings"),
    path("orgs/<uuid:org_id>/channels/demo/simulate", views.DemoSimulateView.as_view(), name="v2-channel-demo-simulate"),
    path("orgs/<uuid:org_id>/customers/conversations", views.ConversationListView.as_view(), name="v2-customer-conversations"),
    path("orgs/<uuid:org_id>/customers/conversations/<uuid:conversation_id>", views.ConversationDetailView.as_view(), name="v2-customer-conversation"),
    path(
        "orgs/<uuid:org_id>/customers/conversations/<uuid:conversation_id>/messages/<uuid:message_id>/<str:decision>",
        views.DraftDecisionView.as_view(),
        name="v2-customer-draft-decision",
    ),
    path("orgs/<uuid:org_id>/customers/conversations/<uuid:conversation_id>/<str:action>", views.ConversationActionView.as_view(), name="v2-customer-conversation-action"),
    path("hooks/whatsapp/<uuid:connection_id>", views_hooks.WhatsAppHookView.as_view(), name="v2-hook-whatsapp"),
    path("hooks/telegram/<uuid:connection_id>", views_hooks.TelegramHookView.as_view(), name="v2-hook-telegram"),
    path("public/chat/<str:site_key>", views_public.PublicChatConfigView.as_view(), name="v2-public-chat"),
    path("public/chat/<str:site_key>/messages", views_public.PublicChatMessagesView.as_view(), name="v2-public-chat-messages"),
]
