"""Token management, webhooks admin, external agents and incidents (V2 session auth)."""

import secrets
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.views import V2APIView
from integrations import crypto
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit
from platform_api import demo_hosts, net, webhooks
from platform_api.models import SCOPES, Incident, PersonalAccessToken, WebhookDelivery, WebhookEndpoint

MAX_TOKENS = 20
MAX_WEBHOOKS = 20
MAX_INCIDENT_UPDATES = 100


def _bad(details):
    return Response({"error": "invalid", "details": str(details)}, status=400)


def _token_payload(t):
    return {
        "id": str(t.id),
        "name": t.name,
        "org": str(t.org_id),
        "scopes": t.scopes,
        "last4": t.last4,
        "created_at": t.created_at.isoformat(),
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "revoked": t.revoked_at is not None,
    }


class MyTokensView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Your personal access tokens (never the secret)")
    def get(self, request):
        rows = PersonalAccessToken.objects.filter(user=request.user).order_by("-created_at")
        return Response([_token_payload(t) for t in rows])

    @extend_schema(summary="Create a personal access token (shown once)")
    def post(self, request):
        import uuid as _uuid

        data = request.data if isinstance(request.data, dict) else {}
        try:
            org_id = _uuid.UUID(str(data.get("org")))
        except ValueError:
            org_id = None
        org = Organization.objects.filter(pk=org_id, is_active=True).first() if org_id else None
        membership = OrgMembership.objects.filter(org=org, user=request.user).first() if org else None
        if membership is None or not membership.is_active_member:
            return Response({"error": "not_found", "details": "Organization not found"}, status=404)
        if not effective_flag(org, membership, "api_access", default=False):
            return Response({"error": "not_implemented", "details": "api_access is not enabled"}, status=501)
        scopes = data.get("scopes") or []
        if not isinstance(scopes, list) or not scopes or not all(isinstance(x, str) for x in scopes) or not set(scopes) <= set(SCOPES):
            return _bad(f"scopes must be a non-empty list from {', '.join(SCOPES)}")
        name = str(data.get("name") or "").strip()[:80]
        if not name:
            return _bad("name is required")
        expires_at = None
        if data.get("expires_in_days") is not None:
            try:
                days = int(data["expires_in_days"])
            except (TypeError, ValueError):
                return _bad("expires_in_days must be a number")
            if not 1 <= days <= 365:
                return _bad("expires_in_days must be 1..365")
            expires_at = timezone.now() + timedelta(days=days)
        if PersonalAccessToken.objects.filter(user=request.user, revoked_at__isnull=True).count() >= MAX_TOKENS:
            return _bad(f"at most {MAX_TOKENS} active tokens")
        token, raw = PersonalAccessToken.issue(request.user, org, name, list(dict.fromkeys(scopes)), expires_at)
        audit(request.user, "pat.create", target=token, payload={"scopes": token.scopes}, request=request, org=org)
        return Response({**_token_payload(token), "token": raw}, status=201)


class MyTokenDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Revoke a token (takes effect on the next request)")
    def delete(self, request, token_id):
        token = PersonalAccessToken.objects.filter(pk=token_id, user=request.user).first()
        if token is None:
            return Response({"error": "not_found", "details": "Token not found"}, status=404)
        if token.revoked_at is None:
            token.revoked_at = timezone.now()
            token.save(update_fields=["revoked_at"])
            audit(request.user, "pat.revoke", target=token, org=token.org)
        return Response(status=204)


def _org_gate(request, view, org_id, perm, flag):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, flag, default=False):
        return org, Response({"error": "not_implemented", "details": f"{flag} is not enabled"}, status=501)
    return org, None


def _hook_payload(h):
    return {
        "id": str(h.id),
        "url": h.url,
        "events": h.events,
        "is_active": h.is_active,
        "created_at": h.created_at.isoformat(),
        "demo_inbox": demo_hosts.is_demo_url(h.url, demo_hosts.DEMO_INBOX_HOST),
    }


