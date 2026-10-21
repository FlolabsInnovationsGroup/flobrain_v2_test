from django.urls import path

from platform_api import mcp, public_views as v, views_status as status

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
]
