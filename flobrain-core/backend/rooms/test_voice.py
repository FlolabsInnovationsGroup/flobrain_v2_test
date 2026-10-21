"""W7 voice notes: validation, access, Whisper (mocked at urlopen), translation cache, demo."""

import importlib
import io
import json
import os
import shutil
import tempfile
import urllib.error
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, Project, ProjectMembership, Team, TeamMembership
from rooms import voice
from rooms.models import MessageTranslation, RoomMessage, VoiceNote
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User

WHISPER = "http://whisper.internal:8000"
DIRECT = {
    "AI_DIRECT_BASE_URL": "https://provider.example",
    "AI_DIRECT_API_KEY": "test-key-not-live",
    "AI_DIRECT_MODEL_ALLOWLIST": "qwen",
    "AI_DIRECT_DEFAULT_MODEL": "qwen",
}


# ------------------------------------------------------------ synthetic recordings


def _size(n):
    return b"\x01" + n.to_bytes(7, "big")


UNKNOWN = b"\x01\xff\xff\xff\xff\xff\xff\xff"


def _el(eid, payload):
    return eid + _size(len(payload)) + payload


def webm(seconds, with_duration=False):
    """A browser-style WebM: unknown-size segment and clusters, no Duration unless asked."""
    info = _el(b"\x2a\xd7\xb1", (1_000_000).to_bytes(3, "big"))
    if with_duration:
        info += _el(b"\x44\x89", __import__("struct").pack(">d", seconds * 1000))
    out = _el(b"\x1a\x45\xdf\xa3", _el(b"\x42\x82", b"webm")) + b"\x18\x53\x80\x67" + UNKNOWN + _el(b"\x15\x49\xa9\x66", info)
    t = 0
    while t * 1000 < seconds * 1000:
        blocks = b"".join(
            _el(b"\xa3", b"\x81" + (ms).to_bytes(2, "big", signed=True) + b"\x80" + b"\x00" * 24)
            for ms in range(0, 10_000, 1000)
            if t * 1000 + ms <= seconds * 1000
        )
        out += b"\x1f\x43\xb6\x75" + UNKNOWN + _el(b"\xe7", (t * 1000).to_bytes(4, "big")) + blocks
        t += 10
    return out


def _ogg_page(granule, payload, kind=0, seq=0):
    return (
        b"OggS\x00" + bytes([kind]) + granule.to_bytes(8, "little", signed=True) + b"\x01\x00\x00\x00"
        + seq.to_bytes(4, "little") + b"\x00" * 4 + b"\x01" + bytes([len(payload)]) + payload
    )


def ogg(seconds):
    head = b"OpusHead\x01\x01" + (312).to_bytes(2, "little") + (48000).to_bytes(4, "little") + b"\x00\x00\x00"
    return (
        _ogg_page(0, head, 2) + _ogg_page(0, b"OpusTags" + b"\x00" * 8, 0, 1)
        + _ogg_page(int(seconds * 48000) + 312, b"\x00" * 60, 4, 2)
    )


def mp3(seconds, kbps=32):
    frame = b"\xff\xfb" + bytes([(1 << 4) | (0 << 2), 0x64])  # MPEG-1 layer III, 32 kbps, 44.1 kHz
    body = frame + b"\x00" * int(seconds * kbps * 1000 / 8 - 4)
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + body


