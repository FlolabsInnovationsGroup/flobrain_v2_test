"""Public endpoints Slack and the Bot Framework call (no FloBrain sign-in; the platform proves itself).

- ``POST /api/v2/hooks/slack/events``        Events API (url_verification, app_mention, message.im, app_uninstalled)
- ``POST /api/v2/hooks/slack/commands``      the ``/flo`` slash command
- ``POST /api/v2/hooks/slack/interactions``  Approve / Reject buttons
- ``POST /api/v2/hooks/teams/messages``      Bot Framework activities (JWT checked)
- ``GET  /api/v2/bridges/slack/oauth/callback`` the Slack install redirect (single-use state)

Every Slack request is checked with the signing secret before anything is read from it; every Teams
activity with the Bot Connector token. Each answers at once and the work runs on the jobs queue.
Bodies over ``MAX_BODY`` are refused, callers are rate limited, and each event id is handled once.
"""

import hashlib
import json
import logging
import re
import secrets
import urllib.parse
from datetime import timedelta

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from bridges import engine, outbound, setup, slack, teams
from bridges.models import (
    SLACK,
    TEAMS,
    BridgeEvent,
    BridgeLink,
    BridgeOAuthState,
    BridgeWorkspace,
)
from channels import ratelimit
from organizations.flags import client_ip, effective_flag

logger = logging.getLogger(__name__)

MAX_BODY = 256 * 1024
CHALLENGE = re.compile(r"^[A-Za-z0-9_.\-]{1,200}$")


def _err(code, status):
    return JsonResponse({"error": code}, status=status)


def _too_big(request) -> bool:
    try:
        return int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY
    except ValueError:
        return True


def _ip_limited(request, scope) -> bool:
    return not ratelimit.hit(f"bridge-ip-{scope}", client_ip(request) or "unknown", engine.limit("hook_per_ip_per_minute", 600), 60)


def _ws_limited(workspace) -> bool:
    return not ratelimit.hit("bridge-ws", str(workspace.id), engine.limit("hook_per_workspace_per_minute", 300), 60)


def _workspace(platform, external_id):
    if not external_id:
        return None
    ws = (
        BridgeWorkspace.objects.select_related("org")
        .filter(platform=platform, external_id=external_id, status=BridgeWorkspace.ACTIVE, demo=False)
        .first()
    )
    if ws is None or not ws.org.is_active or not effective_flag(ws.org, None, "bridges", default=False):
        return None
    return ws


def _accept(ws, item, kind=BridgeEvent.MESSAGE):
    event = engine.record(ws, item, kind)
    if event is not None:
        engine.dispatch(event)
    return event


def _slack_checked(request):
    """(raw body, error response). Signature first: nothing is parsed before it passes."""
    if not setup.slack_ready():
        return None, _err("not_configured", 501)
    if _ip_limited(request, "slack"):
        return None, _err("rate_limited", 429)
    if _too_big(request):
        return None, _err("too_large", 413)
    body = request.body
    if not slack.signature_ok(body, request.headers.get("X-Slack-Request-Timestamp"), request.headers.get("X-Slack-Signature")):
        return None, _err("bad_signature", 401)
    return body, None


def disconnect(ws, reason="disconnected"):
    BridgeWorkspace.objects.filter(pk=ws.pk).update(
        status=BridgeWorkspace.DISCONNECTED, secrets_ciphertext=None, secret_hints={}, last_error=reason[:120]
    )
    BridgeLink.objects.filter(workspace=ws).exclude(status=BridgeLink.REVOKED).update(status=BridgeLink.REVOKED)


@method_decorator(csrf_exempt, name="dispatch")
class SlackEventsView(View):
    http_method_names = ["post"]

    def post(self, request):
        body, error = _slack_checked(request)
        if error:
            return error
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _err("invalid", 400)
        if not isinstance(payload, dict):
            return _err("invalid", 400)
        if payload.get("type") == "url_verification":
            challenge = str(payload.get("challenge") or "")
            if not CHALLENGE.match(challenge):
                return _err("invalid", 400)
            return JsonResponse({"challenge": challenge})
        ws = _workspace(SLACK, slack.team_of(payload))
        if ws is None:
            return JsonResponse({"ok": True, "ignored": "unknown_workspace"})
        if _ws_limited(ws):
            return _err("rate_limited", 429)
        event_type = (payload.get("event") or {}).get("type") if isinstance(payload.get("event"), dict) else ""
        if event_type in ("app_uninstalled", "tokens_revoked"):
            disconnect(ws, "uninstalled_in_slack")
            return JsonResponse({"ok": True})
        item = slack.parse_event(payload)
        if item is None:
            return JsonResponse({"ok": True, "ignored": "not_for_buddies"})
        event = _accept(ws, item)
        return JsonResponse({"ok": True, "duplicate": event is None})


