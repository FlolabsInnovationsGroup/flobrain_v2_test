"""Channels and the customer inbox (W2).

Settings (flag ``channels``; ``channels.manage``):
- ``GET/POST /orgs/{org}/channels/connections``; ``PATCH/DELETE .../connections/{id}``; ``POST .../{id}/test``
- ``GET/PUT /orgs/{org}/channels/customer-settings`` (also flag ``customer_buddy``)
People (flag ``channels``; ``ai.use``):
- ``GET/POST /orgs/{org}/channels/links`` (a one-time code to link my phone or Telegram); ``DELETE .../links/{id}``
Inbox (flag ``customer_buddy``; ``customers.view`` sees all, ``customers.reply`` alone sees what is assigned
to them or to a room they can open; acting needs ``customers.reply``):
- ``GET /orgs/{org}/customers/conversations?status=``; ``GET .../conversations/{id}``
- ``POST .../conversations/{id}/{reply|takeover|handback|resolve|assign}``
- ``POST .../conversations/{id}/messages/{message}/{approve|reject}`` (buddy drafts)
Demo only: ``POST /orgs/{org}/channels/demo/simulate``.

Flag off → 501, missing permission → 403, not visible → 404 (as in other V2 views).
"""

import re
import secrets
import uuid

from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from channels import customers, linking, providers, team, vault
from channels.models import (
    ChannelConnection,
    ChannelLink,
    CustomerConversation,
    CustomerKnowledge,
    CustomerMessage,
    InboundEvent,
)
from channels.views_public import normalize_origin
from core_v2.views import V2APIView
from integrations import crypto
from organizations.flags import effective_flag
from organizations.models import Organization, OrgMembership
from organizations.permissions import IsActiveOrgMember, can
from organizations.services.core import audit

CONFIG_KEYS = {
    ChannelConnection.WHATSAPP: ("phone_number_id", "waba_id", "display_phone"),
    ChannelConnection.TELEGRAM: ("bot_username",),
    ChannelConnection.WEBSITE: ("allowed_origins",),
}
SECRET_RULES = {
    "access_token": re.compile(r"^[A-Za-z0-9_\-.|]{20,1024}$"),
    "app_secret": re.compile(r"^[A-Za-z0-9]{16,128}$"),
    "verify_token": re.compile(r"^[A-Za-z0-9_.-]{8,128}$"),
    "bot_token": providers.TG_BOT_TOKEN,
    "secret_token": providers.TG_SECRET,
}
SECRET_ERRORS = {
    "access_token": "The access token does not look right",
    "app_secret": "The app secret does not look right",
    "verify_token": "The verify token must be 8 to 128 letters, digits, dots, dashes or underscores",
    "bot_token": "The bot token does not look right (it looks like 123456:ABC...)",
    "secret_token": "The secret token must be 16 to 256 letters, digits, dashes or underscores",
}


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _demo_server() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


def _gate(request, org_id, flag, perm=None):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, flag, default=False):
        names = {"channels": "Channels are", "customer_buddy": "The customer buddy is"}
        return org, Response({"error": "not_implemented", "details": f"{names.get(flag, 'This feature is')} not enabled"}, status=501)
    if perm and not can(request.user, perm, org):
        return org, Response({"error": "permission_denied", "details": f"Missing permission: {perm}"}, status=403)
    return org, None


def _invalid(details):
    return Response({"error": "invalid", "details": details}, status=400)


# --- connections ------------------------------------------------------------------------------


def webhook_url(conn) -> str:
    if conn.kind == ChannelConnection.WEBSITE:
        return ""
    base = (getattr(settings, "PUBLIC_API_BASE_URL", "") or "").rstrip("/")
    return f"{base}/api/v2/hooks/{conn.kind}/{conn.id}"


def connection_payload(conn) -> dict:
    keys = CONFIG_KEYS.get(conn.kind, ())
    return {
        "id": str(conn.id),
        "kind": conn.kind,
        "label": conn.label,
        "status": conn.status,
        "config": {k: v for k, v in (conn.config or {}).items() if k in keys},
        "secret_hints": conn.secret_hints or {},
        "site_key": conn.site_key if conn.kind == ChannelConnection.WEBSITE else None,
        "serve_team": conn.serve_team,
        "serve_customers": conn.serve_customers,
        "team_buddy": str(conn.team_buddy_id) if conn.team_buddy_id else None,
        "demo": conn.demo,
        "last_error": conn.last_error,
        "last_checked_at": conn.last_checked_at.isoformat() if conn.last_checked_at else None,
        "webhook_url": webhook_url(conn),
        "linked_people": conn.links.filter(status=ChannelLink.ACTIVE).count(),
        "created_at": conn.created_at.isoformat(),
    }


