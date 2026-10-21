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
        return Response(
            [{"id": str(row.id), "title": row.title, "join_url": row.join_url or None} for row in rows]
        )

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
        return Response({"id": str(meeting.id), "title": meeting.title, "join_url": meeting.join_url or None}, status=201)


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
                }
                for row in page
            ]
        )


class RecordingTranscribeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, recording_id):
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.manage").has_permission(request, self)
        recording = get_object_or_404(Recording, pk=recording_id, org=org)
        if not user_can_access_room(request.user, recording.meeting.room):
            raise NotFound()
        return Response(
            {"error": "not_implemented", "details": "Transcription is not implemented"},
            status=501,
        )


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
        org = _org(org_id)
        request.org = org
        HasPerm("meeting.manage").has_permission(request, self)
        meeting = get_object_or_404(Meeting, pk=meeting_id, org=org)
        if not user_can_access_room(request.user, meeting.room):
            raise NotFound()
        return Response(
            {"error": "not_implemented", "details": "Meeting summary is not implemented"},
            status=501,
        )


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
        summary = get_object_or_404(MeetingSummary, meeting=meeting)
        item = next((row for row in summary.action_items if str(row.get("id")) == str(item_id)), None)
        if item is None:
            return Response({"error": "not_found", "details": "Action item not found"}, status=404)
        task = Task.objects.create(
            org=org,
            title=str(item.get("title") or "Action item")[:200],
            created_by=request.user,
            team=meeting.room.team,
        )
        TaskAssignment.objects.get_or_create(task=task, user=request.user)
        return Response({"id": str(task.id), "title": task.title}, status=201)
