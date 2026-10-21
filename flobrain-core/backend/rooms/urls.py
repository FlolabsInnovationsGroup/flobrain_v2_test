from django.urls import path

from rooms.views import (
    AnnouncementListCreateView,
    AnnouncementPinView,
    AnnouncementUnpinView,
    RoomDetailView,
    RoomListCreateView,
    RoomMemberListView,
    RoomMessageDetailView,
    RoomMessageListCreateView,
    RoomSearchView,
)
from rooms.voice_views import BuddyVoiceInputView, RoomVoiceAudioView, RoomVoiceRetryView, RoomVoiceView

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
    # W7 voice notes (flag voice_notes)
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/voice", RoomVoiceView.as_view(), name="v2-room-voice"),
    path(
        "orgs/<uuid:org_id>/rooms/<uuid:room_id>/voice/<uuid:voice_id>/audio",
        RoomVoiceAudioView.as_view(),
        name="v2-room-voice-audio",
    ),
    path(
        "orgs/<uuid:org_id>/rooms/<uuid:room_id>/voice/<uuid:voice_id>/retry",
        RoomVoiceRetryView.as_view(),
        name="v2-room-voice-retry",
    ),
    path("orgs/<uuid:org_id>/buddies/voice-input", BuddyVoiceInputView.as_view(), name="v2-buddy-voice-input"),
    path("orgs/<uuid:org_id>/announcements", AnnouncementListCreateView.as_view(), name="v2-announcements"),
    path(
        "orgs/<uuid:org_id>/announcements/<uuid:announcement_id>/unpin",
        AnnouncementUnpinView.as_view(),
        name="v2-announcement-unpin",
    ),
    path(
        "orgs/<uuid:org_id>/announcements/<uuid:announcement_id>/pin",
        AnnouncementPinView.as_view(),
        name="v2-announcement-pin",
    ),
]
