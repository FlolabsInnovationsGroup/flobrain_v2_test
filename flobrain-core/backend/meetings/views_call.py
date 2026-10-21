"""Calls inside FloBrain (LiveKit), recording with a notice, uploads, and the LiveKit webhook.

- ``POST /orgs/{org}/meetings/{id}/join``: a short-lived call token (room access + ``voice_video``)
- ``POST /orgs/{org}/meetings/{id}/recording {action: start|stop}``: ``meeting.manage`` only; starting
  posts a notice in the room and every participant sees a recording banner
- ``POST /orgs/{org}/meetings/{id}/end``: ``meeting.manage``; ends the call for everyone
- ``POST /orgs/{org}/meetings/{id}/recordings`` (multipart ``file``): add audio from elsewhere
- ``POST /api/v2/livekit/webhook``: signed by LiveKit; a finished recording starts transcription
"""

import re

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from core_v2.views import V2APIView, V2PublicAPIView
from meetings import livekit, pipeline
from meetings import demo as meeting_demo
from meetings import recording as call_recording
from meetings.models import Meeting, Recording
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit
from rooms.models import RoomMessage
from rooms.services import user_can_access_room

AUDIO_TYPES = {
    "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav",
    "audio/x-wav": "wav", "audio/webm": "webm", "video/webm": "webm", "video/mp4": "mp4",
}
STARTING = "starting"
DEMO_RECORDING = "demo"
KEY_RE = re.compile(r"meetings/[0-9a-f-]{36}/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,120}")
RECORDING_NOTICE = "Recording started by {name}. Everyone in “{title}” sees a recording banner; it will be transcribed and summarized for this room."


def _meeting(request, org_id, meeting_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    meeting = Meeting.objects.filter(org=org, pk=meeting_id).select_related("room", "room__team").first()
    if meeting is None or not user_can_access_room(request.user, meeting.room):
        return org, None, Response({"error": "not_found"}, status=404)
    if not can(request.user, "meeting.view", meeting.room.team or org):
        return org, None, Response({"error": "permission_denied", "details": "Missing permission: meeting.view"}, status=403)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, "voice_video", default=False):
        return org, None, Response({"error": "not_implemented", "details": "Calls are not enabled"}, status=501)
    return org, meeting, None


def _manager(request, meeting, org):
    return can(request.user, "meeting.manage", meeting.room.team or org)


def _impersonated(request):
    from console.impersonation import is_impersonated

    return is_impersonated(request)


class JoinView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="A call token for this meeting (LiveKit)")
    def post(self, request, org_id, meeting_id):
        org, meeting, err = _meeting(request, org_id, meeting_id)
        if err:
            return err
        if _impersonated(request):
            return Response({"error": "forbidden", "details": "Support sessions can't join calls"}, status=403)
        if meeting.ended_at:
            return Response({"error": "conflict", "details": "This meeting has ended"}, status=409)
        if meeting_demo.calls():
            people = meeting_demo.participants(meeting, request.user)
            return Response(
                {
                    "demo": True,
                    "room": livekit.room_name(meeting),
                    "recording": bool(meeting.recording_egress_id),
                    "can_manage": _manager(request, meeting, org),
                    "participants": [name for _, name in people],
                }
            )
        if not livekit.configured():
            return Response({"error": "not_configured", "details": "The call server is not set up (LIVEKIT_URL)"}, status=501)
        try:
            livekit.ensure_room(meeting)
        except livekit.LiveKitError as exc:
            return Response({"error": "provider_unavailable", "details": f"The call server didn't answer ({exc})"}, status=502)
        return Response(
            {
                "url": settings.LIVEKIT_URL,
                "token": livekit.join_token(meeting, request.user),
                "room": livekit.room_name(meeting),
                "recording": bool(meeting.recording_egress_id),
                "can_manage": _manager(request, meeting, org),
            }
        )


class StateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Whether the call is being recorded (polled by the call page)")
    def get(self, request, org_id, meeting_id):
        org, meeting, err = _meeting(request, org_id, meeting_id)
        if err:
            return err
        return Response({"recording": bool(meeting.recording_egress_id), "ended": meeting.ended_at is not None})


class RecordingControlView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Start or stop recording (meeting.manage; a notice goes to the room first)")
    def post(self, request, org_id, meeting_id):
        org, meeting, err = _meeting(request, org_id, meeting_id)
        if err:
            return err
        if not _manager(request, meeting, org) or _impersonated(request):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        demo_call = meeting_demo.calls()
        if not livekit.configured() and not demo_call:
            return Response({"error": "not_configured", "details": "The call server is not set up"}, status=501)
        action = (request.data if isinstance(request.data, dict) else {}).get("action")
        if action == "start":
            if meeting.ended_at:
                return Response({"error": "conflict", "details": "This meeting has ended"}, status=409)
            # Claim first, so two clicks can't start two recordings where only one could be stopped.
            if not Meeting.objects.filter(pk=meeting.pk, recording_egress_id="", ended_at__isnull=True).update(recording_egress_id=STARTING):
                return Response({"error": "conflict", "details": "Already recording"}, status=409)
            name = request.user.username or request.user.email.split("@")[0]
            RoomMessage.objects.create(room=meeting.room, author=request.user, body=RECORDING_NOTICE.format(name=name, title=meeting.title))
            try:
                if demo_call:
                    Meeting.objects.filter(pk=meeting.pk).update(recording_egress_id=DEMO_RECORDING, recording_started_at=timezone.now())
                else:
                    call_recording.start(meeting)  # one track per speaker; later speakers join via the webhook
            except livekit.LiveKitError as exc:
                try:
                    call_recording.stop(meeting)
                except livekit.LiveKitError:
                    pass
                Meeting.objects.filter(pk=meeting.pk).update(recording_egress_id="")
                return Response({"error": "provider_unavailable", "details": f"The call server didn't start recording ({exc})"}, status=502)
            Meeting.objects.filter(pk=meeting.pk).update(recording_started_by=request.user)
            audit(request.user, "meeting.recording_start", target=meeting, request=request, org=org)
            return Response({"recording": True})
        if action == "stop":
            if not meeting.recording_egress_id or meeting.recording_egress_id == STARTING:
                return Response({"recording": bool(meeting.recording_egress_id)})
            try:
                if meeting.recording_egress_id == DEMO_RECORDING:
                    meeting_demo.finish_recording(meeting, request.user)
                else:
                    call_recording.stop(meeting)  # a track whose recording already ended counts as stopped
            except livekit.LiveKitError as exc:
                return Response({"error": "provider_unavailable", "details": f"The call server didn't stop recording ({exc})"}, status=502)
            Meeting.objects.filter(pk=meeting.pk).update(recording_egress_id="")
            audit(request.user, "meeting.recording_stop", target=meeting, request=request, org=org)
            return Response({"recording": False})
        return Response({"error": "invalid", "details": "action must be start or stop"}, status=400)


class EndView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="End the call for everyone (meeting.manage)")
    def post(self, request, org_id, meeting_id):
        org, meeting, err = _meeting(request, org_id, meeting_id)
        if err:
            return err
        if not _manager(request, meeting, org) or _impersonated(request):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        if meeting.recording_egress_id == DEMO_RECORDING:
            meeting_demo.finish_recording(meeting, request.user)
        elif livekit.configured():
            try:
                call_recording.stop(meeting)
            except livekit.LiveKitError:
                pass
        if livekit.configured():
            livekit.end_call(meeting)
        Meeting.objects.filter(pk=meeting.pk).update(ended_at=timezone.now(), recording_egress_id="")
        audit(request.user, "meeting.end", target=meeting, request=request, org=org)
        return Response({"ended": True})


