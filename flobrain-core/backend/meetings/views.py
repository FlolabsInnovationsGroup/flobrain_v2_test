from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from meetings.models import Meeting, MeetingSummary, Recording
from meetings.providers import create_join_url
from meetings.serializers import ActionItemConfirmSerializer, MeetingCreateSerializer
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from rooms.services import user_can_access_room
from rooms.views import _room_or_404
from tasks.models import Task, TaskAssignment


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def meeting_payload(m, user=None):
    from meetings import livekit
    from organizations.permissions.engine import can

    return {
        "can_manage": bool(user and can(user, "meeting.manage", m.room.team or m.org)),
        "id": str(m.id),
        "title": m.title,
        "join_url": m.join_url or None,
        "started_at": m.started_at.isoformat() if m.started_at else None,
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "call_available": livekit.configured() and m.ended_at is None,
        "recording": bool(m.recording_egress_id),
        "has_summary": MeetingSummary.objects.filter(meeting=m).exists(),
    }


def _voice_ok(request, org):
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    return effective_flag(org, membership, "voice_video", default=False)


class MeetingListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.view").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        rows = Meeting.objects.filter(org=org, room=room).order_by("-started_at")
        return Response([meeting_payload(row, request.user) for row in rows.select_related("room__team", "org")])

    def post(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.manage").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        serializer = MeetingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meeting = Meeting.objects.create(
            org=org,
            room=room,
            title=serializer.validated_data.get("title") or "Meeting",
            created_by=request.user,
            join_url="",
        )
        if _voice_ok(request, org):
            meeting.join_url = create_join_url(str(meeting.id))
            if meeting.join_url:
                meeting.save(update_fields=["join_url"])
        return Response(meeting_payload(meeting, request.user), status=201)


class RecordingListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.view").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        qs = Recording.objects.filter(org=org, meeting__room=room)
        ordering = request.query_params.get("ordering") or "-recorded_at"
        if ordering not in {"recorded_at", "-recorded_at"}:
            ordering = "-recorded_at"
        qs = qs.order_by(ordering)
        paginator = V2PageNumberPagination()
        paginator.page_size = 10
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            [
                {
                    "id": str(row.id),
                    "play_url": row.play_url,
                    "recorded_at": row.recorded_at.isoformat(),
                    "meeting": str(row.meeting_id),
                    "source": row.source,
                    "duration_seconds": row.duration_seconds,
                    "transcript_status": row.transcript_status,
                    "transcript_error": row.transcript_error,
                    "speaker": row.speaker_name,
                }
                for row in page
            ]
        )


class RecordingTranscribeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, recording_id):
        from organizations.permissions.engine import can

        org = _org(org_id)
        request.org = org
        recording = get_object_or_404(Recording.objects.select_related("meeting__room__team"), pk=recording_id, org=org)
        if not user_can_access_room(request.user, recording.meeting.room):
            raise NotFound()
        if not can(request.user, "meeting.manage", recording.meeting.room.team or org):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        from meetings import asr, pipeline

        if not asr.configured():
            return Response({"error": "not_implemented", "details": "Transcription is not set up (ASR_BACKEND)"}, status=501)
        if not recording.storage_key:
            return Response({"error": "invalid", "details": "This recording has no audio file"}, status=400)
        if recording.transcript_status in ("queued", "running") and not pipeline.is_stuck(recording):
            return Response({"error": "conflict", "details": "Already transcribing"}, status=409)
        if not pipeline.queue_transcription(recording):
            return Response({"error": "not_implemented", "details": "The job worker is not running"}, status=501)
        return Response({"status": "queued"}, status=202)


class TranscriptView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, recording_id):
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.view").has_permission(request, self)
        recording = get_object_or_404(Recording, pk=recording_id, org=org)
        if not user_can_access_room(request.user, recording.meeting.room):
            raise NotFound()
        transcript = getattr(recording, "transcript", None)
        if transcript is None:
            return Response({"error": "not_found", "details": "No transcript"}, status=404)
        return Response({"text": transcript.text, "segments": transcript.segments})


class MeetingSummarizeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, meeting_id):
        from organizations.permissions.engine import can

        org = _org(org_id)
        request.org = org
        meeting = get_object_or_404(Meeting.objects.select_related("org", "room", "room__team"), pk=meeting_id, org=org)
        if not user_can_access_room(request.user, meeting.room):
            raise NotFound()
        if not can(request.user, "meeting.manage", meeting.room.team or org):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        from meetings import pipeline

        ok, code = pipeline.summarize(meeting, request.user)
        if ok:
            return Response({"status": "done"})
        statuses = {"no_transcript": 409, "not_configured": 501, "private_only": 409, "budget_exceeded": 429}
        return Response({"error": code, "details": SUMMARY_ERRORS.get(code, "The model could not summarize this meeting")}, status=statuses.get(code, 502))


SUMMARY_ERRORS = {
    "no_transcript": "Transcribe a recording first",
    "not_configured": "No AI model is set up",
    "private_only": "Your organization only allows self-hosted models",
    "budget_exceeded": "The org's monthly AI budget is used up",
}


