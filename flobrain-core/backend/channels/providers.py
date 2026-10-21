"""WhatsApp Cloud API and Telegram Bot API: signatures, payload parsing, sending, connection checks.

Outbound calls go only to ``graph.facebook.com`` and ``api.telegram.org`` over HTTPS through
``platform_api.net.fetch`` (public addresses only, pinned, no redirects). Demo connections and demo
servers never call the network: sends and checks are simulated. Tokens never reach logs.
"""

import hashlib
import hmac
import json
import logging
import re
import urllib.parse

from django.conf import settings

from channels import vault
from channels.models import ChannelConnection

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"graph.facebook.com", "api.telegram.org"})
MAX_TEXT = 4000

WA_ID = re.compile(r"^\d{5,20}$")
TG_BOT_TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
TG_SECRET = re.compile(r"^[A-Za-z0-9_-]{16,256}$")  # characters Telegram allows in secret_token


class ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def graph_version() -> str:
    version = str(getattr(settings, "WHATSAPP_GRAPH_VERSION", "") or "v21.0")
    return version if re.match(r"^v\d{1,3}\.\d{1,2}$", version) else "v21.0"


def simulated(connection) -> bool:
    """Demo connections and demo servers never reach a provider."""
    return bool(connection.demo or getattr(settings, "DEMO_MODE", False))


# --- signatures -------------------------------------------------------------------------------