class RecordingUploadView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    parser_classes = [MultiPartParser]

    @extend_schema(summary="Add a recording file to a meeting (meeting.manage), then transcribe it")
    def post(self, request, org_id, meeting_id):
        from content_studio import storage

        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        meeting = Meeting.objects.filter(org=org, pk=meeting_id).select_related("room", "room__team").first()
        if meeting is None or not user_can_access_room(request.user, meeting.room):
            return Response({"error": "not_found"}, status=404)
        if not _manager(request, meeting, org) or _impersonated(request):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        if not storage.is_configured():
            return Response({"error": "not_implemented", "details": "File storage is not set up"}, status=501)
        upload = request.FILES.get("file")
        limit = int(getattr(settings, "MEETING_UPLOAD_MAX_MB", 500)) << 20
        ctype = (getattr(upload, "content_type", "") or "").split(";")[0].lower()
        if upload is None or ctype not in AUDIO_TYPES or upload.size > limit:
            return Response({"error": "invalid", "details": f"An audio or video file up to {limit >> 20} MB"}, status=400)
        recording = Recording.objects.create(org=org, meeting=meeting, source="upload", content_type=ctype)
        key = f"meetings/{org.id}/{meeting.id}/{recording.id}.{AUDIO_TYPES[ctype]}"
        if not storage.put_file(key, upload, ctype):
            recording.delete()
            return Response({"error": "not_implemented", "details": "File storage is not set up"}, status=501)
        Recording.objects.filter(pk=recording.pk).update(storage_key=key)
        recording.storage_key = key
        audit(request.user, "meeting.recording_upload", target=recording, request=request, org=org)
        from meetings import asr

        if asr.configured():
            pipeline.queue_transcription(recording)
        return Response({"id": str(recording.id), "transcript_status": "queued" if asr.configured() else "none"}, status=201)


class LiveKitWebhookView(V2PublicAPIView):
    @extend_schema(summary="LiveKit webhook (signed)")
    def post(self, request):
        event = livekit.verify_webhook(request.body, request.headers.get("Authorization", ""))
        if event is None:
            return Response({"error": "unauthorized"}, status=401)
        if event.get("event") == "track_published":
            return Response(_track_published(event))
        if event.get("event") != "egress_ended":
            return Response({"ok": True})
        info = event.get("egressInfo") or event.get("egress_info") or {}
        if not isinstance(info, dict):
            return Response({"ok": True})
        egress_id = str(info.get("egressId") or info.get("egress_id") or "")[:64]
        room = str(info.get("roomName") or info.get("room_name") or "")[:64]
        files = info.get("fileResults") or info.get("file_results") or ([info.get("file")] if info.get("file") else [])
        if not isinstance(files, list):
            return Response({"ok": True})
        if not room.startswith("fb-"):
            return Response({"ok": True})
        meeting = Meeting.objects.filter(pk=room[3:]).select_related("room").first() if _is_uuid(room[3:]) else None
        if meeting is None:
            return Response({"ok": True})
        Meeting.objects.filter(pk=meeting.pk, recording_egress_id=egress_id).update(recording_egress_id="")
        from meetings.models import TrackEgress

        track = TrackEgress.objects.filter(meeting=meeting, egress_id=egress_id).first() if egress_id else None
        speaker_fields = {}
        if track is not None:
            TrackEgress.objects.filter(pk=track.pk, stopped_at__isnull=True).update(stopped_at=timezone.now())
            started = meeting.recording_started_at or track.started_at
            speaker_fields = {
                "egress_id": egress_id,
                "speaker_id": track.participant_identity if _is_uuid(track.participant_identity) and _is_member(meeting, track.participant_identity) else None,
                "speaker_name": track.participant_name[:150],
                "offset_seconds": max(0.0, (track.started_at - started).total_seconds()),
            }
        made = 0
        for f in files:
            if not isinstance(f, dict):
                continue
            key = str(f.get("filename") or f.get("location") or "")[:1000]
            prefix = f"meetings/{meeting.org_id}/{meeting.id}/"
            if prefix not in key:
                continue
            key = key[key.index(prefix):]  # keep only our own key; never a path the event chose
            if not KEY_RE.fullmatch(key) or ".." in key:
                continue
            if Recording.objects.filter(meeting=meeting, storage_key=key).exists():
                continue
            duration = f.get("duration")
            rec = Recording.objects.create(
                org_id=meeting.org_id, meeting=meeting, source="livekit", storage_key=key, content_type="audio/ogg",
                duration_seconds=int(int(duration) / 1_000_000_000) if str(duration or "").isdigit() else None,
                **speaker_fields,
            )
            from meetings import asr

            if asr.configured():
                pipeline.queue_transcription(rec)
            made += 1
        return Response({"ok": True, "recordings": made})


