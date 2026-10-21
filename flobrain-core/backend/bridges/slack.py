"""Slack: request signatures, payload parsing, Web API calls and Block Kit messages.

Signatures: ``X-Slack-Signature: v0=<hex HMAC-SHA256 of "v0:{timestamp}:{raw body}" with the
signing secret>``, ``X-Slack-Request-Timestamp`` within 5 minutes, constant-time compare.
Web API calls go only to ``https://slack.com/api/*`` (and slash-command ``response_url`` only to
``https://hooks.slack.com/commands/*``). Outbound text is escaped, so a buddy answer can never
ping ``@channel`` or a person.
"""

import hashlib
import hmac
import json
import re
import time
import urllib.parse

from bridges import outbound
from bridges.setup import env, slack_redirect_uri

MAX_SKEW = 300
API = "https://slack.com/api/"
SCOPES = ("app_mentions:read", "chat:write", "commands", "im:history", "im:read", "im:write", "users:read", "users:read.email")
TEAM_ID = re.compile(r"^[TE][A-Z0-9]{2,30}$")
USER_ID = re.compile(r"^[UW][A-Z0-9]{2,30}$")
CHANNEL_ID = re.compile(r"^[CDG][A-Z0-9]{2,30}$")
TS = re.compile(r"^\d{1,12}\.\d{1,8}$")
RESPONSE_URL = re.compile(r"^https://hooks\.slack\.com/commands/[A-Za-z0-9/_-]{10,300}$")
MENTION = re.compile(r"<@[UW][A-Z0-9]+(?:\|[^>]*)?>")
MAX_TEXT = 3500


# --- signatures -------------------------------------------------------------------------------


def signature_ok(body: bytes, timestamp: str | None, signature: str | None, *, secret: str | None = None, now: float | None = None) -> bool:
    secret = env("FLOBRAIN_SLACK_SIGNING_SECRET") if secret is None else secret
    if not secret or not timestamp or not signature or not signature.startswith("v0="):
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts) > MAX_SKEW:
        return False
    base = b"v0:" + str(ts).encode() + b":" + (body or b"")
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.strip().encode())


def sign(body: bytes, timestamp: int, secret: str) -> str:
    """For tests and local tools."""
    return "v0=" + hmac.new(secret.encode(), b"v0:" + str(timestamp).encode() + b":" + body, hashlib.sha256).hexdigest()


# --- parsing ----------------------------------------------------------------------------------