def m4a(seconds):
    ftyp = (24).to_bytes(4, "big") + b"ftypM4A " + b"\x00\x00\x00\x00" + b"isom" + b"M4A "
    mvhd_body = b"\x00\x00\x00\x00" + b"\x00" * 8 + (1000).to_bytes(4, "big") + int(seconds * 1000).to_bytes(4, "big") + b"\x00" * 80
    mvhd = (8 + len(mvhd_body)).to_bytes(4, "big") + b"mvhd" + mvhd_body
    moov = (8 + len(mvhd)).to_bytes(4, "big") + b"moov" + mvhd
    return ftyp + moov


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeNetwork:
    """Answers Whisper and the direct AI provider; records every request."""

    def __init__(self, whisper=None, whisper_error=None):
        self.whisper = whisper or {"text": "Hello team", "language": "en", "duration": 3.0}
        self.whisper_error = whisper_error
        self.whisper_calls = []
        self.ai_calls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        if url.startswith(WHISPER):
            self.whisper_calls.append({"url": url, "body": request.data, "headers": dict(request.headers)})
            if self.whisper_error is not None:
                raise self.whisper_error
            return _Body(self.whisper)
        body = json.loads(request.data.decode())
        self.ai_calls.append(body)
        return _Body({
            "model": "qwen",
            "choices": [{"message": {"role": "assistant", "content": "EN:" + body["messages"][-1]["content"][:40]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        })


class VoiceBase(TestCase):
    def setUp(self):
        cache.clear()
        self.tmp = tempfile.mkdtemp(prefix="voice-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        storage = override_settings(CONTENT_STORAGE="local", CONTENT_LOCAL_DIR=self.tmp)
        storage.enable()
        self.addCleanup(storage.disable)
        self.client = APIClient()
        self.org = Organization.objects.create(name="V Org", slug="v-org", settings={"flags": {"voice_notes": True}})
        self.alice = self._member("alice@example.com")
        self.bob = self._member("bob@example.com")
        self.carol = self._member("carol@example.com")  # in the org, not in the room
        team = Team.objects.create(org=self.org, name="Alpha")
        TeamMembership.objects.create(team=team, user=self.alice)
        TeamMembership.objects.create(team=team, user=self.bob)
        self.room = ensure_team_room(team)
        other = Team.objects.create(org=self.org, name="Beta")
        TeamMembership.objects.create(team=other, user=self.carol)
        self.other_room = ensure_team_room(other)
        self.url = f"/api/v2/orgs/{self.org.id}/rooms/{self.room.id}/voice"

    def _member(self, email):
        user = User.objects.create(email=email, password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=user, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE)
        return user

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _upload(self, data, mime="audio/webm", url=None, **fields):
        file = SimpleUploadedFile("voice.bin", data, content_type=mime)
        return self.client.post(url or self.url, {"file": file, **fields}, format="multipart")


@override_settings(ASR_BACKEND="http", ASR_BASE_URL=WHISPER)
class UploadValidationTests(VoiceBase):
    def test_flag_off_everywhere(self):
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self._auth(self.alice)
        self.assertEqual(self._upload(webm(3)).status_code, 501)
        self.assertEqual(self.client.get(self.url).status_code, 501)
        res = self._upload(webm(3), url=f"/api/v2/orgs/{self.org.id}/buddies/voice-input")
        self.assertEqual(res.status_code, 501)
        self.assertFalse(RoomMessage.objects.filter(kind="voice").exists())

    def test_member_flag_off_overrides_org(self):
        OrgMembership.objects.filter(org=self.org, user=self.alice).update(feature_flags={"voice_notes": False})
        self._auth(self.alice)
        self.assertEqual(self._upload(webm(3)).status_code, 501)

    def test_rejects_too_large(self):
        self._auth(self.alice)
        res = self._upload(webm(3) + b"\x00" * (voice.MAX_BYTES + 1))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "too_large")

    def test_rejects_too_long_from_container(self):
        self._auth(self.alice)
        for data, mime in ((webm(301.5), "audio/webm"), (ogg(320), "audio/ogg"), (m4a(400), "audio/mp4"), (mp3(310), "audio/mpeg")):
            res = self._upload(data, mime=mime, duration="10")  # the container wins over a declared duration
            self.assertEqual(res.status_code, 400, mime)
            self.assertEqual(res.json()["code"], "too_long", mime)
        self.assertFalse(VoiceNote.objects.exists())

    def test_magic_bytes_must_match_declared_type(self):
        self._auth(self.alice)
        res = self._upload(ogg(3), mime="audio/webm")
        self.assertEqual(res.json()["code"], "type_mismatch")
        res = self._upload(b"<html><script>alert(1)</script></html>" * 4, mime="audio/webm")
        self.assertEqual(res.json()["code"], "type_mismatch")
        res = self._upload(webm(3), mime="text/html")
        self.assertEqual(res.json()["code"], "unsupported_type")
        res = self._upload(b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64, mime="audio/ogg")
        self.assertEqual(res.json()["code"], "type_mismatch")

    def test_bad_fields(self):
        self._auth(self.alice)
        self.assertEqual(self._upload(webm(3), duration="abc").json()["code"], "bad_duration")
        self.assertEqual(self._upload(webm(3), language="egyptian; drop").json()["code"], "bad_language")
        self.assertEqual(self.client.post(self.url, {}, format="multipart").json()["code"], "empty")

    def test_room_membership_required(self):
        self._auth(self.carol)
        self.assertEqual(self._upload(webm(3)).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        stranger = User.objects.create(email="x@example.com", password_hash=make_password("x"))
        self._auth(stranger)
        self.assertIn(self._upload(webm(3)).status_code, (403, 404))
        self.assertFalse(VoiceNote.objects.exists())


@override_settings(ASR_BACKEND="http", ASR_BASE_URL=WHISPER)
class TranscriptionTests(VoiceBase):
    def _post(self, net, data=None, mime="audio/webm", **fields):
        self._auth(self.alice)
        with patch("urllib.request.urlopen", side_effect=net), self.captureOnCommitCallbacks(execute=True):
            return self._upload(data or webm(4), mime=mime, **fields)

    def test_success_egyptian_hint_and_prompt(self):
        net = FakeNetwork({"text": "أنا عايز أخلص الموضوع ده النهارده", "language": "ar", "duration": 4.0})
        res = self._post(net, language="ar-EG")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(len(net.whisper_calls), 1)
        call = net.whisper_calls[0]
        self.assertEqual(call["url"], f"{WHISPER}/v1/audio/transcriptions")  # only the configured server
        self.assertIn(b'name="language"\r\n\r\nar\r\n', call["body"])
        self.assertIn(voice.DIALECT_PROMPTS["ar-EG"].encode(), call["body"])
        note = VoiceNote.objects.get()
        self.assertEqual(note.status, "done")
        self.assertEqual(note.language, "ar-EG")
        self.assertEqual(note.message.kind, "voice")
        self.assertEqual(note.message.body, "أنا عايز أخلص الموضوع ده النهارده")
        self.assertAlmostEqual(note.duration_seconds, 4.0, delta=0.1)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, *note.storage_key.split("/"))))
        listed = self.client.get(self.url).json()["results"]
        self.assertEqual(listed[0]["transcript"], note.message.body)
        self.assertEqual(listed[0]["language"], "ar-EG")
        self.assertFalse(listed[0]["demo"])

    def test_gulf_hint_uses_gulf_prompt(self):
        net = FakeNetwork({"text": "شلونك", "language": "ar"})
        self._post(net, language="ar-AE")
        self.assertIn(voice.DIALECT_PROMPTS["gulf"].encode(), net.whisper_calls[0]["body"])
        self.assertEqual(VoiceNote.objects.get().language, "ar-AE")

    def test_detects_gulf_without_hint(self):
        net = FakeNetwork({"text": "هلا، أبي الملف الحين لو سمحت، وايد مهم", "language": "arabic"})
        self._post(net)
        self.assertNotIn(b'name="language"', net.whisper_calls[0]["body"])
        self.assertEqual(VoiceNote.objects.get().language, "ar-SA")

    def test_whisper_error_marks_failed(self):
        err = urllib.error.HTTPError(WHISPER, 500, "boom", {}, io.BytesIO(b""))
        res = self._post(FakeNetwork(whisper_error=err))
        self.assertEqual(res.status_code, 201)
        note = VoiceNote.objects.get()
        self.assertEqual((note.status, note.error), ("failed", "http_500"))
        self.assertEqual(note.message.body, "")

    def test_whisper_unreachable_and_empty(self):
        self._post(FakeNetwork(whisper_error=urllib.error.URLError("down")))
        self.assertEqual(VoiceNote.objects.get().error, "unavailable")
        VoiceNote.objects.all().delete()
        self._post(FakeNetwork({"text": "  ", "language": "en"}))
        self.assertEqual(VoiceNote.objects.get().error, "no_speech")

    def test_whisper_says_too_long(self):
        self._post(FakeNetwork({"text": "long", "language": "en", "duration": 900}), data=m4a(0), mime="audio/mp4")
        self.assertEqual(VoiceNote.objects.get().error, "too_long")

    @override_settings(ASR_BACKEND="")
    def test_not_configured(self):
        self._post(FakeNetwork())
        self.assertEqual(VoiceNote.objects.get().error, "not_configured")

    def test_retry_by_author_only(self):
        self._post(FakeNetwork(whisper_error=urllib.error.URLError("down")))
        note = VoiceNote.objects.get()
        url = f"{self.url}/{note.id}/retry"
        self._auth(self.bob)
        self.assertEqual(self.client.post(url).status_code, 403)
        self._auth(self.alice)
        with patch("urllib.request.urlopen", side_effect=FakeNetwork()), self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(url)
        self.assertEqual(res.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.status, "done")
        self.assertEqual(self.client.post(url).status_code, 409)


@override_settings(ASR_BACKEND="http", ASR_BASE_URL=WHISPER)
class AudioAccessTests(VoiceBase):
    def setUp(self):
        super().setUp()
        self._auth(self.alice)
        with patch("urllib.request.urlopen", side_effect=FakeNetwork()), self.captureOnCommitCallbacks(execute=True):
            self.created = self._upload(ogg(3), mime="audio/ogg; codecs=opus").json()
        self.note = VoiceNote.objects.get()
        self.audio = f"/api/v2{self.created['audio_url']}"

    def test_room_members_get_the_audio(self):
        self._auth(self.bob)
        res = self.client.get(self.audio)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "audio/ogg")
        self.assertEqual(res["Cache-Control"], "private, no-store")
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")
        self.assertTrue(res.content.startswith(b"OggS"))

    def test_others_do_not(self):
        self._auth(self.carol)
        self.assertEqual(self.client.get(self.audio).status_code, 404)
        # The right note through a room the person can read is still not found.
        self.assertEqual(
            self.client.get(f"/api/v2/orgs/{self.org.id}/rooms/{self.other_room.id}/voice/{self.note.id}/audio").status_code, 404
        )
        self.client.credentials()
        self.assertEqual(self.client.get(self.audio).status_code, 401)
        self.assertNotIn("http", self.created["audio_url"])  # no public or presigned URL is handed out

    def test_deleting_the_message_removes_audio(self):
        path = os.path.join(self.tmp, *self.note.storage_key.split("/"))
        self.assertTrue(os.path.isfile(path))
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.delete(f"/api/v2/orgs/{self.org.id}/rooms/{self.room.id}/messages/{self.note.message_id}")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.client.get(self.audio).status_code, 404)

    def test_flag_off_hides_audio(self):
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self.assertEqual(self.client.get(self.audio).status_code, 501)


