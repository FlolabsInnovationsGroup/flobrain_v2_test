"""Calls inside FloBrain on our own LiveKit server (Q2: self-hosted, decided 2026-10-21).

Settings (all empty means "not configured", nothing opens a socket):
- ``LIVEKIT_URL``: the browser's ``wss://`` address of the LiveKit server.
- ``LIVEKIT_API_URL``: the server's HTTP address from the API (defaults to LIVEKIT_URL with https).
- ``LIVEKIT_API_KEY`` / ``LIVEKIT_API_SECRET``: one key pair from ``livekit.yaml``.
Recordings are made by LiveKit Egress (audio only) into the storage configured on the egress
service; the webhook tells us the file name. Tokens are short-lived HS256 JWTs, per person and call.
"""

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request

import jwt
from django.conf import settings

TOKEN_TTL_SECONDS = 10 * 60  # only for joining; LiveKit keeps a joined client connected


class LiveKitError(Exception):
    def __init__(self, code, status=0):
        super().__init__(code)
        self.status = status

    @property
    def gone(self) -> bool:
        """LiveKit says the egress or room no longer exists (twirp not_found / failed_precondition)."""
        return self.status in (404, 412)


def _setting(name):
    return (getattr(settings, name, "") or "").strip()


def configured() -> bool:
    return bool(_setting("LIVEKIT_URL") and _setting("LIVEKIT_API_KEY") and _setting("LIVEKIT_API_SECRET"))


def room_name(meeting) -> str:
    return f"fb-{meeting.id}"


def _jwt(claims: dict, ttl: int) -> str:
    now = int(time.time())
    payload = {"iss": _setting("LIVEKIT_API_KEY"), "nbf": now - 10, "exp": now + ttl, **claims}
    return jwt.encode(payload, _setting("LIVEKIT_API_SECRET"), algorithm="HS256")


def join_token(meeting, user, can_publish=True) -> str:
    return _jwt(
        {
            "sub": str(user.id),
            "name": (user.username or user.email.split("@")[0])[:80],
            "video": {"room": room_name(meeting), "roomJoin": True, "canPublish": can_publish, "canSubscribe": True, "canPublishData": True},
            "metadata": json.dumps({"org": str(meeting.org_id)}),
        },
        TOKEN_TTL_SECONDS,
    )


def _api(service: str, method: str, body: dict, grants: dict) -> dict:
    base = _setting("LIVEKIT_API_URL") or _setting("LIVEKIT_URL").replace("wss://", "https://").replace("ws://", "http://")
    token = _jwt({"video": grants}, 600)
    request = urllib.request.Request(
        f"{base.rstrip('/')}/twirp/livekit.{service}/{method}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # admin-configured internal service
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise LiveKitError(f"http_{exc.code}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise LiveKitError(type(exc).__name__) from exc


def ensure_room(meeting) -> None:
    """Rooms are created only by FloBrain (``room.auto_create: false`` in livekit.yaml), so a token
    alone can't bring an ended call back."""
    _api("RoomService", "CreateRoom", {"name": room_name(meeting), "empty_timeout": 300, "max_participants": 50}, {"roomCreate": True})


def start_recording(meeting) -> str:
    """Audio-only recording of the whole call. Returns the egress id."""
    body = {
        "room_name": room_name(meeting),
        "audio_only": True,
        "file_outputs": [{"file_type": "OGG", "filepath": f"meetings/{meeting.org_id}/{meeting.id}/{{time}}.ogg"}],
    }
    data = _api("Egress", "StartRoomCompositeEgress", body, {"roomRecord": True})
    egress_id = data.get("egress_id") or data.get("egressId") or ""
    if not egress_id:
        raise LiveKitError("no_egress_id")
    return egress_id


def audio_tracks(meeting) -> list[dict]:
    """[{identity, name, track_sid}] for every published microphone track in the call."""
    data = _api("RoomService", "ListParticipants", {"room": room_name(meeting)}, {"roomAdmin": True, "room": room_name(meeting)})
    out = []
    for p in data.get("participants") or []:
        for t in p.get("tracks") or []:
            if str(t.get("type", "")).upper() in ("AUDIO", "0") and t.get("sid"):
                out.append({"identity": str(p.get("identity") or "")[:64], "name": str(p.get("name") or "")[:150], "track_sid": str(t["sid"])[:64]})
    return out


def start_track_recording(meeting, identity: str, track_sid: str) -> str:
    """Record one speaker's audio track on its own, so the transcript knows who spoke."""
    safe_identity = "".join(ch for ch in identity if ch.isalnum() or ch in "-_")[:64] or "speaker"
    body = {
        "room_name": room_name(meeting),
        "track_id": track_sid,
        "file": {"filepath": f"meetings/{meeting.org_id}/{meeting.id}/{safe_identity}-{track_sid}-{{time}}.ogg"},
    }
    data = _api("Egress", "StartTrackEgress", body, {"roomRecord": True})
    egress_id = data.get("egress_id") or data.get("egressId") or ""
    if not egress_id:
        raise LiveKitError("no_egress_id")
    return egress_id


def remove_participant(meeting, identity: str) -> None:
    """Take someone out of a live call (they lost access to the room)."""
    try:
        _api("RoomService", "RemoveParticipant", {"room": room_name(meeting), "identity": identity}, {"roomAdmin": True, "room": room_name(meeting)})
    except LiveKitError:
        pass  # not in the call, or the call is over


def stop_recording(egress_id: str) -> None:
    _api("Egress", "StopEgress", {"egress_id": egress_id}, {"roomRecord": True})


def end_call(meeting) -> None:
    try:
        _api("RoomService", "DeleteRoom", {"room": room_name(meeting)}, {"roomCreate": True})
    except LiveKitError:
        pass  # the room may already be gone


def verify_webhook(body: bytes, authorization: str) -> dict | None:
    """LiveKit signs webhooks with a JWT whose ``sha256`` claim is the body hash."""
    if not configured() or not authorization:
        return None
    token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else authorization
    try:
        claims = jwt.decode(token, _setting("LIVEKIT_API_SECRET"), algorithms=["HS256"], options={"verify_aud": False, "require": ["exp"]})
    except jwt.PyJWTError:
        return None
    if claims.get("iss") != _setting("LIVEKIT_API_KEY"):
        return None
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    if claims.get("sha256") != digest:
        return None
    try:
        event = json.loads(body.decode())
    except ValueError:
        return None
    return event if isinstance(event, dict) else None