@method_decorator(csrf_exempt, name="dispatch")
class SlackCommandsView(View):
    http_method_names = ["post"]

    def post(self, request):
        body, error = _slack_checked(request)
        if error:
            return error
        form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        ws = _workspace(SLACK, slack.team_of(form))
        if ws is None:
            return JsonResponse({"response_type": "ephemeral", "text": "FloBrain is not connected to this Slack workspace."})
        if _ws_limited(ws):
            return JsonResponse({"response_type": "ephemeral", "text": "FloBrain is busy. Try again in a minute."})
        item = slack.parse_command(form)
        if item is None:
            return _err("invalid", 400)
        if not item["text"]:
            return JsonResponse({"response_type": "ephemeral", "text": engine.help_text(SLACK)})
        _accept(ws, item, BridgeEvent.COMMAND)
        return JsonResponse({"response_type": "ephemeral", "text": "Asking your buddy. The answer comes here in a moment, only you can see it."})


@method_decorator(csrf_exempt, name="dispatch")
class SlackInteractionsView(View):
    http_method_names = ["post"]

    def post(self, request):
        body, error = _slack_checked(request)
        if error:
            return error
        form = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        try:
            payload = json.loads((form.get("payload") or ["{}"])[0])
        except ValueError:
            return _err("invalid", 400)
        ws = _workspace(SLACK, slack.team_of(payload if isinstance(payload, dict) else {}))
        if ws is None:
            return HttpResponse(status=200)
        if _ws_limited(ws):
            return _err("rate_limited", 429)
        item = slack.parse_action(payload)
        if item is not None:
            _accept(ws, item, BridgeEvent.DECISION)
        return HttpResponse(status=200)


@method_decorator(csrf_exempt, name="dispatch")
class TeamsMessagesView(View):
    http_method_names = ["post"]

    def post(self, request):
        if not setup.teams_ready():
            return _err("not_configured", 501)
        if _ip_limited(request, "teams"):
            return _err("rate_limited", 429)
        if _too_big(request):
            return _err("too_large", 413)
        try:
            activity = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _err("invalid", 400)
        if not isinstance(activity, dict):
            return _err("invalid", 400)
        try:
            teams.validate(request.headers.get("Authorization"), activity)
        except teams.TeamsAuthError as exc:
            logger.info("bridges: teams activity refused: %s", exc.code)
            if exc.code == "jwt_unavailable":
                return _err("not_configured", 501)
            return _err("unauthorized", 401)
        ws = _workspace(TEAMS, teams.tenant_of(activity))
        if ws is None:
            return JsonResponse({}, status=200)
        if _ws_limited(ws):
            return _err("rate_limited", 429)
        item = teams.parse(activity)
        if item is not None:
            _accept(ws, item, item.get("kind") or BridgeEvent.MESSAGE)
        return JsonResponse({}, status=200)


# --- Slack install ----------------------------------------------------------------------------

STATE_TTL = timedelta(minutes=10)


def digest(value: str) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()


def start_install(org, user) -> str:
    state = secrets.token_urlsafe(32)
    BridgeOAuthState.objects.create(org=org, user=user, state_hash=digest(state), expires_at=timezone.now() + STATE_TTL)
    return slack.authorize_url(state)


def _consume(state: str):
    row = BridgeOAuthState.objects.filter(state_hash=digest(state)).select_related("org").first() if state else None
    if row is None or row.used_at is not None or row.expires_at <= timezone.now():
        return None
    if not BridgeOAuthState.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now()):
        return None
    return row


@method_decorator(csrf_exempt, name="dispatch")
class SlackOAuthCallbackView(View):
    """Authenticated by ``state`` only (single use, 10 minutes). It parks the encrypted result and
    sends the browser back with a one-time code; the person who started confirms it signed in."""

    http_method_names = ["get"]

    def get(self, request):
        from integrations import crypto

        if _ip_limited(request, "oauth"):
            return _err("rate_limited", 429)
        state = str(request.GET.get("state") or "")[:200]
        code = str(request.GET.get("code") or "")[:500]
        row = _consume(state)

        def done(result, confirm=""):
            page = f"/w/{urllib.parse.quote(row.org.slug)}/settings/bridges?" if row is not None else "/?"
            suffix = f"&bridge_confirm={urllib.parse.quote(confirm)}" if confirm else ""
            return HttpResponseRedirect(f"{setup.frontend_base()}{page}bridge_result={urllib.parse.quote(result)}{suffix}")

        if row is None:
            return done("invalid_state")
        if request.GET.get("error") or not code:
            return done("cancelled")
        if not setup.slack_ready() or not crypto.is_configured():
            return done("not_configured")
        try:
            result = slack.exchange(code)
        except outbound.BridgeHTTPError as exc:
            logger.info("bridges: slack install exchange failed: %s", exc.code)
            return done("exchange_failed")
        confirm = secrets.token_urlsafe(24)
        row.result_ciphertext = crypto.encrypt(json.dumps(result), f"bridge-oauth:{row.id}", row.org_id)
        row.key_version = crypto.current_key_version()
        row.confirm_hash = digest(confirm)
        row.save(update_fields=["result_ciphertext", "key_version", "confirm_hash"])
        return done("confirm", confirm)