@override_settings(**DIRECT)
class TranslationCacheTests(VoiceBase):
    def setUp(self):
        super().setUp()
        self.org.settings = {"flags": {"voice_notes": True}}
        self.org.save(update_fields=["settings"])
        message = RoomMessage.objects.create(room=self.room, author=self.alice, body="أنا عايز أخلص ده", kind="voice")
        self.note = VoiceNote.objects.create(org=self.org, message=message, status="done", language="ar-EG", transcript=message.body)
        english = RoomMessage.objects.create(room=self.room, author=self.bob, body="Already English", kind="voice")
        VoiceNote.objects.create(org=self.org, message=english, status="done", language="en", transcript=english.body)

    def _get(self, net):
        with patch("urllib.request.urlopen", side_effect=net):
            return self.client.get(self.url + "?translate_to=en")

    def test_translates_once_then_uses_the_cache(self):
        self._auth(self.bob)
        net = FakeNetwork()
        rows = {r["message"]: r for r in self._get(net).json()["results"]}
        self.assertEqual(len(net.ai_calls), 1)  # the English note is not sent
        row = rows[str(self.note.message_id)]
        self.assertTrue(row["translated"])
        self.assertTrue(row["translation"].startswith("EN:"))
        self.assertEqual(MessageTranslation.objects.filter(message=self.note.message, language="en").count(), 1)
        again = FakeNetwork()
        self._get(again)
        self.assertEqual(again.ai_calls, [])
        # A corrected transcript is a new version: translated again.
        self.note.message.body = "أنا عايز أخلص ده بكرة"
        self.note.message.save(update_fields=["body", "updated_at"])
        third = FakeNetwork()
        self._get(third)
        self.assertEqual(len(third.ai_calls), 1)

    def test_private_only_org_gets_no_translation(self):
        from brain.llm.policy import PRIVATE_ONLY
        from organizations.models import OrgPolicy

        OrgPolicy.objects.update_or_create(org=self.org, defaults={"inference_scope": PRIVATE_ONLY})
        self._auth(self.bob)
        net = FakeNetwork()
        body = self._get(net).json()
        self.assertEqual(net.ai_calls, [])
        self.assertEqual(body["translation_note"], "private_only")