def _clean_config(kind, raw, current=None):
    raw = raw if isinstance(raw, dict) else {}
    out = dict(current or {})
    if kind == ChannelConnection.WHATSAPP:
        for key in ("phone_number_id", "waba_id"):
            if key in raw:
                value = str(raw.get(key) or "").strip()
                if not providers.WA_ID.match(value):
                    raise ValueError(f"{key.replace('_', ' ')} must be digits from Meta")
                out[key] = value
        if "display_phone" in raw:
            out["display_phone"] = re.sub(r"[^\d+ ]", "", str(raw.get("display_phone") or ""))[:24]
    elif kind == ChannelConnection.WEBSITE and "allowed_origins" in raw:
        values = raw.get("allowed_origins")
        if isinstance(values, str):
            values = [v for v in re.split(r"[\s,]+", values) if v]
        if not isinstance(values, list) or len(values) > 20:
            raise ValueError("List up to 20 website addresses")
        origins = []
        for value in values:
            origin = normalize_origin(value)
            local = origin.startswith(("http://localhost", "http://127.0.0.1"))
            if not origin or (origin.startswith("http://") and not local):
                raise ValueError(f"{str(value)[:80]} is not a website address like https://www.example.com")
            if origin not in origins:
                origins.append(origin)
        out["allowed_origins"] = origins
    return out


def _clean_secrets(kind, raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in vault.SECRET_FIELDS.get(kind, ()):
        value = str(raw.get(key) or "").strip()
        if not value:
            continue
        if not SECRET_RULES[key].match(value):
            raise ValueError(SECRET_ERRORS[key])
        out[key] = value
    return out


def _team_buddy(request, org, value):
    if not value:
        return None
    from buddies.services import visible_buddies

    buddy = visible_buddies(request.user, org).filter(pk=_uuid(value)).first()
    if buddy is None:
        raise ValueError("Choose a buddy you can see")
    return buddy


class ConnectionListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Channel connections (channels.manage)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id, "channels", "channels.manage")
        if err:
            return err
        rows = ChannelConnection.objects.filter(org=org).order_by("kind", "created_at")
        return Response([connection_payload(c) for c in rows])

    @extend_schema(summary="Connect WhatsApp, Telegram or the website chat (channels.manage)")
    def post(self, request, org_id):
        org, err = _gate(request, org_id, "channels", "channels.manage")
        if err:
            return err
        data = _body(request)
        kind = data.get("kind")
        if kind not in CONFIG_KEYS:
            return _invalid("kind must be whatsapp, telegram or website")
        demo = _demo_server()
        try:
            config = _clean_config(kind, data.get("config"))
            secret_values = {} if demo else _clean_secrets(kind, data.get("secrets"))
            buddy = _team_buddy(request, org, data.get("team_buddy"))
        except ValueError as exc:
            return _invalid(str(exc))
        if kind != ChannelConnection.WEBSITE and not demo:
            if not crypto.is_configured():
                return Response({"error": "not_configured", "details": "Encryption is not configured on this server"}, status=501)
            missing = [k for k in vault.SECRET_FIELDS[kind] if k not in secret_values]
            if kind == ChannelConnection.WHATSAPP and "phone_number_id" not in config:
                missing.append("phone_number_id")
            if missing:
                return _invalid(f"Missing: {', '.join(m.replace('_', ' ') for m in missing)}")
        if kind == ChannelConnection.WEBSITE and not config.get("allowed_origins"):
            return _invalid("Add at least one website address that may show the chat")
        default_label = dict(ChannelConnection.KIND_CHOICES)[kind]
        label = str(data.get("label") or default_label).strip()[:100]
        conn = ChannelConnection(
            org=org,
            kind=kind,
            label=f"{label} (demo)" if demo and "(demo)" not in label else label,
            config=config,
            serve_team=bool(data.get("serve_team", kind != ChannelConnection.WEBSITE)) and kind != ChannelConnection.WEBSITE,
            serve_customers=bool(data.get("serve_customers", kind == ChannelConnection.WEBSITE)),
            team_buddy=buddy,
            demo=demo,
            created_by=request.user,
        )
        if kind == ChannelConnection.WEBSITE:
            conn.site_key = secrets.token_urlsafe(18)
            conn.status = ChannelConnection.ACTIVE
        elif demo:
            conn.status = ChannelConnection.ACTIVE  # simulated: no provider is ever called
        if secret_values:
            vault.store(conn, secret_values)
        conn.save()
        audit(request.user, "channels.connect", target=conn, payload={"kind": kind, "demo": demo}, request=request, org=org)
        return Response(connection_payload(conn), status=201)


class ConnectionDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Change a connection (channels.manage); secrets are replaced only when given")
    def patch(self, request, org_id, connection_id):
        org, err = _gate(request, org_id, "channels", "channels.manage")
        if err:
            return err
        conn = get_object_or_404(ChannelConnection, pk=connection_id, org=org)
        data = _body(request)
        try:
            if "config" in data:
                conn.config = _clean_config(conn.kind, data.get("config"), conn.config)
            new_secrets = {} if conn.demo else _clean_secrets(conn.kind, data.get("secrets"))
            if "team_buddy" in data:
                conn.team_buddy = _team_buddy(request, org, data.get("team_buddy"))
        except ValueError as exc:
            return _invalid(str(exc))
        if new_secrets:
            if not crypto.is_configured():
                return Response({"error": "not_configured", "details": "Encryption is not configured on this server"}, status=501)
            vault.store(conn, new_secrets)
            if not conn.demo:
                conn.status = ChannelConnection.NOT_SET_UP  # test again with the new secrets
        if "label" in data:
            conn.label = str(data.get("label") or conn.label).strip()[:120]
        if "serve_team" in data and conn.kind != ChannelConnection.WEBSITE:
            conn.serve_team = bool(data["serve_team"])
        if "serve_customers" in data:
            conn.serve_customers = bool(data["serve_customers"])
        conn.save()
        audit(request.user, "channels.update", target=conn, payload={"fields": sorted(k for k in data if k != "secrets"), "secrets": sorted(new_secrets)}, request=request, org=org)
        return Response(connection_payload(conn))

    @extend_schema(summary="Disconnect: wipe the secrets and unlink everyone (channels.manage)")
    def delete(self, request, org_id, connection_id):
        org, err = _gate(request, org_id, "channels", "channels.manage")
        if err:
            return err
        conn = get_object_or_404(ChannelConnection, pk=connection_id, org=org)
        ChannelConnection.objects.filter(pk=conn.pk).update(
            secrets_ciphertext=None, secret_hints={}, status=ChannelConnection.NOT_SET_UP, site_key=None, last_error="disconnected"
        )
        conn.links.filter(status__in=[ChannelLink.ACTIVE, ChannelLink.PENDING]).update(status=ChannelLink.REVOKED, code_hash="")
        audit(request.user, "channels.disconnect", target=conn, payload={"kind": conn.kind}, request=request, org=org)
        return Response(status=204)


class ConnectionTestView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Test a connection with the provider (simulated in demo)")
    def post(self, request, org_id, connection_id):
        from django.utils import timezone

        org, err = _gate(request, org_id, "channels", "channels.manage")
        if err:
            return err
        conn = get_object_or_404(ChannelConnection, pk=connection_id, org=org)
        if conn.kind == ChannelConnection.WEBSITE and not conn.site_key:
            return Response({"error": "conflict", "details": "This chat was disconnected"}, status=409)
        status, error = providers.check(conn)
        conn.status, conn.last_error, conn.last_checked_at = status, error, timezone.now()
        conn.save(update_fields=["status", "last_error", "last_checked_at", "config", "updated_at"])
        audit(request.user, "channels.test", target=conn, payload={"status": status, "error": error}, request=request, org=org)
        return Response({**connection_payload(conn), "simulated": providers.simulated(conn) and conn.kind != ChannelConnection.WEBSITE})


# --- my links ---------------------------------------------------------------------------------


def link_payload(link) -> dict:
    return {
        "id": str(link.id),
        "connection": str(link.connection_id),
        "kind": link.connection.kind,
        "status": link.status,
        "contact": linking.mask(link.external_id, link.connection.kind),
        "linked_at": link.linked_at.isoformat() if link.linked_at else None,
        "expires_at": link.code_expires_at.isoformat() if link.status == ChannelLink.PENDING and link.code_expires_at else None,
    }