def unescape(text: str) -> str:
    return (text or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_text(text: str) -> str:
    """The person's words: mentions of the bot removed, Slack escaping undone."""
    return unescape(MENTION.sub("", text or "")).strip()[:MAX_TEXT]


def parse_event(payload: dict) -> dict | None:
    """An ``event_callback`` that should reach a buddy, or None (bots, edits, other events)."""
    event = payload.get("event") if isinstance(payload, dict) else None
    if not isinstance(event, dict) or payload.get("type") != "event_callback":
        return None
    kind = event.get("type")
    if event.get("bot_id") or event.get("subtype") or event.get("app_id") and event.get("bot_profile"):
        return None  # our own posts, edits, joins and other bots
    channel = str(event.get("channel") or "")
    if kind == "app_mention":
        if event.get("channel_type") == "im" or channel.startswith("D"):
            return None  # the message.im event handles direct messages
        channel_type = "channel"
    elif kind == "message" and event.get("channel_type") == "im":
        channel_type = "im"
    else:
        return None
    user, ts = str(event.get("user") or ""), str(event.get("ts") or "")
    if not USER_ID.match(user) or not CHANNEL_ID.match(channel) or not TS.match(ts):
        return None
    thread_ts = str(event.get("thread_ts") or "")
    return {
        "id": str(payload.get("event_id") or f"{channel}:{ts}")[:128],
        "sender": user,
        "text": clean_text(str(event.get("text") or "")),
        "context": {"channel": channel, "ts": ts, "thread_ts": thread_ts if TS.match(thread_ts) else "", "channel_type": channel_type},
    }


def parse_command(form) -> dict | None:
    user, channel = str(form.get("user_id") or ""), str(form.get("channel_id") or "")
    trigger = str(form.get("trigger_id") or "")
    if not USER_ID.match(user) or not trigger:
        return None
    response_url = str(form.get("response_url") or "")
    return {
        "id": f"cmd:{trigger}"[:128],
        "sender": user,
        "sender_name": str(form.get("user_name") or "")[:120],
        "text": unescape(str(form.get("text") or "")).strip()[:MAX_TEXT],
        "context": {
            "channel": channel if CHANNEL_ID.match(channel) else "",
            "response_url": response_url if RESPONSE_URL.match(response_url) else "",
            "channel_type": "command",
        },
    }


def parse_action(payload: dict) -> dict | None:
    """An Approve or Reject button press on one of our approval messages."""
    if not isinstance(payload, dict) or payload.get("type") != "block_actions":
        return None
    actions = payload.get("actions") or []
    action = actions[0] if actions and isinstance(actions[0], dict) else {}
    action_id = action.get("action_id")
    if action_id not in ("flo_approve", "flo_reject"):
        return None
    user = str((payload.get("user") or {}).get("id") or "")
    container = payload.get("container") or {}
    channel = str(container.get("channel_id") or (payload.get("channel") or {}).get("id") or "")
    ts = str(container.get("message_ts") or (payload.get("message") or {}).get("ts") or "")
    if not USER_ID.match(user) or not CHANNEL_ID.match(channel) or not TS.match(ts):
        return None
    return {
        "id": f"act:{ts}:{action.get('action_ts') or ''}:{user}"[:128],
        "sender": user,
        "text": "approve" if action_id == "flo_approve" else "reject",
        "context": {"channel": channel, "ts": ts, "proposal": str(action.get("value") or "")[:64], "channel_type": "action"},
    }


def team_of(payload: dict) -> str:
    team = payload.get("team_id") or (payload.get("team") or {}).get("id") if isinstance(payload, dict) else ""
    team = str(team or "")
    return team if TEAM_ID.match(team) else ""


# --- Web API ----------------------------------------------------------------------------------


def _token(workspace) -> str:
    from channels import vault

    return vault.get(workspace, "bot_token")


def call(workspace, method: str, payload: dict | None = None, *, query: dict | None = None) -> dict:
    """Call one Web API method with the workspace's bot token. Returns the JSON (``ok`` false on errors)."""
    if outbound.simulated(workspace):
        outbound.record_simulated(f"slack.{method}", payload or query or {})
        canned = {"ok": True, "ts": f"{int(time.time())}.000100", "channel": (payload or {}).get("channel") or "D0DEMO"}
        if method == "conversations.open":
            canned["channel"] = {"id": "D0DEMO"}
        return canned
    token = _token(workspace)
    if not token:
        return {"ok": False, "error": "not_authed"}
    url = API + method
    headers = {"Authorization": f"Bearer {token}"}
    try:
        if query is not None:
            status, body = outbound.request("GET", f"{url}?{urllib.parse.urlencode(query)}", headers=headers)
        else:
            headers["Content-Type"] = "application/json; charset=utf-8"
            status, body = outbound.request("POST", url, body=json.dumps(payload or {}).encode(), headers=headers)
    except outbound.BridgeHTTPError as exc:
        return {"ok": False, "error": exc.code}
    if not 200 <= status < 300:
        return {"ok": False, "error": outbound.status_error(status)}
    return body if isinstance(body, dict) else {"ok": False, "error": "invalid_response"}


def respond(workspace, response_url: str, text: str) -> bool:
    """Answer a slash command only to the person who typed it (ephemeral)."""
    payload = {"response_type": "ephemeral", "text": escape(text)[:MAX_TEXT]}
    if outbound.simulated(workspace):
        outbound.record_simulated("slack.response_url", payload)
        return True
    if not RESPONSE_URL.match(response_url or ""):
        return False
    try:
        status, _ = outbound_request_hooks(response_url, payload)
    except outbound.BridgeHTTPError:
        return False
    return 200 <= status < 300


def outbound_request_hooks(url: str, payload: dict):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "hooks.slack.com":
        raise outbound.BridgeHTTPError("host_not_allowed")
    from platform_api import net

    try:
        status, _ = net.fetch("POST", url, json.dumps(payload).encode(), {"Content-Type": "application/json"}, timeout=10, max_bytes=1024)
    except (net.UnsafeURL, OSError) as exc:
        raise outbound.BridgeHTTPError("provider_unavailable") from exc
    return status, {}


def post(workspace, channel: str, text: str, *, thread_ts: str = "", blocks: list | None = None) -> dict:
    payload = {"channel": channel, "text": escape(text)[:MAX_TEXT], "unfurl_links": False, "unfurl_media": False}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks:
        payload["blocks"] = blocks
    return call(workspace, "chat.postMessage", payload)


def ephemeral(workspace, channel: str, user: str, text: str) -> dict:
    return call(workspace, "chat.postEphemeral", {"channel": channel, "user": user, "text": escape(text)[:MAX_TEXT]})


def update(workspace, channel: str, ts: str, text: str, blocks: list) -> dict:
    return call(workspace, "chat.update", {"channel": channel, "ts": ts, "text": escape(text)[:MAX_TEXT], "blocks": blocks})


def open_dm(workspace, user: str) -> str:
    result = call(workspace, "conversations.open", {"users": user})
    channel = (result.get("channel") or {}).get("id") if isinstance(result.get("channel"), dict) else ""
    return channel if result.get("ok") and CHANNEL_ID.match(str(channel or "")) else ""


def user_profile(workspace, user: str) -> dict:
    """{id, name, email} for a Slack user (needs users:read and users:read.email). {} when unknown."""
    if outbound.simulated(workspace):
        return {}
    result = call(workspace, "users.info", query={"user": user})
    return _profile(result.get("user")) if result.get("ok") else {}


def lookup_email(workspace, email: str) -> dict:
    if outbound.simulated(workspace):
        return {}
    result = call(workspace, "users.lookupByEmail", query={"email": email})
    return _profile(result.get("user")) if result.get("ok") else {}


def _profile(user) -> dict:
    if not isinstance(user, dict) or user.get("deleted") or user.get("is_bot") or user.get("is_restricted") and user.get("is_stranger"):
        return {}
    profile = user.get("profile") or {}
    uid = str(user.get("id") or "")
    if not USER_ID.match(uid):
        return {}
    return {
        "id": uid,
        "name": str(profile.get("real_name") or user.get("real_name") or user.get("name") or "")[:120],
        "email": str(profile.get("email") or "").strip().lower()[:254],
    }


def authorize_url(state: str) -> str:
    params = {"client_id": env("FLOBRAIN_SLACK_CLIENT_ID"), "scope": ",".join(SCOPES), "redirect_uri": slack_redirect_uri(), "state": state}
    return "https://slack.com/oauth/v2/authorize?" + urllib.parse.urlencode(params)


def exchange(code: str) -> dict:
    """Swap the install code for the bot token. Raises ``BridgeHTTPError``."""
    import base64

    basic = base64.b64encode(f"{env('FLOBRAIN_SLACK_CLIENT_ID')}:{env('FLOBRAIN_SLACK_CLIENT_SECRET')}".encode()).decode()
    body = urllib.parse.urlencode({"code": code, "redirect_uri": slack_redirect_uri()}).encode()
    status, data = outbound.request(
        "POST", API + "oauth.v2.access", body=body, headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    )
    if not 200 <= status < 300 or not data.get("ok"):
        raise outbound.BridgeHTTPError(str(data.get("error") or outbound.status_error(status))[:40])
    team = data.get("team") or {}
    token = str(data.get("access_token") or "")
    if not TEAM_ID.match(str(team.get("id") or "")) or not token.startswith("xoxb-"):
        raise outbound.BridgeHTTPError("invalid_response")
    return {
        "team_id": team["id"],
        "team_name": str(team.get("name") or "")[:120],
        "bot_token": token,
        "bot_user_id": str(data.get("bot_user_id") or "")[:32],
        "app_id": str(data.get("app_id") or "")[:32],
        "scopes": str(data.get("scope") or "")[:500],
    }


# --- Block Kit --------------------------------------------------------------------------------


def approval_blocks(proposal, buddy_name: str) -> list:
    summary = escape(proposal.summary or proposal.tool_key)[:2800]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Waiting for your approval*\n{summary}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": escape(f"Proposed by {buddy_name or 'your buddy'} in FloBrain. Only you can decide.")}]},
        {
            "type": "actions",
            "block_id": "flo_approval",
            "elements": [
                {"type": "button", "action_id": "flo_approve", "style": "primary", "text": {"type": "plain_text", "text": "Approve"}, "value": str(proposal.id)},
                {"type": "button", "action_id": "flo_reject", "style": "danger", "text": {"type": "plain_text", "text": "Reject"}, "value": str(proposal.id)},
            ],
        },
    ]


def decided_blocks(proposal, result_text: str) -> list:
    summary = escape(proposal.summary or proposal.tool_key)[:2800]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{escape(result_text)}*\n{summary}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Decided in Slack. The record is in FloBrain, Approvals."}]},
    ]
