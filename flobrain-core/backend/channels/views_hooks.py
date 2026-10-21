"""Provider webhooks (no FloBrain sign-in; the provider proves itself).

- ``GET  /api/v2/hooks/whatsapp/<connection>``: Meta's verify-token challenge.
- ``POST /api/v2/hooks/whatsapp/<connection>``: ``X-Hub-Signature-256`` HMAC of the raw body with the app secret.
- ``POST /api/v2/hooks/telegram/<connection>``: ``X-Telegram-Bot-Api-Secret-Token`` header.

All compares are constant time. Bodies over ``MAX_BODY`` are refused before they are read, each
connection is rate limited, and every provider message id is processed once.
"""

import hmac
import json
import re

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from channels import inbound, providers, ratelimit, vault
from channels.models import ChannelConnection
from organizations.flags import effective_flag

MAX_BODY = 256 * 1024
CHALLENGE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _err(code, status):
    return JsonResponse({"error": code}, status=status)


def _connection(kind, connection_id):
    conn = ChannelConnection.objects.select_related("org").filter(pk=connection_id, kind=kind).first()
    # Demo connections have no secrets to check against: they never accept webhooks.
    if conn is None or conn.demo or not conn.org.is_active or not effective_flag(conn.org, None, "channels", default=False):
        return None
    return conn


def _too_big(request) -> bool:
    try:
        return int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY
    except ValueError:
        return True


def _limited(connection_id) -> bool:
    return not ratelimit.hit("hook", str(connection_id), ratelimit.limit("webhook_per_minute", 300), 60)


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _accept(conn, items):
    events = [e for e in (inbound.record(conn, item) for item in items[:50]) if e is not None]
    inbound.dispatch(events)
    return JsonResponse({"ok": True, "received": len(events)})


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppHookView(View):
    def get(self, request, connection_id):
        if _limited(connection_id):
            return _err("rate_limited", 429)
        conn = _connection(ChannelConnection.WHATSAPP, connection_id)
        if conn is None:
            return _err("not_found", 404)
        expected = vault.get(conn, "verify_token")
        given = request.GET.get("hub.verify_token") or ""
        challenge = request.GET.get("hub.challenge") or ""
        if (
            request.GET.get("hub.mode") == "subscribe"
            and expected
            and given
            and hmac.compare_digest(expected.encode(), given.encode())
            and CHALLENGE.match(challenge)
        ):
            return HttpResponse(challenge, content_type="text/plain")
        return _err("forbidden", 403)

    def post(self, request, connection_id):
        if _limited(connection_id):
            return _err("rate_limited", 429)
        if _too_big(request):
            return _err("too_large", 413)
        conn = _connection(ChannelConnection.WHATSAPP, connection_id)
        if conn is None:
            return _err("not_found", 404)
        body = request.body
        if not providers.whatsapp_signature_ok(vault.get(conn, "app_secret"), body, request.headers.get("X-Hub-Signature-256")):
            return _err("bad_signature", 401)
        payload = _json(body)
        if payload is None:
            return _err("invalid", 400)
        return _accept(conn, providers.parse_whatsapp(payload, str((conn.config or {}).get("phone_number_id") or "")))


@method_decorator(csrf_exempt, name="dispatch")
class TelegramHookView(View):
    http_method_names = ["post"]

    def post(self, request, connection_id):
        if _limited(connection_id):
            return _err("rate_limited", 429)
        if _too_big(request):
            return _err("too_large", 413)
        conn = _connection(ChannelConnection.TELEGRAM, connection_id)
        if conn is None:
            return _err("not_found", 404)
        if not providers.telegram_secret_ok(vault.get(conn, "secret_token"), request.headers.get("X-Telegram-Bot-Api-Secret-Token")):
            return _err("bad_signature", 401)
        payload = _json(request.body)
        if payload is None:
            return _err("invalid", 400)
        items = providers.parse_telegram(payload)
        if items and isinstance(payload.get("update_id"), int):
            items[0]["id"] = f"u{payload['update_id']}"
        return _accept(conn, items)