def _linkable(org):
    return ChannelConnection.objects.filter(
        org=org, status=ChannelConnection.ACTIVE, serve_team=True, kind__in=[ChannelConnection.WHATSAPP, ChannelConnection.TELEGRAM]
    )


class LinkListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="My linked phones and Telegram chats, and where I can link")
    def get(self, request, org_id):
        org, err = _gate(request, org_id, "channels", "ai.use")
        if err:
            return err
        from django.utils import timezone

        links = ChannelLink.objects.filter(org=org, user=request.user).filter(
            Q(status=ChannelLink.ACTIVE) | Q(status=ChannelLink.PENDING, code_expires_at__gt=timezone.now())
        ).select_related("connection")
        return Response(
            {
                "links": [link_payload(link) for link in links.order_by("-created_at")],
                "connections": [
                    {
                        "id": str(c.id),
                        "kind": c.kind,
                        "label": c.label,
                        "demo": c.demo,
                        "contact": (c.config or {}).get("display_phone") or ("@" + c.config["bot_username"] if (c.config or {}).get("bot_username") else ""),
                    }
                    for c in _linkable(org)
                ],
            }
        )

    @extend_schema(summary="Make a one-time code to link my phone or Telegram (valid 10 minutes)")
    def post(self, request, org_id):
        org, err = _gate(request, org_id, "channels", "ai.use")
        if err:
            return err
        conn = _linkable(org).filter(pk=_uuid(_body(request).get("connection"))).first()
        if conn is None:
            return Response({"error": "not_found", "details": "Choose an active WhatsApp or Telegram connection"}, status=404)
        link, code = linking.create_code(request.user, org, conn)
        audit(request.user, "channels.link_code", target=link, payload={"kind": conn.kind}, request=request, org=org)
        return Response({**link_payload(link), "code": code}, status=201)


class LinkDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Unlink one of my phones or chats")
    def delete(self, request, org_id, link_id):
        org, err = _gate(request, org_id, "channels")
        if err:
            return err
        link = get_object_or_404(ChannelLink, pk=link_id, org=org, user=request.user)
        ChannelLink.objects.filter(pk=link.pk).update(status=ChannelLink.REVOKED, code_hash="")
        audit(request.user, "channels.unlink", target=link, payload={"from": "settings"}, request=request, org=org)
        return Response(status=204)


# --- customer settings ------------------------------------------------------------------------


def settings_payload(row, request, org) -> dict:
    from docs_app.models import Document
    from rooms.services import accessible_rooms

    rooms = accessible_rooms(request.user, org)
    chosen = list(CustomerKnowledge.objects.filter(org=org).select_related("document"))
    visible = set(Document.objects.filter(org=org, room__in=rooms, pk__in=[k.document_id for k in chosen]).values_list("pk", flat=True))
    docs = Document.objects.filter(org=org, room__in=rooms).select_related("room").order_by("title")[:300]
    return {
        "auto_reply": row.auto_reply,
        "escalation_room": str(row.escalation_room_id) if row.escalation_room_id else None,
        "blocked_topics": row.blocked_topics or [],
        "buddy_name": row.buddy_name,
        "greeting": row.greeting,
        # Documents in rooms this admin cannot open are counted, not named, and stay chosen on save.
        "knowledge": [{"id": str(k.document_id), "title": k.document.title} for k in chosen if k.document_id in visible],
        "hidden_knowledge": len([k for k in chosen if k.document_id not in visible]),
        "documents": [{"id": str(d.id), "title": d.title, "room": d.room.name} for d in docs],
        "rooms": [{"id": str(r.id), "name": r.name} for r in rooms.order_by("name")[:200]],
    }


class CustomerSettingsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _gate(self, request, org_id):
        org, err = _gate(request, org_id, "channels", "channels.manage")
        if err:
            return org, err
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if not effective_flag(org, membership, "customer_buddy", default=False):
            return org, Response({"error": "not_implemented", "details": "The customer buddy is not enabled"}, status=501)
        return org, None

    @extend_schema(summary="Customer buddy settings: auto reply, hand-off room, blocked topics, public knowledge")
    def get(self, request, org_id):
        org, err = self._gate(request, org_id)
        if err:
            return err
        return Response(settings_payload(customers.settings_for(org), request, org))

    @extend_schema(summary="Change the customer buddy settings (channels.manage)")
    def put(self, request, org_id):
        from docs_app.models import Document
        from rooms.services import accessible_rooms

        org, err = self._gate(request, org_id)
        if err:
            return err
        data = _body(request)
        row = customers.settings_for(org)
        rooms = accessible_rooms(request.user, org)
        if "auto_reply" in data:
            row.auto_reply = bool(data["auto_reply"])
        if "escalation_room" in data:
            value = data.get("escalation_room")
            room = rooms.filter(pk=_uuid(value)).first() if value else None
            if value and room is None:
                return _invalid("Choose a room you can open")
            row.escalation_room = room
        if "blocked_topics" in data:
            topics = data.get("blocked_topics")
            if isinstance(topics, str):
                topics = [t for t in re.split(r"[\n,]+", topics)]
            if not isinstance(topics, list) or len(topics) > 50:
                return _invalid("List up to 50 blocked topics")
            row.blocked_topics = list(dict.fromkeys(str(t).strip()[:60] for t in topics if str(t).strip()))
        if "buddy_name" in data:
            row.buddy_name = str(data.get("buddy_name") or "").strip()[:60]
        if "greeting" in data:
            row.greeting = str(data.get("greeting") or "").strip()[:300]
        if "knowledge" in data:
            ids = data.get("knowledge")
            if not isinstance(ids, list) or len(ids) > 200:
                return _invalid("knowledge must be a list of document ids")
            wanted = {u for u in (_uuid(i) for i in ids) if u}
            docs = list(Document.objects.filter(org=org, pk__in=wanted, room__in=rooms))
            if len(docs) != len(wanted):
                return _invalid("Choose documents you can open")
            # Only documents this admin can open are added or removed here.
            CustomerKnowledge.objects.filter(org=org, document__room__in=rooms).exclude(document__in=docs).delete()
            for doc in docs:
                CustomerKnowledge.objects.get_or_create(org=org, document=doc, defaults={"added_by": request.user})
        row.updated_by = request.user
        row.save()
        audit(
            request.user,
            "channels.customer_settings",
            target=row,
            payload={"auto_reply": row.auto_reply, "knowledge": CustomerKnowledge.objects.filter(org=org).count(), "topics": len(row.blocked_topics)},
            request=request,
            org=org,
        )
        return Response(settings_payload(row, request, org))


# --- customer inbox ---------------------------------------------------------------------------


def visible_conversations(user, org):
    qs = CustomerConversation.objects.filter(org=org)
    if can(user, "customers.view", org):
        return qs
    if can(user, "customers.reply", org):
        from rooms.services import accessible_rooms

        return qs.filter(Q(assignee=user) | Q(assigned_room__in=accessible_rooms(user, org)))
    return qs.none()


def _person(user):
    from rooms.services import display_name

    return {"id": str(user.id), "name": display_name(user)} if user else None


def conversation_payload(c, full=False) -> dict:
    data = {
        "id": str(c.id),
        "channel": c.channel,
        "connection": str(c.connection_id),
        "customer_name": c.customer_name,
        "contact": c.contact_masked,
        "status": c.status,
        "mode": c.mode,
        "escalation_reason": c.escalation_reason,
        "assigned_room": str(c.assigned_room_id) if c.assigned_room_id else None,
        "assigned_room_name": c.assigned_room.name if c.assigned_room_id else "",
        "assignee": _person(c.assignee),
        "demo": c.demo,
        "last_message_at": c.last_message_at.isoformat(),
        "created_at": c.created_at.isoformat(),
    }
    if full:
        data["messages"] = [
            {
                "id": str(m.id),
                "role": m.role,
                "text": m.text,
                "status": m.status,
                "citations": m.citations or [],
                "media": {"type": (m.media or {}).get("type")} if m.media else {},
                "author": _person(m.author),
                "approved_by": _person(m.approved_by),
                "delivery_error": m.delivery_error,
                "created_at": m.created_at.isoformat(),
            }
            for m in c.messages.select_related("author", "approved_by").order_by("created_at")
        ]
    else:
        last = c.messages.exclude(status=CustomerMessage.REJECTED).order_by("-created_at").first()
        data["preview"] = (last.text[:140] if last else "")
        data["drafts"] = c.draft_count if hasattr(c, "draft_count") else c.messages.filter(status=CustomerMessage.DRAFT).count()
    return data


