"""Bridges settings (flag ``bridges``). Flag off → 501, missing permission → 403, not visible → 404.

Admins (``bridges.manage``):
- ``POST /orgs/{org}/bridges/slack/install`` → Slack authorize URL; ``POST .../slack/confirm`` finishes it
- ``POST /orgs/{org}/bridges/teams/connect`` (Microsoft 365 tenant id); ``GET .../teams/manifest``
- ``PATCH/DELETE /orgs/{org}/bridges/workspaces/{id}``; ``POST .../workspaces/{id}/test``
Every member:
- ``GET /orgs/{org}/bridges`` (status, workspaces, my links; admins also see setup and buddies)
- ``GET/POST /orgs/{org}/bridges/links`` (``?scope=all`` for admins); ``POST .../links/{id}/confirm``;
  ``PATCH/DELETE .../links/{id}``
Demo only: ``POST /orgs/{org}/bridges/demo/simulate`` and ``POST .../demo/decide``.
"""

import json
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from bridges import engine, outbound, setup, slack, teams
from bridges.models import (
    SLACK,
    TEAMS,
    BridgeCard,
    BridgeEvent,
    BridgeLink,
    BridgeOAuthState,
    BridgeWorkspace,
)
from bridges.views_hooks import digest, disconnect, start_install
from channels import vault
from core_v2.views import V2APIView
from integrations import crypto
from organizations.flags import effective_flag
from organizations.models import Organization, OrgMembership
from organizations.permissions import IsActiveOrgMember, can
from organizations.services.core import audit

MANAGE = "bridges.manage"
MIRROR_KEYS = ("approvals", "automations", "escalations")
DEMO_TEAMS_BOT = "00000000-0000-4000-8000-000000000de0"  # clearly not a real Azure app id


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _demo_server() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


def _gate(request, org_id, perm=None):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, "bridges", default=False):
        return org, Response({"error": "not_implemented", "details": "Slack and Teams bridges are not enabled"}, status=501)
    if perm and not can(request.user, perm, org):
        return org, Response({"error": "permission_denied", "details": f"Missing permission: {perm}"}, status=403)
    return org, None