def whatsapp_signature_ok(app_secret: str, body: bytes, header: str | None) -> bool:
    """``X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw body with the app secret>``."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.strip().encode())


def telegram_secret_ok(expected: str, header: str | None) -> bool:
    if not expected or not header:
        return False
    return hmac.compare_digest(expected.encode(), header.encode())


# --- parsing ----------------------------------------------------------------------------------


def parse_whatsapp(payload, phone_number_id: str) -> list[dict]:
    """Messages addressed to this phone number. Status updates and other numbers are skipped."""
    out = []
    if not isinstance(payload, dict):
        return out
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            if not isinstance(value, dict):
                continue
            if str((value.get("metadata") or {}).get("phone_number_id") or "") != str(phone_number_id):
                continue
            names = {}
            for contact in value.get("contacts") or []:
                if isinstance(contact, dict):
                    names[str(contact.get("wa_id") or "")] = str(((contact.get("profile") or {}).get("name")) or "")[:120]
            for msg in value.get("messages") or []:
                if not isinstance(msg, dict) or not msg.get("id"):
                    continue
                sender = str(msg.get("from") or "")
                if not WA_ID.match(sender):
                    continue
                kind = msg.get("type")
                text, media = "", {}
                if kind == "text":
                    text = str((msg.get("text") or {}).get("body") or "")
                elif kind == "audio":
                    audio = msg.get("audio") or {}
                    media = {"type": "voice", "ref": str(audio.get("id") or "")[:128], "mime": str(audio.get("mime_type") or "")[:60]}
                elif kind == "button":
                    text = str((msg.get("button") or {}).get("text") or "")
                else:
                    media = {"type": str(kind or "unknown")[:20]}
                out.append({"id": str(msg["id"])[:128], "sender": sender, "name": names.get(sender, ""), "text": text[:MAX_TEXT], "media": media})
    return out


def parse_telegram(payload) -> list[dict]:
    """A private chat message. Groups, channels and edits are skipped."""
    if not isinstance(payload, dict):
        return []
    msg = payload.get("message")
    if not isinstance(msg, dict):
        return []
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or not isinstance(chat.get("id"), int):
        return []
    sender = (msg.get("from") or {})
    name = " ".join(str(sender.get(k) or "") for k in ("first_name", "last_name")).strip()[:120]
    text, media = str(msg.get("text") or ""), {}
    voice = msg.get("voice") or msg.get("audio")
    if isinstance(voice, dict):
        media = {"type": "voice", "ref": str(voice.get("file_id") or "")[:128], "mime": str(voice.get("mime_type") or "")[:60]}
    elif not text:
        media = {"type": "unknown"}
    message_id = msg.get("message_id")
    return [{"id": f"{chat['id']}:{message_id}", "sender": str(chat["id"]), "name": name, "text": text[:MAX_TEXT], "media": media}]


# --- network ----------------------------------------------------------------------------------


def _call(method: str, url: str, payload: dict | None = None, headers: dict | None = None):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ProviderError("host_not_allowed")
    from platform_api import net

    body = json.dumps(payload).encode() if payload is not None else b""
    all_headers = {"Content-Type": "application/json", **(headers or {})} if payload is not None else dict(headers or {})
    try:
        status, data = net.fetch(method, url, body, all_headers, timeout=10, max_bytes=65536)
    except (net.UnsafeURL, OSError) as exc:
        logger.info("channels: %s %s failed: %s", method, parsed.hostname, type(exc).__name__)  # never the URL (Telegram puts the token in it)
        raise ProviderError("provider_unavailable") from exc
    try:
        decoded = json.loads(data.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        decoded = {}
    return status, decoded


def _secrets(connection) -> dict | None:
    from integrations.crypto import CredentialCryptoError

    try:
        return vault.read(connection)
    except (CredentialCryptoError, ValueError):
        return None


def _status_error(status: int) -> str:
    if status in (401, 403):
        return "invalid_credentials"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "provider_rejected"
    return "provider_unavailable"


def check(connection) -> tuple[str, str]:
    """Check the credentials. Returns (status, error)."""
    if connection.kind == ChannelConnection.WEBSITE:
        return ChannelConnection.ACTIVE, ""
    if simulated(connection):
        return ChannelConnection.ACTIVE, ""
    secrets = _secrets(connection)
    if secrets is None:
        return ChannelConnection.ERROR, "decrypt_failed"
    try:
        if connection.kind == ChannelConnection.WHATSAPP:
            phone = (connection.config or {}).get("phone_number_id", "")
            token = secrets.get("access_token", "")
            if not token or not WA_ID.match(str(phone)):
                return ChannelConnection.NOT_SET_UP, "missing_settings"
            status, _ = _call("GET", f"https://graph.facebook.com/{graph_version()}/{phone}?fields=display_phone_number", headers={"Authorization": f"Bearer {token}"})
        else:
            token = secrets.get("bot_token", "")
            if not TG_BOT_TOKEN.match(token):
                return ChannelConnection.NOT_SET_UP, "missing_settings"
            status, body = _call("GET", f"https://api.telegram.org/bot{token}/getMe")
            if 200 <= status < 300 and isinstance(body.get("result"), dict):
                username = str(body["result"].get("username") or "")[:64]
                if username:
                    connection.config = {**(connection.config or {}), "bot_username": username}
    except ProviderError as exc:
        return ChannelConnection.ERROR, exc.code
    if 200 <= status < 300:
        return ChannelConnection.ACTIVE, ""
    return ChannelConnection.ERROR, _status_error(status)


def send(connection, to: str, text: str) -> str:
    """Send a text. Returns "" when sent (or simulated), else an error code."""
    text = (text or "").strip()[:MAX_TEXT]
    if connection.kind == ChannelConnection.WEBSITE:
        return ""  # the website chat reads its messages from FloBrain
    if not text or not to:
        return "empty"
    if simulated(connection):
        return ""  # demo sends are simulated
    if connection.status != ChannelConnection.ACTIVE:
        return "not_active"
    secrets = _secrets(connection)
    if secrets is None:
        return "decrypt_failed"
    try:
        if connection.kind == ChannelConnection.WHATSAPP:
            phone = str((connection.config or {}).get("phone_number_id", ""))
            if not WA_ID.match(phone) or not WA_ID.match(str(to)):
                return "invalid_target"
            status, _ = _call(
                "POST",
                f"https://graph.facebook.com/{graph_version()}/{phone}/messages",
                {"messaging_product": "whatsapp", "to": str(to), "type": "text", "text": {"body": text, "preview_url": False}},
                {"Authorization": f"Bearer {secrets.get('access_token', '')}"},
            )
        else:
            token = secrets.get("bot_token", "")
            if not TG_BOT_TOKEN.match(token) or not re.match(r"^-?\d{1,20}$", str(to)):
                return "invalid_target"
            status, _ = _call("POST", f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": int(to), "text": text})
    except ProviderError as exc:
        return exc.code
    return "" if 200 <= status < 300 else _status_error(status)


# --- inbound media (voice notes) ----------------------------------------------------------------

MEDIA_HOSTS = frozenset({"graph.facebook.com", "lookaside.fbsbx.com", "api.telegram.org"})
MAX_MEDIA = 10 * 1024 * 1024
MEDIA_REF = re.compile(r"^[A-Za-z0-9_\-:.]{1,256}$")
TG_FILE_PATH = re.compile(r"^[A-Za-z0-9_\-./]{1,256}$")


def _fetch_media(url: str, headers: dict | None = None) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in MEDIA_HOSTS:
        raise ProviderError("host_not_allowed")
    from platform_api import net

    try:
        status, data = net.fetch("GET", url, b"", dict(headers or {}), timeout=20, max_bytes=MAX_MEDIA + 1)
    except (net.UnsafeURL, OSError) as exc:
        logger.info("channels: media GET %s failed: %s", parsed.hostname, type(exc).__name__)
        raise ProviderError("provider_unavailable") from exc
    if not 200 <= status < 300:
        raise ProviderError(_status_error(status))
    if len(data) > MAX_MEDIA:
        raise ProviderError("too_large")
    return data


def download_media(connection, ref: str) -> bytes:
    """Download one inbound media file (up to 10 MB). Raises ``ProviderError``; never simulated."""
    if simulated(connection) or not MEDIA_REF.match(str(ref or "")):
        raise ProviderError("not_available")
    secrets = _secrets(connection)
    if secrets is None:
        raise ProviderError("decrypt_failed")
    if connection.kind == ChannelConnection.WHATSAPP:
        auth = {"Authorization": f"Bearer {secrets.get('access_token', '')}"}
        status, meta = _call("GET", f"https://graph.facebook.com/{graph_version()}/{ref}", None, auth)
        if not 200 <= status < 300:
            raise ProviderError(_status_error(status))
        return _fetch_media(str(meta.get("url") or ""), auth)
    if connection.kind == ChannelConnection.TELEGRAM:
        token = secrets.get("bot_token", "")
        if not TG_BOT_TOKEN.match(token):
            raise ProviderError("invalid_credentials")
        status, meta = _call("POST", f"https://api.telegram.org/bot{token}/getFile", {"file_id": ref})
        path = str(((meta or {}).get("result") or {}).get("file_path") or "")
        if not 200 <= status < 300 or not TG_FILE_PATH.match(path) or ".." in path:
            raise ProviderError("not_available")
        return _fetch_media(f"https://api.telegram.org/file/bot{token}/{path}")
    raise ProviderError("not_available")