def _is_member(meeting, user_id) -> bool:
    return OrgMembership.objects.filter(org_id=meeting.org_id, user_id=user_id).exists()


def _track_published(event) -> dict:
    """A participant started publishing a microphone while the call is recorded: record it too."""
    room = event.get("room") if isinstance(event.get("room"), dict) else {}
    name = str(room.get("name") or "")
    participant = event.get("participant") if isinstance(event.get("participant"), dict) else {}
    track = event.get("track") if isinstance(event.get("track"), dict) else {}
    if not name.startswith("fb-") or not _is_uuid(name[3:]) or str(track.get("type", "")).upper() not in ("AUDIO", "0") or not track.get("sid"):
        return {"ok": True}
    # "starting" too: someone who unmutes while recording is being switched on must not be missed.
    meeting = Meeting.objects.filter(pk=name[3:], recording_egress_id__in=[call_recording.TRACKS, STARTING], ended_at__isnull=True).first()
    if meeting is None:
        return {"ok": True}
    try:
        call_recording.record_track(meeting, str(participant.get("identity") or "")[:64], str(participant.get("name") or "")[:150], str(track["sid"])[:64])
    except livekit.LiveKitError:
        return {"ok": False}
    return {"ok": True, "recording_track": True}


def _is_uuid(value):
    import uuid

    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


class BotSessionsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="The assistant's sessions in this meeting")
    def get(self, request, org_id, meeting_id):
        from meetings.models import MeetingBotSession

        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        meeting = Meeting.objects.filter(org=org, pk=meeting_id).select_related("room", "room__team").first()
        if meeting is None or not user_can_access_room(request.user, meeting.room):
            return Response({"error": "not_found"}, status=404)
        rows = list(MeetingBotSession.objects.filter(meeting=meeting).order_by("-created_at")[:20])
        if meeting_demo.bot():
            rows = [meeting_demo.advance_bot(r) for r in rows]
        return Response(
            [
                {"id": str(r.id), "platform": r.platform, "status": r.status, "error": r.error, "created_at": r.created_at.isoformat(), "joined_at": r.joined_at.isoformat() if r.joined_at else None}
                for r in rows
            ]
        )


class BotCancelView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Tell the assistant to leave (meeting.manage)")
    def post(self, request, org_id, meeting_id, session_id):
        from meetings.models import MeetingBotSession

        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        meeting = Meeting.objects.filter(org=org, pk=meeting_id).select_related("room", "room__team").first()
        if meeting is None or not user_can_access_room(request.user, meeting.room):
            return Response({"error": "not_found"}, status=404)
        if not _manager(request, meeting, org) or _impersonated(request):
            return Response({"error": "permission_denied", "details": "Missing permission: meeting.manage"}, status=403)
        updated = MeetingBotSession.objects.filter(pk=session_id, meeting=meeting, status__in=["requested", "joining", "waiting_admission", "in_call"]).update(status="cancelled", left_at=timezone.now())
        audit(request.user, "meeting_bot.cancel", target=meeting, payload={"session": str(session_id)}, request=request, org=org)
        return Response({"cancelled": bool(updated)})