@override_settings(ASR_BACKEND="http", ASR_BASE_URL=WHISPER)
class BuddyVoiceInputTests(VoiceBase):
    def setUp(self):
        super().setUp()
        self.input_url = f"/api/v2/orgs/{self.org.id}/buddies/voice-input"
        self.scratch = tempfile.mkdtemp(prefix="voice-input-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self._auth(self.alice)

    def test_returns_text_and_keeps_nothing(self):
        with override_settings(VOICE_TMP_DIR=self.scratch), patch("urllib.request.urlopen", side_effect=FakeNetwork({"text": "Summarize my tasks", "language": "en"})):
            res = self._upload(webm(2), url=self.input_url)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["text"], "Summarize my tasks")
        self.assertEqual(os.listdir(self.scratch), [])
        self.assertFalse(RoomMessage.objects.exists())
        self.assertFalse(VoiceNote.objects.exists())
        self.assertEqual([p for p in os.listdir(self.tmp)], [])  # nothing in storage either

    def test_temp_file_removed_on_failure(self):
        err = urllib.error.URLError("down")
        with override_settings(VOICE_TMP_DIR=self.scratch), patch("urllib.request.urlopen", side_effect=FakeNetwork(whisper_error=err)):
            res = self._upload(webm(2), url=self.input_url)
        self.assertEqual(res.status_code, 503)
        self.assertEqual(os.listdir(self.scratch), [])

    def test_validation_applies(self):
        res = self._upload(webm(400), url=self.input_url)
        self.assertEqual(res.json()["code"], "too_long")

    @override_settings(ASR_BACKEND="")
    def test_not_configured(self):
        self.assertEqual(self._upload(webm(2), url=self.input_url).status_code, 501)


