from django.urls import path

from meetings.views import (
    ActionItemToTaskView,
    MeetingListCreateView,
    MeetingSummarizeView,
    MeetingSummaryView,
    RecordingListView,
    RecordingTranscribeView,
    TranscriptView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/meetings", MeetingListCreateView.as_view(), name="v2-meetings"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/recordings", RecordingListView.as_view(), name="v2-recordings"),
    path(
        "orgs/<uuid:org_id>/recordings/<uuid:recording_id>/transcribe",
        RecordingTranscribeView.as_view(),
        name="v2-transcribe",
    ),
    path(
        "orgs/<uuid:org_id>/recordings/<uuid:recording_id>/transcript",
        TranscriptView.as_view(),
        name="v2-transcript",
    ),
    path(
        "orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/summarize",
        MeetingSummarizeView.as_view(),
        name="v2-summarize",
    ),
    path(
        "orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/summary",
        MeetingSummaryView.as_view(),
        name="v2-summary",
    ),
    path(
        "orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/action-items/<str:item_id>/to-task",
        ActionItemToTaskView.as_view(),
        name="v2-action-to-task",
    ),
]
