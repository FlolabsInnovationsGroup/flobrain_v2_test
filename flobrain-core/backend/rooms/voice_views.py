"""Voice note endpoints (W7, flag ``voice_notes``). See docs/v2/features/VOICE.md.

- ``POST orgs/{org}/rooms/{room}/voice`` (multipart ``file``, optional ``duration``, ``language``)
- ``GET  orgs/{org}/rooms/{room}/voice[?translate_to=xx]``: voice notes in the room
- ``GET  orgs/{org}/rooms/{room}/voice/{id}/audio``: the audio, to people who can read the room
- ``POST orgs/{org}/rooms/{room}/voice/{id}/retry``: the author queues a failed transcript again
- ``POST orgs/{org}/buddies/voice-input`` (multipart ``file``): a transcript only, nothing kept
"""

import os
import tempfile

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from brain.throttles import AISendThrottle
from core_v2.throttles import V2UserThrottle
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit
from rooms import voice
from rooms.models import VoiceNote
from rooms.serializers import TranslateQuerySerializer
from rooms.services import notify_new_message
from rooms.views import _org, _room_or_404

FLAG = "voice_notes"
LIST_LIMIT = 200


def _flag_off(org, user):
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if effective_flag(org, membership, FLAG, default=False):
        return None
    return Response({"error": "not_implemented", "details": "Voice notes are not enabled"}, status=501)


def _impersonated(request) -> bool:
    from console.impersonation import is_impersonated

    return is_impersonated(request)


def _invalid(exc):
    return Response({"error": "invalid", "code": exc.code, "details": voice.MESSAGES.get(exc.code, exc.code)}, status=400)


def _read_upload(request):
    """(bytes, declared type) of the ``file`` field, reading at most one byte past the limit."""
    upload = request.FILES.get("file")
    if upload is None:
        raise voice.VoiceError("empty")
    if upload.size is not None and upload.size > voice.MAX_BYTES:
        raise voice.VoiceError("too_large")
    try:
        data = upload.read(voice.MAX_BYTES + 1)
    finally:
        upload.close()
    if len(data) > voice.MAX_BYTES:
        raise voice.VoiceError("too_large")
    return data, getattr(upload, "content_type", "") or ""


def _gate(view, request, org_id, room_id, perm="chat.use"):
    org = _org(org_id)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    off = _flag_off(org, request.user)
    if off is not None:
        return org, None, off
    room = _room_or_404(request.user, org, room_id)
    return org, room, None


def _note_or_404(org, room, voice_id):
    return get_object_or_404(
        VoiceNote.objects.select_related("message", "message__room"),
        pk=voice_id, org=org, message__room=room, message__deleted_at__isnull=True,
    )


class RoomVoiceView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    parser_classes = [MultiPartParser, FormParser]

    def get_throttles(self):
        if self.request.method == "POST":
            return [V2UserThrottle(), AISendThrottle()]
        return [V2UserThrottle()]

    @extend_schema(summary="Voice notes in a room, optionally translated to the reader's language")
    def get(self, request, org_id, room_id):
        org, room, error = _gate(self, request, org_id, room_id)
        if error:
            return error
        query = TranslateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        language = query.validated_data.get("translate_to") or ""
        notes = list(
            VoiceNote.objects.filter(org=org, message__room=room, message__deleted_at__isnull=True)
            .select_related("message")
            .order_by("-message__created_at")[:LIST_LIMIT]
        )
        translations, note = {}, ""
        if language:
            translations, note = self._translate(request, org, notes, language)
        rows = [voice.payload(n, translations.get(n.message_id)) for n in notes]
        body = {"results": rows}
        if note:
            body["translation_note"] = note
        return Response(body)

    def _translate(self, request, org, notes, language):
        if _impersonated(request):  # translation spends money and sends room text to a model
            return {}, "impersonation_read_only"
        from brain.llm import direct
        from brain.llm.policy import check_ai

        if not direct.is_configured():
            return {}, "not_configured"
        if check_ai(org, "direct"):
            return {}, "private_only"
        allow = True
        if voice.needs_translation_calls(notes, language):
            allow = AISendThrottle().allow_request(request, self)
        return voice.translations_for(notes, language, request.user, org, allow_calls=allow), ("" if allow else "deferred")

    @extend_schema(summary="Post a voice note (multipart file, up to 5 minutes and 10 MB)")
    def post(self, request, org_id, room_id):
        from content_studio import storage

        org, room, error = _gate(self, request, org_id, room_id)
        if error:
            return error
        if _impersonated(request):
            return Response({"error": "permission_denied", "details": "impersonation_read_only"}, status=403)
        if not storage.is_configured():
            return Response({"error": "not_implemented", "details": "File storage is not set up"}, status=501)
        try:
            data, mime = _read_upload(request)
            declared = voice.parse_declared_duration(request.data.get("duration"))
            hint = voice.parse_hint(request.data.get("language")) or voice.default_hint(org, request.user)
            info = voice.validate(data, mime, declared)
            note = voice.create_room_voice_note(room, request.user, data, info, hint=hint)
        except voice.VoiceError as exc:
            if exc.code == "storage_unavailable":
                return Response({"error": "not_implemented", "details": "File storage is not set up"}, status=501)
            return _invalid(exc)
        notify_new_message(room, note.message, request.user)
        # Ids and sizes only: never audio or text in the audit log.
        audit(request.user, "room.voice_note.create", target=note.message, org=org, request=request,
              payload={"room": str(room.id), "seconds": info["duration"], "bytes": len(data)})
        note.refresh_from_db()
        note.message.refresh_from_db()
        return Response(voice.payload(note), status=201)


