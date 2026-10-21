from django.urls import path

from rooms.views import (
    AnnouncementListCreateView,
    AnnouncementUnpinView,
    RoomDetailView,
    RoomListCreateView,
    RoomMemberListView,
    RoomMessageDetailView,
    RoomMessageListCreateView,
    RoomSearchView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/rooms", RoomListCreateView.as_view(), name="v2-rooms"),
    path("orgs/<uuid:org_id>/rooms/search", RoomSearchView.as_view(), name="v2-rooms-search"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>", RoomDetailView.as_view(), name="v2-room-detail"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/members", RoomMemberListView.as_view(), name="v2-room-members"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/messages", RoomMessageListCreateView.as_view(), name="v2-room-messages"),
    path(
        "orgs/<uuid:org_id>/rooms/<uuid:room_id>/messages/<uuid:message_id>",
        RoomMessageDetailView.as_view(),
        name="v2-room-message",
    ),
    path("orgs/<uuid:org_id>/announcements", AnnouncementListCreateView.as_view(), name="v2-announcements"),
    path(
        "orgs/<uuid:org_id>/announcements/<uuid:announcement_id>/unpin",
        AnnouncementUnpinView.as_view(),
        name="v2-announcement-unpin",
    ),
]