def _delivery_payload(d):
    return {
        "id": str(d.id),
        "event": d.event,
        "status": d.status,
        "attempts": d.attempts,
        "max_attempts": webhooks.MAX_ATTEMPTS,
        "response_code": d.response_code,
        "error": d.error,
        "created_at": d.created_at.isoformat(),
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
        "next_attempt_at": d.next_attempt_at.isoformat() if d.status == WebhookDelivery.PENDING else None,
        "payload": d.payload,  # ids and short fields only (webhooks.emit)
    }


class WebhookListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Webhook endpoints (webhooks.manage)")
    def get(self, request, org_id):
        org, error = _org_gate(request, self, org_id, "webhooks.manage", "webhooks")
        if error:
            return error
        return Response([_hook_payload(h) for h in WebhookEndpoint.objects.filter(org=org)])

    @extend_schema(summary="Add a webhook endpoint; the signing secret is shown once")
    def post(self, request, org_id):
        org, error = _org_gate(request, self, org_id, "webhooks.manage", "webhooks")
        if error:
            return error
        if not crypto.is_configured():
            return Response({"error": "not_configured", "details": "Encryption is not configured"}, status=501)
        data = request.data if isinstance(request.data, dict) else {}
        events = data.get("events") or []
        if WebhookEndpoint.objects.filter(org=org).count() >= MAX_WEBHOOKS:
            return _bad(f"at most {MAX_WEBHOOKS} webhook endpoints per org")
        if (
            not isinstance(events, list)
            or not events
            or not all(isinstance(e, str) for e in events)
            or not set(events) <= set(WebhookEndpoint.EVENTS)
        ):
            return _bad(f"events must be a non-empty list from {', '.join(WebhookEndpoint.EVENTS)}")
        url = str(data.get("url") or "")[:500]
        if not demo_hosts.is_demo_url(url, demo_hosts.DEMO_INBOX_HOST):  # the demo inbox exists only in demo mode
            try:
                net.check_url(url)
            except net.UnsafeURL as exc:
                return _bad(exc)
        secret = "whsec_" + secrets.token_urlsafe(32)
        hook = WebhookEndpoint(org=org, url=url, events=list(dict.fromkeys(events)), created_by=request.user)
        hook.secret_ciphertext = crypto.encrypt(secret, hook.id, org.id)
        hook.key_version = crypto.current_key_version()
        hook.save()
        audit(request.user, "webhook.create", target=hook, payload={"events": hook.events}, request=request, org=org)
        return Response({**_hook_payload(hook), "secret": secret}, status=201)


def _hook(request, view, org_id, hook_id):
    org, error = _org_gate(request, view, org_id, "webhooks.manage", "webhooks")
    if error:
        return org, None, error
    hook = WebhookEndpoint.objects.filter(org=org, pk=hook_id).first()
    if hook is None:
        return org, None, Response({"error": "not_found", "details": "Webhook not found"}, status=404)
    return org, hook, None


class WebhookDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="An endpoint and its last 50 deliveries (attempts, status, response code)")
    def get(self, request, org_id, hook_id):
        org, hook, error = _hook(request, self, org_id, hook_id)
        if error:
            return error
        rows = WebhookDelivery.objects.filter(endpoint=hook)[:50]
        return Response({**_hook_payload(hook), "deliveries": [_delivery_payload(d) for d in rows]})

    @extend_schema(summary="Turn an endpoint on or off")
    def patch(self, request, org_id, hook_id):
        org, hook, error = _hook(request, self, org_id, hook_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        if not isinstance(data.get("is_active"), bool):
            return _bad("is_active must be true or false")
        hook.is_active = data["is_active"]
        hook.save(update_fields=["is_active"])
        audit(request.user, "webhook.update", target=hook, payload={"is_active": hook.is_active}, request=request, org=org)
        return Response(_hook_payload(hook))

    @extend_schema(summary="Delete a webhook endpoint")
    def delete(self, request, org_id, hook_id):
        org, error = _org_gate(request, self, org_id, "webhooks.manage", "webhooks")
        if error:
            return error
        deleted, _ = WebhookEndpoint.objects.filter(org=org, pk=hook_id).delete()
        if deleted:
            audit(request.user, "webhook.delete", payload={"id": str(hook_id)}, request=request, org=org)
        return Response(status=204) if deleted else Response({"error": "not_found", "details": "Webhook not found"}, status=404)


class WebhookTestView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Send a signed ping event to this endpoint")
    def post(self, request, org_id, hook_id):
        org, hook, error = _hook(request, self, org_id, hook_id)
        if error:
            return error
        if not hook.is_active:
            return Response({"error": "conflict", "details": "Turn the endpoint on first"}, status=409)
        delivery = webhooks.send_test(hook)
        audit(request.user, "webhook.test", target=hook, request=request, org=org)
        return Response(_delivery_payload(delivery), status=202)


class WebhookDeliveryRetryView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Try a failed or waiting delivery once more, now")
    def post(self, request, org_id, hook_id, delivery_id):
        org, hook, error = _hook(request, self, org_id, hook_id)
        if error:
            return error
        delivery = WebhookDelivery.objects.filter(endpoint=hook, pk=delivery_id).first()
        if delivery is None:
            return Response({"error": "not_found", "details": "Delivery not found"}, status=404)
        if not hook.is_active:
            return Response({"error": "conflict", "details": "Turn the endpoint on first"}, status=409)
        if not webhooks.retry_now(delivery):
            return Response({"error": "conflict", "details": "Only failed or waiting deliveries can be retried"}, status=409)
        audit(request.user, "webhook.retry", target=hook, payload={"delivery": str(delivery.id)}, request=request, org=org)
        delivery.refresh_from_db()
        return Response(_delivery_payload(delivery), status=202)


class DemoInboxView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Demo mode only: what the built-in demo receiver got, with signature checks")
    def get(self, request, org_id):
        if not demo_hosts.enabled():
            return Response({"error": "not_found"}, status=404)
        org, error = _org_gate(request, self, org_id, "webhooks.manage", "webhooks")
        if error:
            return error
        from platform_api.models import DemoInboxDelivery

        rows = DemoInboxDelivery.objects.filter(org=org).select_related("endpoint")[:50]
        return Response(
            {
                "url": demo_hosts.inbox_url(org),
                "demo": True,
                "received": [
                    {
                        "id": str(r.id),
                        "endpoint": str(r.endpoint_id),
                        "event": r.event,
                        "body": r.body,
                        "signature": r.signature,
                        "signature_valid": r.signature_valid,
                        "received_at": r.received_at.isoformat(),
                    }
                    for r in rows
                ],
            }
        )


def _incident_payload(i):
    from platform_api.status import public_incident

    return {**public_incident(i), "is_public": i.is_public, "org": str(i.org_id) if i.org_id else None}


class IncidentListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="The org's incidents (private to the org) and public platform incidents")
    def get(self, request, org_id):
        org, error = _org_gate(request, self, org_id, "incidents.manage", "status_page")
        if error:
            return error
        rows = Incident.objects.filter(org=org) | Incident.objects.filter(org__isnull=True, is_public=True)
        return Response([_incident_payload(i) for i in rows.order_by("-created_at")[:200]])

    @extend_schema(summary="Open an org incident (incidents.manage)")
    def post(self, request, org_id):
        org, error = _org_gate(request, self, org_id, "incidents.manage", "status_page")
        if error:
            return error
        return _save_incident(request, Incident(org=org, created_by=request.user), org)