class MeetingTranscriptView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, meeting_id):
        """The whole meeting in time order, with speakers when the call was inside FloBrain."""
        from meetings import pipeline

        org = _org(org_id)
        request.org = org
        HasPerm("meeting.view").has_permission(request, self)
        meeting = get_object_or_404(Meeting, pk=meeting_id, org=org)
        if not user_can_access_room(request.user, meeting.room):
            raise NotFound()
        rows = pipeline.merged_transcript(meeting)
        return Response({"segments": rows[:10000], "speakers": sorted({r["speaker"] for r in rows if r["speaker"]})})


class MeetingSummaryView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, meeting_id):
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.view").has_permission(request, self)
        meeting = get_object_or_404(Meeting, pk=meeting_id, org=org)
        if not user_can_access_room(request.user, meeting.room):
            raise NotFound()
        summary = getattr(meeting, "summary", None)
        if summary is None:
            return Response({"error": "not_found", "details": "No summary"}, status=404)
        return Response(
            {"text": summary.text, "decisions": summary.decisions, "action_items": summary.action_items}
        )


class ActionItemToTaskView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, meeting_id, item_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.write").has_permission(request, self)
        meeting = get_object_or_404(Meeting, pk=meeting_id, org=org)
        if not user_can_access_room(request.user, meeting.room):
            raise NotFound()
        serializer = ActionItemConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data.get("confirm"):
            return Response({"error": "confirmation_required", "details": "Human confirm is required"}, status=400)
        from django.db import transaction as db_tx

        from organizations.models import OrgMembership

        data = serializer.validated_data
        assignee = request.user
        if data.get("assignee_id"):
            membership = OrgMembership.objects.filter(org=org, user_id=data["assignee_id"], employment_status="active").select_related("user").first()
            if membership is None:
                return Response({"error": "invalid", "details": "The assignee must be an active member"}, status=400)
            assignee = membership.user
        with db_tx.atomic():
            summary = get_object_or_404(MeetingSummary.objects.select_for_update(), meeting=meeting)
            items = list(summary.action_items or [])
            index = next((i for i, row in enumerate(items) if isinstance(row, dict) and str(row.get("id")) == str(item_id)), None)
            if index is None:
                return Response({"error": "not_found", "details": "Action item not found"}, status=404)
            item = items[index]
            existing = item.get("task_id") and Task.objects.filter(org=org, pk=item["task_id"]).first()
            if existing:
                return Response({"error": "conflict", "details": "Already a task", "id": str(existing.id), "title": existing.title}, status=409)
            task = Task.objects.create(
                org=org,
                title=str(item.get("title") or item.get("text") or "Action item")[:200],
                description=f"From the meeting “{meeting.title}”.",
                created_by=request.user,
                team=meeting.room.team,
                room=meeting.room,
                due_on=data.get("due_on"),
            )
            TaskAssignment.objects.get_or_create(task=task, user=assignee)
            items[index] = {**item, "task_id": str(task.id)}
            summary.action_items = items
            summary.save(update_fields=["action_items"])
        return Response({"id": str(task.id), "title": task.title, "assignee_id": str(assignee.id)}, status=201)


class MeetingBotView(V2APIView):
    """Invite the meeting bot (meeting.manage in the room, host consent required)."""

    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, room_id, meeting_id):
        from django.utils import timezone as tz

        from meetings import bot
        from meetings.models import MeetingBotSession
        from organizations.flags import effective_flag
        from organizations.models import OrgMembership
        from organizations.permissions.engine import can
        from organizations.services.core import audit
        from rooms.models import RoomMessage
        from rooms.services import user_can_access_room

        org = _org(org_id)
        request.org = org
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if not effective_flag(org, membership, "meeting_bot", default=False):
            return Response({"error": "not_implemented", "details": "The meeting bot is not enabled"}, status=501)
        meeting = Meeting.objects.filter(org=org, room_id=room_id, pk=meeting_id).select_related("room").first()
        if meeting is None or not user_can_access_room(request.user, meeting.room):
            return Response({"error": "not_found"}, status=404)
        if not can(request.user, "meeting.manage", meeting.room.team or org):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        data = request.data if isinstance(request.data, dict) else {}
        platform, url = data.get("platform"), str(data.get("meeting_url") or "")
        if platform not in MeetingBotSession.PLATFORMS or not bot.valid_url(platform, url):
            return Response({"error": "invalid", "details": "A Zoom, Google Meet or Teams meeting link is required"}, status=400)
        if data.get("host_consent") is not True:
            return Response({"error": "invalid", "details": "Confirm that the host agrees to recording"}, status=400)
        if data.get("proactive_answers") is True:
            return Response({"error": "invalid", "details": "Proactive answers are off until every participant is known to be a member"}, status=400)
        if not bot.configured():
            return Response({"error": "not_configured", "details": "The meeting assistant is not set up (MEETING_BOT_VENDOR=self_hosted and a running meeting-bot service)"}, status=501)
        session = MeetingBotSession.objects.create(
            org=org, meeting=meeting, platform=platform, meeting_url=url, consent_confirmed_by=request.user
        )
        RoomMessage.objects.create(room=meeting.room, author=request.user, body=bot.NOTICE.format(title=meeting.title))
        MeetingBotSession.objects.filter(pk=session.pk).update(recording_notice_sent_at=tz.now())
        audit(request.user, "meeting_bot.invite", target=session, payload={"platform": platform}, request=request, org=org)
        return Response({"id": str(session.id), "status": session.status}, status=201)
