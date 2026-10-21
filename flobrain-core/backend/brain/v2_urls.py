from django.urls import path

from brain.v2_views import (
    AIModelListView,
    RoomThreadDetailView,
    RoomThreadListCreateView,
    RoomThreadSendView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/ai/models", AIModelListView.as_view(), name="v2-ai-models"),
    path(
        "orgs/<uuid:org_id>/rooms/<uuid:room_id>/ai/threads",
        RoomThreadListCreateView.as_view(),
        name="v2-ai-threads",
    ),
    path(
        "orgs/<uuid:org_id>/ai/threads/<int:thread_id>",
        RoomThreadDetailView.as_view(),
        name="v2-ai-thread",
    ),
    path(
        "orgs/<uuid:org_id>/ai/threads/<int:thread_id>/send",
        RoomThreadSendView.as_view(),
        name="v2-ai-thread-send",
    ),
]