def _save_incident(request, incident, org, platform=False):
    from django.utils.dateparse import parse_datetime

    data = request.data if isinstance(request.data, dict) else {}
    adding = incident._state.adding
    if "title" in data or adding:
        incident.title = str(data.get("title") or "").strip()[:200] if isinstance(data.get("title"), (str, type(None))) else ""
        if not incident.title:
            return _bad("title is required")
    if "severity" in data:
        if data["severity"] not in Incident.SEVERITIES:
            return _bad("unknown severity")
        incident.severity = data["severity"]
    for field in ("impact", "mitigation", "user_action"):
        if field in data:
            if not isinstance(data.get(field), (str, type(None))):
                return _bad(f"{field} must be text")
            setattr(incident, field, str(data.get(field) or "")[:2000])
    if "components" in data:
        comps = data.get("components") or []
        if not isinstance(comps, list) or not all(isinstance(c, str) and len(c) <= 60 for c in comps):
            return _bad("components must be short names")
        incident.components = comps[:20]
    if "next_update_at" in data:
        raw = data.get("next_update_at")
        if raw in (None, ""):
            incident.next_update_at = None
        else:
            try:
                when = parse_datetime(str(raw))
            except ValueError:
                when = None
            if when is None:
                return _bad("next_update_at must be an ISO date-time")
            incident.next_update_at = when if timezone.is_aware(when) else timezone.make_aware(when)
    previous_status = None if adding else incident.status
    if "status" in data:
        if data["status"] not in Incident.STATUSES:
            return _bad("unknown status")
        incident.status = data["status"]
        incident.resolved_at = (incident.resolved_at or timezone.now()) if data["status"] == "resolved" else None
        if incident.status == "resolved":
            incident.next_update_at = None
    message = data.get("message")
    if message is not None and not isinstance(message, str):
        return _bad("message must be text")
    if message or adding or incident.status != previous_status:
        text = (message or "").strip()[:2000] or ("Resolved." if incident.status == "resolved" else incident.impact[:2000] or incident.title)
        incident.updates = ((incident.updates or []) + [{"at": timezone.now().isoformat(), "status": incident.status, "message": text}])[
            -MAX_INCIDENT_UPDATES:
        ]
    if "is_public" in data:
        # Only platform admins publish to the public status page; org incidents stay private to the org.
        if not platform:
            return Response({"error": "permission_denied", "details": "Only platform admins publish incidents"}, status=403)
        incident.is_public = bool(data["is_public"])
    incident.save()
    if org is not None:  # platform-wide incidents belong to no org's audit log
        audit(request.user, "incident.save", target=incident, payload={"status": incident.status}, request=request, org=org)
    if platform and incident.is_public:
        from platform_api.status import notify_subscribers

        transaction.on_commit(lambda: notify_subscribers(incident))
    return Response(_incident_payload(incident), status=201 if adding else 200)


class IncidentDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Update or resolve an org incident (adds an entry to its updates)")
    def patch(self, request, org_id, incident_id):
        org, error = _org_gate(request, self, org_id, "incidents.manage", "status_page")
        if error:
            return error
        incident = Incident.objects.filter(org=org, pk=incident_id).first()
        if incident is None:
            return Response({"error": "not_found", "details": "Incident not found"}, status=404)
        return _save_incident(request, incident, org)


def _platform_admin(request):
    user = request.user
    return bool(
        user and user.is_authenticated and getattr(user, "is_platform_admin", False)
        and not (isinstance(request.auth, dict) and request.auth.get("impersonation"))
    )


class PlatformIncidentListView(V2APIView):
    permission_classes = []

    @extend_schema(summary="Platform-wide incidents (platform admins)")
    def get(self, request):
        if not _platform_admin(request):
            return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)
        return Response([_incident_payload(i) for i in Incident.objects.filter(org__isnull=True)[:200]])

    @extend_schema(summary="Open a platform-wide incident; is_public puts it on the status page")
    def post(self, request):
        if not _platform_admin(request):
            return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)
        return _save_incident(request, Incident(org=None, created_by=request.user), None, platform=True)


class PlatformIncidentDetailView(V2APIView):
    permission_classes = []

    @extend_schema(summary="Update a platform-wide incident (platform admins)")
    def patch(self, request, incident_id):
        if not _platform_admin(request):
            return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)
        incident = Incident.objects.filter(org__isnull=True, pk=incident_id).first()
        if incident is None:
            return Response({"error": "not_found", "details": "Incident not found"}, status=404)
        return _save_incident(request, incident, None, platform=True)
