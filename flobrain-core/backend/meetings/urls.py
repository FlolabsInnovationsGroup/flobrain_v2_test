from django.urls import path

from meetings.views import (
    ActionItemToTaskView,
    MeetingBotView,
    MeetingListCreateView,
    MeetingSummarizeView,
    MeetingSummaryView,
    MeetingTranscriptView,
    RecordingListView,
    RecordingTranscribeView,
    TranscriptView,
)

from meetings import views_bot_worker as botw
from meetings import views_call as call

urlpatterns = [
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/join", call.JoinView.as_view(), name="v2-meeting-join"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/state", call.StateView.as_view(), name="v2-meeting-state"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/recording", call.RecordingControlView.as_view(), name="v2-meeting-recording"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/end", call.EndView.as_view(), name="v2-meeting-end"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/recordings", call.RecordingUploadView.as_view(), name="v2-meeting-upload"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/transcript", MeetingTranscriptView.as_view(), name="v2-meeting-transcript"),
    path("livekit/webhook", call.LiveKitWebhookView.as_view(), name="v2-livekit-webhook"),
    path("workers/meeting-bots/claim", botw.ClaimView.as_view(), name="v2-bot-claim"),
    path("workers/meeting-bots/<uuid:session_id>/status", botw.StatusView.as_view(), name="v2-bot-status"),
    path("workers/meeting-bots/<uuid:session_id>/audio", botw.AudioView.as_view(), name="v2-bot-audio"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/bot-sessions", call.BotSessionsView.as_view(), name="v2-bot-sessions"),
    path("orgs/<uuid:org_id>/meetings/<uuid:meeting_id>/bot-sessions/<uuid:session_id>/cancel", call.BotCancelView.as_view(), name="v2-bot-cancel"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/meetings", MeetingListCreateView.as_view(), name="v2-meetings"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/recordings", RecordingListView.as_view(), name="v2-recordings"),
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/meetings/<uuid:meeting_id>/bot", MeetingBotView.as_view(), name="v2-meeting-bot"),
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
