from django.urls import path

from platform_api import mcp, oauth_mcp as oauth, public_views as v, views_status as status

urlpatterns = [
    path("api/public/v1/me", v.MeView.as_view(), name="public-me"),
    path("api/public/v1/tasks", v.TaskListView.as_view(), name="public-tasks"),
    path("api/public/v1/tasks/<uuid:task_id>", v.TaskDetailView.as_view(), name="public-task"),
    path("api/public/v1/rooms", v.RoomListView.as_view(), name="public-rooms"),
    path("api/public/v1/rooms/<uuid:room_id>/messages", v.RoomMessagesView.as_view(), name="public-room-messages"),
    path("api/public/v1/time/entries", v.TimeEntriesView.as_view(), name="public-time-entries"),
    path("api/public/status", status.PublicStatusView.as_view(), name="public-status"),
    path("api/public/status/subscribe", status.StatusSubscribeView.as_view(), name="public-status-subscribe"),
    path("api/public/status/confirm", status.StatusConfirmView.as_view(), name="public-status-confirm"),
    path("api/public/status/unsubscribe", status.StatusUnsubscribeView.as_view(), name="public-status-unsubscribe"),
    path("api/mcp", mcp.MCPView.as_view(), name="mcp"),
    # MCP authorization (growth round M1): RFC 9728, RFC 8414, RFC 7591, OAuth 2.1, RFC 7009
    path(".well-known/oauth-protected-resource", oauth.ProtectedResourceMetadataView.as_view(), name="mcp-protected-resource"),
    path(".well-known/oauth-protected-resource/api/mcp", oauth.ProtectedResourceMetadataView.as_view(), name="mcp-protected-resource-path"),
    path(".well-known/oauth-authorization-server", oauth.AuthorizationServerMetadataView.as_view(), name="mcp-authorization-server"),
    path("oauth/register", oauth.RegisterView.as_view(), name="mcp-oauth-register"),
    path("oauth/authorize", oauth.AuthorizeView.as_view(), name="mcp-oauth-authorize"),
    path("oauth/token", oauth.TokenView.as_view(), name="mcp-oauth-token"),
    path("oauth/revoke", oauth.RevokeView.as_view(), name="mcp-oauth-revoke"),
]