@override_settings(ASR_BACKEND="http", ASR_BASE_URL=WHISPER)
class ChannelsHookTests(VoiceBase):
    def test_transcribe_bytes(self):
        net = FakeNetwork({"text": "إزيك عامل إيه دلوقتي", "language": "ar"})
        with patch("urllib.request.urlopen", side_effect=net):
            text, language = voice.transcribe_bytes(self.org, ogg(5), "audio/ogg; codecs=opus")
        self.assertEqual((text, language), ("إزيك عامل إيه دلوقتي", "ar-EG"))
        self.assertFalse(VoiceNote.objects.exists())

    def test_transcribe_bytes_validates(self):
        with self.assertRaises(voice.VoiceError) as ctx:
            voice.transcribe_bytes(self.org, ogg(5), "audio/mpeg")
        self.assertEqual(ctx.exception.code, "type_mismatch")
        with self.assertRaises(voice.VoiceError) as ctx:
            voice.transcribe_bytes(self.org, b"\x00" * 100, "")
        self.assertEqual(ctx.exception.code, "unsupported_type")

    def test_org_default_hint(self):
        self.org.settings = {"flags": {}, "voice_language_hint": "ar-SA"}
        net = FakeNetwork({"text": "زين", "language": "ar"})
        with patch("urllib.request.urlopen", side_effect=net):
            _, language = voice.transcribe_bytes(self.org, ogg(5), None)
        self.assertEqual(language, "ar-SA")
        self.assertIn(voice.DIALECT_PROMPTS["gulf"].encode(), net.whisper_calls[0]["body"])


