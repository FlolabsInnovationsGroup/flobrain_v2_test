"""Website chat, public and signed out.

- ``GET  /api/v2/public/chat/<site_key>?embed=<parent origin>``: name, greeting, whether this page may embed it.
- ``POST /api/v2/public/chat/<site_key>/messages``: ``{text, conversation?, name?, embed_origin?}``; the first
  message opens a conversation and returns its token once (unguessable; only its hash is stored).
- ``GET  /api/v2/public/chat/<site_key>/messages?conversation=<token>``: the messages the customer may see.

Requests from a browser must come from one of the site's allowed origins, or from FloBrain's own
chat page embedded by an allowed origin. CORS is answered only for allowed origins (see
``channels.cors``). Rate limits per IP and per conversation sit on top of the anonymous throttle.
"""

import hashlib
import re
import secrets
import urllib.parse

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from channels import customers, ratelimit
from channels.models import ChannelConnection, CustomerConversation, CustomerMessage
from core_v2.views import V2PublicAPIView
from organizations.flags import client_ip, effective_flag

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_TEXT = 2000
VISIBLE_ROLES = (CustomerMessage.CUSTOMER, CustomerMessage.BUDDY, CustomerMessage.STAFF, CustomerMessage.SYSTEM)


def token_hash(token: str) -> str:
    return hashlib.sha256(f"channel-chat:{token}".encode()).hexdigest()


def normalize_origin(value: str) -> str:
    """``scheme://host[:port]`` in lower case, or "" when it is not an http(s) origin."""
    try:
        parsed = urllib.parse.urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        return ""
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return ""
    host = parsed.hostname.lower()
    return f"{parsed.scheme}://{host}{':' + str(port) if port else ''}"


def allowed_origins(conn) -> set:
    return {o for o in (normalize_origin(v) for v in (conn.config or {}).get("allowed_origins") or []) if o}


def frontend_origin() -> str:
    return normalize_origin(getattr(settings, "FRONTEND_BASE_URL", "") or "")


def site_for(site_key: str):
    if not site_key or len(site_key) > 40:
        return None
    conn = ChannelConnection.objects.select_related("org").filter(kind=ChannelConnection.WEBSITE, site_key=site_key, status=ChannelConnection.ACTIVE).first()
    if conn is None or not conn.org.is_active or not conn.serve_customers:
        return None
    org = conn.org
    if not (effective_flag(org, None, "channels", default=False) and effective_flag(org, None, "customer_buddy", default=False)):
        return None
    return conn


def origin_ok(conn, request, embed_origin: str = "") -> bool:
    origin = request.headers.get("Origin")
    if origin is None:
        return True  # not a cross-site browser request (rate limits still apply)
    origin = normalize_origin(origin)
    allowed = allowed_origins(conn)
    if origin and origin in allowed:
        return True
    if origin and origin == frontend_origin():
        # FloBrain's own chat page: fine on its own, or inside an allowed site's iframe.
        parent = normalize_origin(embed_origin) if embed_origin else ""
        return not embed_origin or parent in allowed
    return False


def _ip(request) -> str:
    return client_ip(request) or "unknown"


def _message(m):
    return {
        "id": str(m.id),
        "role": m.role,
        "text": m.text,
        "created_at": m.created_at.isoformat(),
        "citations": [{"n": c.get("n"), "title": c.get("title")} for c in (m.citations or []) if isinstance(c, dict)],
    }


def _visible(conversation, after=None):
    qs = conversation.messages.filter(status=CustomerMessage.SENT, role__in=VISIBLE_ROLES)
    if after:
        qs = qs.filter(created_at__gt=after)
    return [_message(m) for m in qs.order_by("created_at")[:200]]


def _not_found():
    return Response({"error": "not_found"}, status=404)


def _forbidden():
    return Response({"error": "origin_not_allowed", "details": "This site may not use this chat"}, status=403)


def _limited():
    return Response({"error": "rate_limited", "details": "Too many messages. Wait a minute and try again."}, status=429)


class PublicChatConfigView(V2PublicAPIView):
    @extend_schema(summary="Website chat settings (public)")
    def get(self, request, site_key):
        conn = site_for(site_key)
        if conn is None:
            return _not_found()
        embed = request.query_params.get("embed") or ""
        if not origin_ok(conn, request, embed):
            return _forbidden()
        row = customers.settings_for(conn.org)
        return Response(
            {
                "name": row.buddy_name or conn.org.name,
                "greeting": row.greeting or "Hi! Ask me anything about our products and services.",
                "embed_allowed": (not embed) or normalize_origin(embed) in allowed_origins(conn),
                "demo": conn.demo,
            }
        )


class PublicChatMessagesView(V2PublicAPIView):
    def _conversation(self, conn, token):
        if not token or len(token) > 100:
            return None
        return CustomerConversation.objects.filter(connection=conn, token_hash=token_hash(token)).first()

    @extend_schema(summary="Messages in my website chat (public, by conversation token)")
    def get(self, request, site_key):
        conn = site_for(site_key)
        if conn is None:
            return _not_found()
        if not origin_ok(conn, request, request.query_params.get("embed") or ""):
            return _forbidden()
        if not ratelimit.hit("chat-poll", f"{conn.id}:{_ip(request)}", ratelimit.limit("chat_polls_per_minute", 40), 60):
            return _limited()
        conversation = self._conversation(conn, request.query_params.get("conversation") or "")
        if conversation is None:
            return _not_found()
        return Response({"status": conversation.status, "messages": _visible(conversation)})

    @extend_schema(summary="Send a message to the website chat (public)")
    def post(self, request, site_key):
        conn = site_for(site_key)
        if conn is None:
            return _not_found()
        data = request.data if isinstance(request.data, dict) else {}
        if not origin_ok(conn, request, str(data.get("embed_origin") or "")):
            return _forbidden()
        text = CONTROL.sub(" ", str(data.get("text") or "")).strip()
        if not text:
            return Response({"error": "invalid", "details": "Write a message first"}, status=400)
        if len(text) > MAX_TEXT:
            return Response({"error": "invalid", "details": f"Messages can be up to {MAX_TEXT} characters"}, status=400)
        ip = _ip(request)
        if not ratelimit.hit("chat-ip", f"{conn.id}:{ip}", ratelimit.limit("chat_messages_per_ip_10min", 30), 600):
            return _limited()
        token = str(data.get("conversation") or "")
        new_token = None
        if token:
            conversation = self._conversation(conn, token)
            if conversation is None:
                return _not_found()
        else:
            if not ratelimit.hit("chat-new", f"{conn.id}:{ip}", ratelimit.limit("chat_new_per_ip_hour", 5), 3600):
                return _limited()
            new_token = secrets.token_urlsafe(32)
            name = CONTROL.sub(" ", str(data.get("name") or "")).strip()[:60]
            conversation = CustomerConversation.objects.create(
                org=conn.org,
                connection=conn,
                channel=ChannelConnection.WEBSITE,
                token_hash=token_hash(new_token),
                customer_name=name or f"Website visitor {secrets.randbelow(9000) + 1000}",
                demo=conn.demo,
            )
        if not ratelimit.hit("chat-conv", str(conversation.id), ratelimit.limit("chat_messages_per_conversation_minute", 6), 60):
            return _limited()
        customers.receive(conversation, text)
        conversation.refresh_from_db()
        body = {"status": conversation.status, "messages": _visible(conversation)}
        if new_token:
            body["conversation"] = new_token
        return Response(body, status=201 if new_token else 200)