def _invalid(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _not_configured(details, missing=()):
    return Response({"error": "not_configured", "details": details, "missing": list(missing)}, status=501)


# --- payloads ---------------------------------------------------------------------------------


def workspace_payload(ws, manager: bool) -> dict:
    out = {
        "id": str(ws.id),
        "platform": ws.platform,
        "name": ws.name,
        "status": ws.status,
        "demo": ws.demo,
    }
    if manager:
        out.update(
            {
                "external_id": ws.external_id,
                "default_buddy": str(ws.default_buddy_id) if ws.default_buddy_id else None,
                "mirror": {k: bool((ws.mirror or {}).get(k)) for k in MIRROR_KEYS},
                "secret_hints": ws.secret_hints or {},
                "bot_user": (ws.config or {}).get("bot_user_id", ""),
                "last_error": ws.last_error,
                "last_checked_at": ws.last_checked_at.isoformat() if ws.last_checked_at else None,
                "linked_people": ws.links.filter(status=BridgeLink.ACTIVE).count(),
                "pending_people": ws.links.filter(status=BridgeLink.PENDING).count(),
                "created_at": ws.created_at.isoformat(),
            }
        )
    return out


def link_payload(link, with_person=False) -> dict:
    out = {
        "id": str(link.id),
        "workspace": str(link.workspace_id),
        "platform": link.workspace.platform,
        "workspace_name": link.workspace.name,
        "status": link.status,
        "account": link.external_name,
        "email": link.email_masked,
        "found_via": link.found_via,
        "mirror": link.mirror,
        "confirmed_at": link.confirmed_at.isoformat() if link.confirmed_at else None,
        "created_at": link.created_at.isoformat(),
    }
    if with_person:
        out["person"] = {"id": str(link.user_id), "name": link.user.username or link.user.email, "email": link.user.email}
    return out


def card_payload(card) -> dict:
    proposal = card.proposal
    return {
        "id": str(card.id),
        "platform": card.workspace.platform,
        "status": card.status,
        "proposal": {"id": str(proposal.id), "summary": proposal.summary, "status": proposal.status, "tool": proposal.tool_key},
        "message": card.payload or {},
        "created_at": card.created_at.isoformat(),
    }


def _workspaces(org):
    return BridgeWorkspace.objects.filter(org=org).exclude(status=BridgeWorkspace.DISCONNECTED).order_by("platform", "created_at")


# --- overview ---------------------------------------------------------------------------------


class OverviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Slack and Teams: what is connected, my links, and (admins) what the server has")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        manager = can(request.user, MANAGE, org)
        demo = _demo_server()
        links = BridgeLink.objects.filter(org=org, user=request.user).exclude(status=BridgeLink.REVOKED).select_related("workspace")
        out = {
            "demo": demo,
            "can_manage": manager,
            "ready": {"slack": demo or setup.slack_ready(), "teams": demo or setup.teams_ready()},
            "workspaces": [workspace_payload(ws, manager) for ws in _workspaces(org)],
            "my_links": [link_payload(link) for link in links.order_by("-created_at") if link.workspace.status != BridgeWorkspace.DISCONNECTED],
        }
        if manager:
            from buddies.router import NEVER_ROUTE
            from buddies.services import visible_buddies

            out["setup"] = setup.status()
            out["setup"]["teams"]["jwt_library"] = teams.jwt_available()
            out["setup"]["encryption"] = crypto.is_configured()
            out["buddies"] = [
                {"id": str(b.id), "name": b.name, "slug": b.slug}
                for b in visible_buddies(request.user, org).exclude(slug__in=NEVER_ROUTE).order_by("name")[:200]
            ]
        return Response(out)


# --- Slack install ----------------------------------------------------------------------------


def _bound_elsewhere(platform, external_id, org) -> bool:
    return BridgeWorkspace.objects.filter(platform=platform, external_id=external_id).exclude(status=BridgeWorkspace.DISCONNECTED).exclude(org=org).exists()


def _demo_workspace(org, platform, user):
    ws = BridgeWorkspace.objects.filter(org=org, platform=platform, demo=True).exclude(status=BridgeWorkspace.DISCONNECTED).first()
    if ws is not None:
        return ws, False
    external = ("T0DEMO" + uuid.uuid4().hex[:6].upper()) if platform == SLACK else str(uuid.uuid4())
    ws = BridgeWorkspace.objects.create(
        org=org, platform=platform, external_id=external, name=f"{org.name} (demo)"[:120], status=BridgeWorkspace.ACTIVE,
        demo=True, installed_by=user, config={"bot_user_id": "U0FLOBRAIN"} if platform == SLACK else {"bot_id": DEMO_TEAMS_BOT},
        last_checked_at=timezone.now(),
    )
    return ws, True


class SlackInstallView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Start installing the FloBrain Slack app (bridges.manage)")
    def post(self, request, org_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        if _demo_server():
            ws, created = _demo_workspace(org, SLACK, request.user)
            if created:
                audit(request.user, "bridges.connect", target=ws, payload={"platform": SLACK, "demo": True}, request=request, org=org)
            return Response({"simulated": True, "workspace": workspace_payload(ws, True)}, status=201 if created else 200)
        if not setup.slack_ready():
            return _not_configured("Slack is not set up on this server", setup.missing(setup.SLACK_ENV))
        if not crypto.is_configured():
            return _not_configured("Encryption is not configured on this server")
        url = start_install(org, request.user)
        audit(request.user, "bridges.install_started", payload={"platform": SLACK}, request=request, org=org)
        return Response({"authorize_url": url})


class SlackConfirmView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Finish installing Slack: the person who started confirms with the one-time code")
    def post(self, request, org_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        code = str(_body(request).get("code") or "")[:100]
        recent = timezone.now() - timedelta(minutes=30)
        row = (
            BridgeOAuthState.objects.filter(
                org=org, user=request.user, confirm_hash=digest(code), confirmed_at__isnull=True, used_at__isnull=False, created_at__gte=recent
            ).first()
            if code
            else None
        )
        if row is None or not row.result_ciphertext:
            return Response({"error": "not_found", "details": "This install link has expired. Start again."}, status=404)
        if not BridgeOAuthState.objects.filter(pk=row.pk, confirmed_at__isnull=True).update(confirmed_at=timezone.now()):
            return Response({"error": "not_found", "details": "This install link has expired. Start again."}, status=404)
        try:
            result = json.loads(crypto.decrypt(bytes(row.result_ciphertext), f"bridge-oauth:{row.id}", row.org_id, row.key_version))
        except (crypto.CredentialCryptoError, ValueError):
            return _not_configured("The install result can't be read. Start again.")
        finally:
            BridgeOAuthState.objects.filter(pk=row.pk).update(result_ciphertext=None)
        team = result.get("team_id", "")
        if _bound_elsewhere(SLACK, team, org):
            return Response({"error": "conflict", "details": "This Slack workspace is connected to another FloBrain organization."}, status=409)
        with transaction.atomic():
            ws = BridgeWorkspace.objects.filter(org=org, platform=SLACK, external_id=team).exclude(status=BridgeWorkspace.DISCONNECTED).first()
            ws = ws or BridgeWorkspace(org=org, platform=SLACK, external_id=team, installed_by=request.user)
            ws.name = result.get("team_name", "")[:120]
            ws.config = {"bot_user_id": result.get("bot_user_id", ""), "app_id": result.get("app_id", ""), "scopes": result.get("scopes", "")}
            ws.status, ws.last_error, ws.last_checked_at = BridgeWorkspace.ACTIVE, "", timezone.now()
            vault.store(ws, {"bot_token": result.get("bot_token", "")})
            ws.save()
        audit(request.user, "bridges.connect", target=ws, payload={"platform": SLACK, "team": team}, request=request, org=org)
        return Response(workspace_payload(ws, True), status=201)


# --- Teams ------------------------------------------------------------------------------------


class TeamsConnectView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Connect a Microsoft 365 tenant to this org (bridges.manage)")
    def post(self, request, org_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        if _demo_server():
            ws, created = _demo_workspace(org, TEAMS, request.user)
            if created:
                audit(request.user, "bridges.connect", target=ws, payload={"platform": TEAMS, "demo": True}, request=request, org=org)
            return Response({"simulated": True, "workspace": workspace_payload(ws, True)}, status=201 if created else 200)
        if not setup.teams_ready():
            return _not_configured("Microsoft Teams is not set up on this server", setup.missing(setup.TEAMS_ENV))
        if not teams.jwt_available():
            return _not_configured("PyJWT with cryptography is needed on the server to check Teams messages")
        data = _body(request)
        tenant = str(data.get("tenant_id") or "").strip().lower()
        if not teams.GUID.match(tenant):
            return _invalid("The tenant ID is a GUID like 72f988bf-86f1-41af-91ab-2d7cd011db47 (Microsoft Entra admin center, Overview)")
        if _bound_elsewhere(TEAMS, tenant, org):
            return Response({"error": "conflict", "details": "This Microsoft 365 organization is connected to another FloBrain organization."}, status=409)
        ws = BridgeWorkspace.objects.filter(org=org, platform=TEAMS, external_id=tenant).exclude(status=BridgeWorkspace.DISCONNECTED).first()
        created = ws is None
        if created:
            ws = BridgeWorkspace.objects.create(
                org=org, platform=TEAMS, external_id=tenant, name=str(data.get("name") or "Microsoft Teams").strip()[:120],
                status=BridgeWorkspace.ACTIVE, installed_by=request.user, config={"bot_id": setup.env("FLOBRAIN_TEAMS_APP_ID")},
            )
        audit(request.user, "bridges.connect", target=ws, payload={"platform": TEAMS}, request=request, org=org)
        return Response(workspace_payload(ws, True), status=201 if created else 200)


class TeamsManifestView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Teams app manifest.json for upload as a custom app (bridges.manage)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        bot_id = DEMO_TEAMS_BOT if _demo_server() else setup.env("FLOBRAIN_TEAMS_APP_ID")
        if not bot_id:
            return _not_configured("Microsoft Teams is not set up on this server", setup.missing(setup.TEAMS_ENV))
        website = setup.frontend_base() or "https://flobrain.ai"
        if not website.startswith("https://"):
            website = "https://flobrain.ai"
        body = json.dumps(teams.manifest(org, bot_id, website), indent=2)
        response = HttpResponse(body, content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="manifest.json"'
        return response


# --- workspaces -------------------------------------------------------------------------------


class WorkspaceDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Default buddy and notification mirroring (bridges.manage)")
    def patch(self, request, org_id, workspace_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        ws = get_object_or_404(_workspaces(org), pk=workspace_id)
        data = _body(request)
        fields = []
        if "default_buddy" in data:
            value = data.get("default_buddy")
            if value:
                from buddies.services import visible_buddies

                buddy = visible_buddies(request.user, org).filter(pk=_uuid(value)).first()
                if buddy is None:
                    return _invalid("Choose a buddy you can see")
                ws.default_buddy = buddy
            else:
                ws.default_buddy = None
            fields.append("default_buddy")
        if "mirror" in data:
            raw = data.get("mirror")
            if not isinstance(raw, dict) or any(k not in MIRROR_KEYS for k in raw):
                return _invalid("mirror takes approvals, automations and escalations")
            ws.mirror = {**{k: bool((ws.mirror or {}).get(k)) for k in MIRROR_KEYS}, **{k: bool(v) for k, v in raw.items()}}
            fields.append("mirror")
        if "name" in data:
            ws.name = str(data.get("name") or ws.name).strip()[:120]
            fields.append("name")
        ws.save()
        audit(request.user, "bridges.update", target=ws, payload={"fields": fields}, request=request, org=org)
        return Response(workspace_payload(ws, True))

    @extend_schema(summary="Disconnect: delete the bot token and unlink everyone (bridges.manage)")
    def delete(self, request, org_id, workspace_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        ws = get_object_or_404(_workspaces(org), pk=workspace_id)
        if ws.platform == SLACK and not outbound.simulated(ws) and ws.secrets_ciphertext:
            slack.call(ws, "auth.revoke", {})  # best effort: Slack forgets the token too
        disconnect(ws)
        audit(request.user, "bridges.disconnect", target=ws, payload={"platform": ws.platform}, request=request, org=org)
        return Response(status=204)


class WorkspaceTestView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Check the connection with Slack or the Bot Framework (simulated in demo)")
    def post(self, request, org_id, workspace_id):
        org, err = _gate(request, org_id, MANAGE)
        if err:
            return err
        ws = get_object_or_404(_workspaces(org), pk=workspace_id)
        status, error = BridgeWorkspace.ACTIVE, ""
        if outbound.simulated(ws):
            pass
        elif ws.platform == SLACK:
            result = slack.call(ws, "auth.test", {})
            if not result.get("ok"):
                status, error = BridgeWorkspace.ERROR, str(result.get("error") or "provider_error")[:60]
            elif str(result.get("team_id") or "") != ws.external_id:
                status, error = BridgeWorkspace.ERROR, "wrong_workspace"
        else:
            if not setup.teams_ready():
                status, error = BridgeWorkspace.NOT_SET_UP, "not_configured"
            else:
                try:
                    teams.bot_token()
                except outbound.BridgeHTTPError as exc:
                    status, error = BridgeWorkspace.ERROR, exc.code
        ws.status, ws.last_error, ws.last_checked_at = status, error, timezone.now()
        ws.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
        audit(request.user, "bridges.test", target=ws, payload={"status": status, "error": error}, request=request, org=org)
        return Response({**workspace_payload(ws, True), "simulated": outbound.simulated(ws)})


# --- links ------------------------------------------------------------------------------------


def _demo_profile(user, ws):
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"{ws.id}:{user.id}").hex
    external = ("U0" + suffix[:9].upper()) if ws.platform == SLACK else str(uuid.UUID(suffix))
    return {"id": external, "name": user.username or user.email, "email": user.email}


class LinkListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="My Slack and Teams links (admins: ?scope=all lists everyone)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        rows = BridgeLink.objects.filter(org=org).exclude(status=BridgeLink.REVOKED).exclude(workspace__status=BridgeWorkspace.DISCONNECTED)
        everyone = request.query_params.get("scope") == "all"
        if everyone and not can(request.user, MANAGE, org):
            return Response({"error": "permission_denied", "details": f"Missing permission: {MANAGE}"}, status=403)
        if not everyone:
            rows = rows.filter(user=request.user)
        rows = rows.select_related("workspace", "user").order_by("workspace__platform", "-created_at")[:500]
        return Response([link_payload(link, with_person=everyone) for link in rows])

    @extend_schema(summary="Link my Slack or Teams: find my account by email, then I confirm it")
    def post(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        ws = _workspaces(org).filter(pk=_uuid(_body(request).get("workspace")), status=BridgeWorkspace.ACTIVE).first()
        if ws is None:
            return Response({"error": "not_found", "details": "Choose a connected Slack or Teams workspace"}, status=404)
        if not engine.ratelimit.hit("bridge-link-lookup", str(request.user.id), engine.limit("link_lookups_per_hour", 20), 3600):
            return Response({"error": "rate_limited", "details": "Too many tries. Try again later."}, status=429)
        label = engine.PLATFORM_LABEL[ws.platform]
        if outbound.simulated(ws):
            profile = _demo_profile(request.user, ws)
        elif ws.platform == SLACK:
            profile = slack.lookup_email(ws, (request.user.email or "").strip().lower())
        else:
            pending = BridgeLink.objects.filter(workspace=ws, user=request.user, status=BridgeLink.PENDING).first()
            if pending is not None:
                return Response(link_payload(pending), status=200)
            return Response(
                {"error": "not_found", "details": "Write any message to FloBrain in Teams first, then come back here and confirm."}, status=404
            )
        if not profile or profile.get("email", "") != (request.user.email or "").strip().lower():
            return Response(
                {"error": "not_found", "details": f"No {label} account in {ws.name or label} uses your FloBrain email {engine.mask_email(request.user.email)}."},
                status=404,
            )
        active = BridgeLink.objects.filter(workspace=ws, user=request.user, status=BridgeLink.ACTIVE, external_id=profile["id"]).first()
        if active is not None:
            return Response(link_payload(active))
        link = engine.suggest(ws, request.user, profile["id"], profile, BridgeLink.FROM_FLOBRAIN)
        audit(request.user, "bridges.link_found", target=link, payload={"platform": ws.platform}, request=request, org=org)
        return Response(link_payload(link), status=201)


class LinkConfirmView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Confirm that this Slack or Teams account is mine")
    def post(self, request, org_id, link_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        with transaction.atomic():
            link = BridgeLink.objects.select_for_update().filter(pk=link_id, org=org, user=request.user).select_related("workspace").first()
            if link is None or link.workspace.status != BridgeWorkspace.ACTIVE:
                return Response({"error": "not_found", "details": "Link not found"}, status=404)
            if link.status != BridgeLink.PENDING:
                return Response({"error": "conflict", "details": "This link is not waiting for you"}, status=409)
            # One FloBrain person per account and one account per person in a workspace.
            BridgeLink.objects.filter(workspace=link.workspace, status=BridgeLink.ACTIVE).filter(
                Q(external_id=link.external_id) | Q(user=request.user)
            ).update(status=BridgeLink.REVOKED)
            link.status, link.confirmed_at = BridgeLink.ACTIVE, timezone.now()
            link.save(update_fields=["status", "confirmed_at"])
        audit(request.user, "bridges.link", target=link, payload={"platform": link.workspace.platform, "found_via": link.found_via}, request=request, org=org)
        return Response(link_payload(link))


class LinkDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _link(self, request, org, link_id, allow_manager=False):
        link = BridgeLink.objects.filter(pk=link_id, org=org).exclude(status=BridgeLink.REVOKED).select_related("workspace", "user").first()
        if link is None:
            return None
        if link.user_id == request.user.id or (allow_manager and can(request.user, MANAGE, org)):
            return link
        return None

    @extend_schema(summary="Mirror my notifications to this Slack or Teams account, or stop")
    def patch(self, request, org_id, link_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        link = self._link(request, org, link_id)
        if link is None:
            return Response({"error": "not_found", "details": "Link not found"}, status=404)
        data = _body(request)
        if "mirror" in data:
            link.mirror = bool(data["mirror"])
            link.save(update_fields=["mirror"])
        return Response(link_payload(link))

    @extend_schema(summary="Unlink (mine, or anyone's with bridges.manage)")
    def delete(self, request, org_id, link_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        link = self._link(request, org, link_id, allow_manager=True)
        if link is None:
            return Response({"error": "not_found", "details": "Link not found"}, status=404)
        BridgeLink.objects.filter(pk=link.pk).update(status=BridgeLink.REVOKED)
        audit(
            request.user, "bridges.unlink", target=link,
            payload={"platform": link.workspace.platform, "from": "settings", "own": link.user_id == request.user.id}, request=request, org=org,
        )
        return Response(status=204)


# --- demo -------------------------------------------------------------------------------------


def _demo_gate(request, org_id):
    org, err = _gate(request, org_id)
    if err:
        return org, err
    if not (_demo_server() and (org.settings or {}).get("demo") is True):
        return org, Response({"error": "not_found"}, status=404)
    return org, None


def _demo_link(ws, user):
    link = BridgeLink.objects.filter(workspace=ws, user=user, status=BridgeLink.ACTIVE).first()
    if link is None:
        profile = _demo_profile(user, ws)
        link = BridgeLink.objects.create(
            org=ws.org, user=user, workspace=ws, status=BridgeLink.ACTIVE, external_id=profile["id"], external_name=profile["name"],
            email_masked=engine.mask_email(profile["email"]), found_via=BridgeLink.FROM_FLOBRAIN, confirmed_at=timezone.now(),
            config={"dm_channel": "D0DEMO"} if ws.platform == SLACK else {
                "service_url": "https://smba.trafficmanager.net/emea/", "conversation": "a:demo-personal", "teams_user": "29:demo", "bot": "28:demo",
            },
        )
    return link


def _posts(calls) -> list:
    out = []
    for call in calls:
        payload = call.get("payload") or {}
        out.append({"call": call.get("call"), "text": str(payload.get("text") or "")[:4000], "thread": bool(payload.get("thread_ts"))})
    return out


class DemoSimulateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Demo only: a Slack mention or Teams message from me, run end to end without network")
    def post(self, request, org_id):
        org, err = _demo_gate(request, org_id)
        if err:
            return err
        data = _body(request)
        platform = data.get("platform") if data.get("platform") in (SLACK, TEAMS) else SLACK
        text = str(data.get("text") or "").strip()[:2000]
        if not text:
            return _invalid("Write a message")
        ws = BridgeWorkspace.objects.filter(org=org, platform=platform, demo=True, status=BridgeWorkspace.ACTIVE).first()
        if ws is None:
            return _invalid("Connect the demo workspace first")
        link = _demo_link(ws, request.user)
        stamp = f"{time.time():.6f}"
        if platform == SLACK:
            context = {"channel": "C0DEMOLAUNCH", "ts": stamp, "thread_ts": "", "channel_type": "channel"}
        else:
            context = {
                "service_url": "https://smba.trafficmanager.net/emea/", "conversation": "19:demo-launch@thread.tacv2;messageid=1",
                "activity": stamp.replace(".", ""), "conversation_type": "channel", "teams_user": "29:demo", "bot": "28:demo", "tenant": ws.external_id,
            }
        event = engine.record(ws, {"id": f"demo-{uuid.uuid4().hex}", "sender": link.external_id, "sender_name": link.external_name, "text": text, "context": context})
        started = timezone.now()
        with outbound.capture() as calls:
            outcome = engine.process(event.id)
        cards = BridgeCard.objects.filter(workspace=ws, link=link, created_at__gte=started).select_related("proposal", "workspace").order_by("created_at")
        posts = _posts(calls)
        reply = next((p["text"] for p in posts if p["call"] in ("slack.chat.postMessage", "slack.chat.postEphemeral", "teams.send") and p["text"]), "")
        return Response({"simulated": True, "outcome": outcome, "reply": reply, "posts": posts, "cards": [card_payload(c) for c in cards]})


class DemoDecideView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Demo only: press Approve or Reject on a simulated approval message")
    def post(self, request, org_id):
        org, err = _demo_gate(request, org_id)
        if err:
            return err
        data = _body(request)
        decision = data.get("decision")
        if decision not in ("approve", "reject"):
            return _invalid("decision is approve or reject")
        card = BridgeCard.objects.filter(pk=_uuid(data.get("card")), org=org, workspace__demo=True).select_related("workspace", "link", "proposal").first()
        if card is None:
            return Response({"error": "not_found"}, status=404)
        ws = card.workspace
        link = BridgeLink.objects.filter(workspace=ws, user=request.user, status=BridgeLink.ACTIVE).first()
        if link is None:
            return Response({"error": "not_found"}, status=404)
        if ws.platform == SLACK:
            context = {"channel": card.channel, "ts": card.message_id, "proposal": str(card.proposal_id), "channel_type": "action"}
        else:
            context = {**(link.config or {}), "conversation": card.channel, "card_activity": card.message_id, "proposal": str(card.proposal_id), "conversation_type": "personal"}
        event = engine.record(ws, {"id": f"demo-act-{uuid.uuid4().hex}", "kind": BridgeEvent.DECISION, "sender": link.external_id, "text": decision, "context": context})
        with outbound.capture() as calls:
            outcome = engine.process(event.id)
        card.refresh_from_db()
        card.proposal.refresh_from_db()
        return Response({"simulated": True, "outcome": outcome, "posts": _posts(calls), "card": card_payload(card)})