class ParserTests(TestCase):
    def test_durations(self):
        self.assertAlmostEqual(voice.duration_of(webm(42), "webm"), 42.02, delta=0.05)
        self.assertAlmostEqual(voice.duration_of(webm(42, with_duration=True), "webm"), 42.0, delta=0.01)
        self.assertAlmostEqual(voice.duration_of(ogg(12.5), "ogg"), 12.5, delta=0.01)
        self.assertAlmostEqual(voice.duration_of(mp3(20), "mp3"), 20.0, delta=0.1)
        self.assertAlmostEqual(voice.duration_of(m4a(33), "mp4"), 33.0, delta=0.01)
        self.assertIsNone(voice.duration_of(b"\x1a\x45\xdf\xa3\x00", "webm"))

    def test_sniff(self):
        self.assertEqual(voice.sniff(webm(1)), "webm")
        self.assertEqual(voice.sniff(ogg(1)), "ogg")
        self.assertEqual(voice.sniff(mp3(1)), "mp3")
        self.assertEqual(voice.sniff(m4a(1)), "mp4")
        self.assertIsNone(voice.sniff(b"%PDF-1.7\n" + b"\x00" * 40))
        matroska = _el(b"\x1a\x45\xdf\xa3", _el(b"\x42\x82", b"matroska")) + b"\x00" * 20
        self.assertIsNone(voice.sniff(matroska))

    def test_dialects(self):
        self.assertEqual(voice.guess_dialect("إزيك يا باشا، عايز إيه دلوقتي؟"), "ar-EG")
        self.assertEqual(voice.guess_dialect("شلونك؟ أبي أشوفك الحين"), "ar-SA")
        self.assertEqual(voice.guess_dialect("مرحبا بكم في الاجتماع"), "ar")
        self.assertEqual(voice.resolve_language("english", "", "hello"), "en")
        self.assertEqual(voice.resolve_language("ar", "ar-AE", "مرحبا"), "ar-AE")
        self.assertEqual(voice.whisper_hints("ar-SA")[0], "ar")
        self.assertEqual(voice.whisper_hints(""), (None, None))


@override_settings(DEMO_MODE=True, DEMO_AI=True, ASR_BACKEND="", ASR_BASE_URL="")
class DemoTests(VoiceBase):
    def test_demo_upload_transcribes_without_network(self):
        self._auth(self.alice)
        with patch("urllib.request.urlopen", side_effect=AssertionError("no network in demo")), self.captureOnCommitCallbacks(execute=True):
            res = self._upload(webm(3), language="ar-EG")
        self.assertEqual(res.status_code, 201, res.content)
        note = VoiceNote.objects.get()
        self.assertTrue(note.is_demo)
        self.assertEqual(note.language, "ar-EG")
        self.assertEqual(note.message.body, voice.DEMO_TRANSCRIPTS["ar-EG"]["text"])

    def test_demo_translation_handler(self):
        from brain.llm.demo_handlers import voice as handler
        from rooms.translation import TRANSLATE_SYSTEM

        reply = handler.handle(TRANSLATE_SYSTEM.format(language="en"), voice.DEMO_TRANSCRIPTS["ar-SA"]["text"], [], None)
        self.assertIn("Dubai", reply.text)
        self.assertIn("demo", reply.text)
        self.assertIsNone(handler.handle(TRANSLATE_SYSTEM.format(language="en"), "something else", [], None))
        self.assertIsNone(handler.handle("You are a helpful buddy", voice.DEMO_TRANSCRIPTS["en"]["text"], [], None))

    def test_demo_seed(self):
        project = Project.objects.create(org=self.org, name="Mobile app launch")
        ProjectMembership.objects.create(project=project, user=self.alice)
        users = {"designer": self.alice, "admin": self.bob, "member": self.carol}
        importlib.import_module("demo.extras.97_voice").seed(self.org, users, timezone.now())
        notes = VoiceNote.objects.filter(message__room__project=project).order_by("message__created_at")
        self.assertEqual([n.language for n in notes], ["ar-EG", "ar-SA", "en"])
        self.assertTrue(all(n.is_demo and n.status == "done" and n.storage_key for n in notes))
        self.assertTrue(MessageTranslation.objects.filter(message=notes[0].message, language="en").exists())
        # The cached translation is served with no model call.
        self._auth(self.alice)
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/rooms/{notes[0].message.room_id}/voice?translate_to=en")
        rows = {r["message"]: r for r in res.json()["results"]}
        self.assertTrue(rows[str(notes[0].message_id)]["translated"])
        audio = self.client.get(f"/api/v2{rows[str(notes[0].message_id)]['audio_url']}")
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio["Content-Type"], "audio/wav")