def _inbox_gate(request, org_id):
    org, err = _gate(request, org_id, "customer_buddy")
    if err:
        return org, err
    if not (can(request.user, "customers.view", org) or can(request.user, "customers.reply", org)):
        return org, Response({"error": "permission_denied", "details": "Missing permission: customers.view"}, status=403)
    return org, None


class ConversationListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Customer conversations I can see (?status=open|waiting_human|resolved|drafts)")
    def get(self, request, org_id):
        org, err = _inbox_gate(request, org_id)
        if err:
            return err
        qs = visible_conversations(request.user, org).select_related("assigned_room", "assignee").annotate(
            draft_count=Count("messages", filter=Q(messages__status=CustomerMessage.DRAFT))
        )
        status = request.query_params.get("status")
        if status in dict(CustomerConversation.STATUS_CHOICES):
            qs = qs.filter(status=status)
        elif status == "drafts":
            qs = qs.filter(draft_count__gt=0)
        if request.query_params.get("mine") == "1":
            qs = qs.filter(assignee=request.user)
        return Response([conversation_payload(c) for c in qs.order_by("-last_message_at")[:200]])


def _visible_or_404(request, org, conversation_id):
    return get_object_or_404(visible_conversations(request.user, org).select_related("assigned_room", "assignee", "connection"), pk=conversation_id)


class ConversationDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One customer conversation with drafts and citations")
    def get(self, request, org_id, conversation_id):
        org, err = _inbox_gate(request, org_id)
        if err:
            return err
        return Response(conversation_payload(_visible_or_404(request, org, conversation_id), full=True))


ACTIONS = ("reply", "takeover", "handback", "resolve", "assign")


class ConversationActionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Reply, take over, hand back to the buddy, resolve or assign (customers.reply)")
    def post(self, request, org_id, conversation_id, action):
        org, err = _inbox_gate(request, org_id)
        if err:
            return err
        if action not in ACTIONS:
            return Response({"error": "not_found"}, status=404)
        conversation = _visible_or_404(request, org, conversation_id)
        if not can(request.user, "customers.reply", org):
            return Response({"error": "permission_denied", "details": "Missing permission: customers.reply"}, status=403)
        data = _body(request)
        payload = {}
        if action == "reply":
            text = str(data.get("text") or "").strip()
            if not text or len(text) > 4000:
                return _invalid("Write a reply of up to 4000 characters")
            message = customers.staff_reply(conversation, request.user, text)
            payload = {"delivered": message.status == CustomerMessage.SENT, "error": message.delivery_error}
        elif action == "takeover":
            CustomerConversation.objects.filter(pk=conversation.pk).update(
                mode=CustomerConversation.MODE_HUMAN, assignee=conversation.assignee or request.user
            )
        elif action == "handback":
            CustomerConversation.objects.filter(pk=conversation.pk).update(
                mode=CustomerConversation.MODE_BUDDY, status=CustomerConversation.OPEN, escalation_reason=""
            )
        elif action == "resolve":
            CustomerConversation.objects.filter(pk=conversation.pk).update(status=CustomerConversation.RESOLVED, mode=CustomerConversation.MODE_BUDDY)
            conversation.messages.filter(status=CustomerMessage.DRAFT).update(status=CustomerMessage.REJECTED)
        elif action == "assign":
            updates = {}
            if "assignee" in data:
                assignee = None
                if data.get("assignee"):
                    member = OrgMembership.objects.filter(org=org, user_id=_uuid(data.get("assignee")), employment_status="active").select_related("user").first()
                    if member is None or not can(member.user, "customers.reply", org):
                        return _invalid("Choose a member who can reply to customers")
                    assignee = member.user
                updates["assignee"] = assignee
            if "room" in data:
                from rooms.services import accessible_rooms

                room = accessible_rooms(request.user, org).filter(pk=_uuid(data.get("room"))).first() if data.get("room") else None
                if data.get("room") and room is None:
                    return _invalid("Choose a room you can open")
                updates["assigned_room"] = room
            if not updates:
                return _invalid("Give an assignee or a room")
            CustomerConversation.objects.filter(pk=conversation.pk).update(**updates)
        audit(request.user, f"customers.{action}", target=conversation, payload=payload, request=request, org=org)
        conversation = CustomerConversation.objects.select_related("assigned_room", "assignee").get(pk=conversation.pk)
        return Response({**conversation_payload(conversation, full=True), **payload})


class DraftDecisionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Send (optionally edited) or discard a buddy draft (customers.reply)")
    def post(self, request, org_id, conversation_id, message_id, decision):
        org, err = _inbox_gate(request, org_id)
        if err:
            return err
        if decision not in ("approve", "reject"):
            return Response({"error": "not_found"}, status=404)
        conversation = _visible_or_404(request, org, conversation_id)
        if not can(request.user, "customers.reply", org):
            return Response({"error": "permission_denied", "details": "Missing permission: customers.reply"}, status=403)
        message = get_object_or_404(CustomerMessage, pk=message_id, conversation=conversation, role=CustomerMessage.BUDDY)
        if decision == "approve":
            text = str(_body(request).get("text") or "").strip()
            if len(text) > 4000:
                return _invalid("Replies can be up to 4000 characters")
            sent = customers.approve_draft(message, request.user, text or None)
            if sent is None:
                return Response({"error": "conflict", "details": "This draft was already decided"}, status=409)
            payload = {"delivered": sent.status == CustomerMessage.SENT, "error": sent.delivery_error, "edited": bool(text)}
        else:
            if not customers.reject_draft(message, request.user):
                return Response({"error": "conflict", "details": "This draft was already decided"}, status=409)
            payload = {}
        audit(request.user, f"customers.draft_{decision}", target=message, payload=payload, request=request, org=org)
        conversation = CustomerConversation.objects.select_related("assigned_room", "assignee").get(pk=conversation.pk)
        return Response({**conversation_payload(conversation, full=True), **payload})


# --- demo -------------------------------------------------------------------------------------


class DemoSimulateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Demo only: pretend a message arrived on a demo connection")
    def post(self, request, org_id):
        org, err = _gate(request, org_id, "channels")
        if err:
            return err
        if not (_demo_server() and (org.settings or {}).get("demo") is True):
            return Response({"error": "not_found"}, status=404)
        data = _body(request)
        conn = ChannelConnection.objects.filter(org=org, pk=_uuid(data.get("connection")), demo=True, status=ChannelConnection.ACTIVE).first()
        if conn is None:
            return _invalid("Choose a demo connection")
        text = str(data.get("text") or "").strip()[:2000]
        if not text:
            return _invalid("Write a message")
        sender = data.get("from")
        if sender == "me":
            if conn.kind == ChannelConnection.WEBSITE or not can(request.user, "ai.use", org):
                return _invalid("Only WhatsApp and Telegram reach your buddy")
            link = ChannelLink.objects.filter(connection=conn, user=request.user, status=ChannelLink.ACTIVE).first()
            if link is None:
                from django.utils import timezone

                external = f"2010{secrets.randbelow(10**7):07d}" if conn.kind == ChannelConnection.WHATSAPP else str(secrets.randbelow(10**9))
                link = ChannelLink.objects.create(org=org, user=request.user, connection=conn, status=ChannelLink.ACTIVE, external_id=external, linked_at=timezone.now())
            event = InboundEvent.objects.create(org=org, connection=conn, provider_message_id=f"demo-{uuid.uuid4().hex}", sender=link.external_id, text=text)
            reply = team.handle(conn, link, event)
            InboundEvent.objects.filter(pk=event.pk).update(status=InboundEvent.DONE, outcome="team:simulated")
            return Response({"simulated": True, "reply": reply})
        if not (can(request.user, "channels.manage", org) or can(request.user, "customers.reply", org)):
            return Response({"error": "permission_denied", "details": "Missing permission: customers.reply"}, status=403)
        if not effective_flag(org, OrgMembership.objects.filter(org=org, user=request.user).first(), "customer_buddy", default=False):
            return Response({"error": "not_implemented", "details": "The customer buddy is not enabled"}, status=501)
        name = str(data.get("name") or "Demo customer").strip()[:60]
        if conn.kind == ChannelConnection.WEBSITE:
            conversation = CustomerConversation.objects.create(
                org=org, connection=conn, channel=conn.kind, customer_name=name, demo=True, token_hash=secrets.token_hex(32)
            )
        else:
            external = f"2011{secrets.randbelow(10**7):07d}" if conn.kind == ChannelConnection.WHATSAPP else str(secrets.randbelow(10**9))
            conversation = customers.find_or_open(conn, external, name, linking.mask(external, conn.kind))
        customers.receive(conversation, text)
        conversation = CustomerConversation.objects.select_related("assigned_room", "assignee").get(pk=conversation.pk)
        return Response({"simulated": True, "conversation": conversation_payload(conversation, full=True)}, status=201)