class RoomVoiceAudioView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="The audio of a voice note (room readers only)")
    def get(self, request, org_id, room_id, voice_id):
        from content_studio import storage

        org, room, error = _gate(self, request, org_id, room_id)
        if error:
            return error
        if _impersonated(request):
            return Response({"error": "permission_denied", "details": "impersonation_read_only"}, status=403)
        note = _note_or_404(org, room, voice_id)
        data = storage.read_bytes(note.storage_key, voice.MAX_BYTES) if note.storage_key else None
        content_type = note.content_type
        if data is None and note.is_demo:
            data, content_type = voice.demo_audio(note.duration_seconds or 10, seed=note.id.int % 7), "audio/wav"
        if data is None:
            return Response({"error": "not_found", "details": "The audio is no longer stored"}, status=404)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Length"] = str(len(data))
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        ext = {ctype: ext for ctype, ext in voice.FAMILY.values()}.get(content_type, "wav")
        response["Content-Disposition"] = f'inline; filename="voice-{note.id}.{ext}"'
        return response


class RoomVoiceRetryView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="Try a failed transcript again (the author)")
    def post(self, request, org_id, room_id, voice_id):
        org, room, error = _gate(self, request, org_id, room_id)
        if error:
            return error
        note = _note_or_404(org, room, voice_id)
        if note.message.author_id != request.user.id or _impersonated(request):
            return Response({"error": "permission_denied", "details": "Only the author can retry"}, status=403)
        if not voice.retry(note):
            return Response({"error": "invalid", "details": "Only a failed transcript with its audio can be retried"}, status=409)
        note.refresh_from_db()
        return Response(voice.payload(note))


class BuddyVoiceInputView(V2APIView):
    """Speech to text for the buddy composer. The person reviews the text before sending it."""

    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle, AISendThrottle]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(summary="Transcribe a short recording for the buddy composer (nothing is stored)")
    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("ai.use").has_permission(request, self)
        off = _flag_off(org, request.user)
        if off is not None:
            return off
        if _impersonated(request):
            return Response({"error": "permission_denied", "details": "impersonation_read_only"}, status=403)
        try:
            data, mime = _read_upload(request)
            declared = voice.parse_declared_duration(request.data.get("duration"))
            hint = voice.parse_hint(request.data.get("language")) or voice.default_hint(org, request.user)
            info = voice.validate(data, mime, declared)
        except voice.VoiceError as exc:
            return _invalid(exc)
        try:
            out = transcribe_via_temp_file(data, info, hint, request.user)
        except voice.VoiceError as exc:
            if exc.code == "not_configured":
                return Response({"error": "not_implemented", "details": "Speech to text is not set up"}, status=501)
            if exc.code in voice.MESSAGES:
                return _invalid(exc)
            return Response({"error": "unavailable", "code": exc.code, "details": "Speech to text did not answer. Try again."}, status=503)
        text = (out["text"] or "").strip()
        if not text:
            return Response({"error": "invalid", "code": "no_speech", "details": "No speech was heard."}, status=400)
        return Response({"text": text, "language": out["language"], "demo": out["demo"], "duration": info["duration"] or out["duration"]})


def transcribe_via_temp_file(data: bytes, info: dict, hint: str, user) -> dict:
    """Write the clip to a private temp file only while it is transcribed, then delete it.

    ``VOICE_TMP_DIR`` (optional) picks the folder; the file is removed even when Whisper fails.
    """
    folder = getattr(settings, "VOICE_TMP_DIR", None) or None
    fd, path = tempfile.mkstemp(prefix="voice-", suffix="." + info["ext"], dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        with open(path, "rb") as fh:
            audio = fh.read()
        return voice.recognize(audio, info, hint=hint, user=user)
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
