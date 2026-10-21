"""Worker API for our own meeting bot. ``Authorization: Worker <token>`` with a ``meeting_bot`` token only.

- ``POST /api/v2/workers/meeting-bots/claim``: one requested session, or 204
- ``POST /api/v2/workers/meeting-bots/{id}/status {status, error?}``: progress; the answer says whether to leave
- ``POST /api/v2/workers/meeting-bots/{id}/audio`` (multipart ``file``): the recording, then transcription
A worker only sees the session it holds. Sessions whose worker stops reporting are failed, never rejoined.
"""

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from meetings import bot, pipeline
from meetings.models import MeetingBotSession, Recording
from meetings.views_call import AUDIO_TYPES
from workers.authentication import IsMeetingBotWorker
from workers.views import WorkerAPIView

LIVE = ("joining", "waiting_admission", "in_call", "uploading")
FROM_WORKER = ("joining", "waiting_admission", "in_call", "uploading", "done", "failed")


class BotWorkerView(WorkerAPIView):
    permission_classes = [IsMeetingBotWorker]


REQUEST_EXPIRES_MINUTES = 30  # a link can be reused for a later meeting: never join on an old request
ADMISSION_MINUTES = 15  # the bot waits up to 10 minutes in the lobby, reporting as it goes


def fail_stale():
    now = timezone.now()
    MeetingBotSession.objects.filter(status__in=["in_call", "uploading"], heartbeat_at__lt=now - timedelta(minutes=bot.STALE_MINUTES)).update(
        status="failed", error="worker_lost", left_at=now
    )
    MeetingBotSession.objects.filter(status__in=["joining", "waiting_admission"], heartbeat_at__lt=now - timedelta(minutes=ADMISSION_MINUTES)).update(
        status="failed", error="worker_lost", left_at=now
    )
    MeetingBotSession.objects.filter(status="requested", created_at__lt=now - timedelta(minutes=REQUEST_EXPIRES_MINUTES)).update(
        status="failed", error="expired", left_at=now
    )


def _held(request, session_id):
    return MeetingBotSession.objects.select_related("meeting", "meeting__room").filter(pk=session_id, worker=request.auth).first()


def _gone():
    return Response({"error": "not_found", "details": "Session not held by this worker"}, status=404)


class ClaimView(BotWorkerView):
    @extend_schema(summary="Claim one meeting the bot should join")
    def post(self, request):
        if not bot.configured():
            return Response(status=204)
        fail_stale()
        with transaction.atomic():
            qs = MeetingBotSession.objects.filter(status="requested", meeting__ended_at__isnull=True).order_by("created_at")
            if connection.vendor == "postgresql":
                qs = qs.select_for_update(skip_locked=True, of=("self",))
            session = qs.first()
            if session is None:
                return Response(status=204)
            now = timezone.now()
            if not MeetingBotSession.objects.filter(pk=session.pk, status="requested").update(status="joining", worker=request.auth, heartbeat_at=now):
                return Response(status=204)
        session = MeetingBotSession.objects.select_related("meeting").get(pk=session.pk)
        return Response(
            {
                "session": str(session.id),
                "platform": session.platform,
                "meeting_url": session.meeting_url,
                "title": session.meeting.title,
                "bot_name": bot.BOT_NAME,
                "announce": bot.ANNOUNCE,
                "max_minutes": int(getattr(settings, "MEETING_BOT_MAX_MINUTES", 120)),
                "leave_when_alone_minutes": 2,
                "admission_timeout_minutes": 10,
            }
        )


class StatusView(BotWorkerView):
    @extend_schema(summary="Report bot progress; answers whether to leave now")
    def post(self, request, session_id):
        session = _held(request, session_id)
        if session is None:
            return _gone()
        data = request.data if isinstance(request.data, dict) else {}
        status = data.get("status")
        if status not in FROM_WORKER:
            return Response({"error": "invalid", "details": f"status must be one of {', '.join(FROM_WORKER)}"}, status=400)
        if session.status in ("done", "failed", "cancelled") and not (session.status == "cancelled" and status in ("uploading", "done", "failed")):
            return Response({"status": session.status, "leave": True})
        if session.status == "cancelled":
            # Told to leave: the bot may still upload what it recorded before, then it stops.
            MeetingBotSession.objects.filter(pk=session.pk).update(heartbeat_at=timezone.now())
            return Response({"status": "cancelled", "leave": True})
        now = timezone.now()
        fields = {"status": status, "heartbeat_at": now}
        if status == "in_call" and not session.joined_at:
            fields["joined_at"] = now
        if status in ("done", "failed"):
            fields["left_at"] = now
            fields["error"] = str(data.get("error") or "")[:120]
        MeetingBotSession.objects.filter(pk=session.pk).update(**fields)
        leave = session.meeting.ended_at is not None
        return Response({"status": status, "leave": leave})


class AudioView(BotWorkerView):
    parser_classes = [MultiPartParser]

    @extend_schema(summary="Upload the bot's recording; transcription starts")
    def post(self, request, session_id):
        from content_studio import storage
        from meetings import asr

        session = _held(request, session_id)
        if session is None:
            return _gone()
        if session.recording_id:
            return Response({"error": "conflict", "details": "Audio already uploaded"}, status=409)
        # Only audio from a session that really joined and wasn't failed; a removal during the lobby wins.
        if session.status == "failed" or session.joined_at is None or (session.status == "cancelled" and session.left_at and session.left_at <= session.joined_at):
            return Response({"error": "conflict", "details": "This session can't take audio"}, status=409)
        upload = request.FILES.get("file")
        limit = int(getattr(settings, "MEETING_UPLOAD_MAX_MB", 500)) << 20
        ctype = (getattr(upload, "content_type", "") or "").split(";")[0].lower()
        if upload is None or ctype not in AUDIO_TYPES or upload.size > limit:
            return Response({"error": "invalid", "details": "An audio file is required"}, status=400)
        meeting = session.meeting
        recording = Recording.objects.create(org_id=session.org_id, meeting=meeting, source="bot", content_type=ctype)
        key = f"meetings/{session.org_id}/{meeting.id}/{recording.id}.{AUDIO_TYPES[ctype]}"
        if not storage.put_file(key, upload, ctype):
            recording.delete()
            return Response({"error": "not_implemented", "details": "File storage is not set up"}, status=501)
        Recording.objects.filter(pk=recording.pk).update(storage_key=key)
        recording.storage_key = key
        fields = {"recording": recording, "left_at": timezone.now(), "heartbeat_at": timezone.now()}
        if session.status != "cancelled":
            fields["status"] = "done"
        MeetingBotSession.objects.filter(pk=session.pk).update(**fields)
        if asr.configured():
            pipeline.queue_transcription(recording)
        return Response({"recording": str(recording.id)}, status=201)
