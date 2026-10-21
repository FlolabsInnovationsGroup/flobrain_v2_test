"""Microsoft Teams through the Bot Framework: inbound token checks, activity parsing, replies,
Adaptive Card approvals and the Teams app manifest.

Inbound: every activity carries ``Authorization: Bearer <JWT>`` from the Bot Connector. We check it
with PyJWT against the Bot Framework signing keys (OpenID metadata at
``https://login.botframework.com/v1/.well-known/openidconfiguration``, keys cached for a day and
refreshed at most every 5 minutes for an unknown key id): RS256 only, issuer
``https://api.botframework.com``, audience = our app id, not expired (5 minutes of clock skew, as
Microsoft documents), the key endorses the activity's channel, and the token's ``serviceUrl`` claim
equals the activity's ``serviceUrl``.

Outbound: replies go only to the activity's ``serviceUrl`` when its host is ``*.botframework.com``
or ``smba.trafficmanager.net``, with a client-credentials token from ``login.microsoftonline.com``
(app id and secret from the environment; cached in this process until shortly before expiry).
"""

import json
import logging
import re
import threading
import time
import urllib.parse

from django.core.cache import cache

from bridges import outbound
from bridges.setup import env

logger = logging.getLogger(__name__)

OPENID_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
ISSUER = "https://api.botframework.com"
LEEWAY = 300
JWKS_CACHE = "bridges:teams:jwks"
JWKS_TTL = 24 * 3600
REFRESH_EVERY = 300
BOT_SCOPE = "https://api.botframework.com/.default"
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
CONVERSATION = re.compile(r"^[A-Za-z0-9:@._;=\-]{1,300}$")
ACTIVITY_ID = re.compile(r"^[A-Za-z0-9:@._|\-]{1,200}$")
AT_TAG = re.compile(r"<at>.*?</at>", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]{1,200}>")
MAX_TEXT = 3500

_last_refresh = {"at": 0.0}
_token_cache: dict = {}
_lock = threading.Lock()


class TeamsAuthError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def jwt_available() -> bool:
    try:
        import jwt  # noqa: F401
        from jwt.algorithms import (
            RSAAlgorithm,  # noqa: F401  (needs the cryptography package)
        )
    except ImportError:
        return False
    return True


# --- signing keys -----------------------------------------------------------------------------


def _fetch_jwks() -> list:
    status, meta = outbound.request("GET", OPENID_URL)
    jwks_uri = str(meta.get("jwks_uri") or "") if 200 <= status < 300 else ""
    parsed = urllib.parse.urlparse(jwks_uri)
    if parsed.scheme != "https" or parsed.hostname != "login.botframework.com":
        raise TeamsAuthError("openid_metadata")
    status, body = outbound.request("GET", jwks_uri)
    keys = body.get("keys") if 200 <= status < 300 else None
    if not isinstance(keys, list):
        raise TeamsAuthError("jwks_unavailable")
    return [k for k in keys if isinstance(k, dict) and k.get("kid")]


def signing_keys(force: bool = False) -> list:
    keys = None if force else cache.get(JWKS_CACHE)
    if keys is None:
        keys = _fetch_jwks()
        cache.set(JWKS_CACHE, keys, JWKS_TTL)
        _last_refresh["at"] = time.time()
    return keys


def _key_for(kid: str) -> dict | None:
    keys = signing_keys()
    found = next((k for k in keys if k.get("kid") == kid), None)
    if found is None and time.time() - _last_refresh["at"] > REFRESH_EVERY:
        found = next((k for k in signing_keys(force=True) if k.get("kid") == kid), None)
    return found


def validate(authorization: str | None, activity: dict, *, app_id: str | None = None) -> dict:
    """The verified token claims, or raises ``TeamsAuthError``."""
    if not jwt_available():
        raise TeamsAuthError("jwt_unavailable")
    import jwt

    app_id = env("FLOBRAIN_TEAMS_APP_ID") if app_id is None else app_id
    if not app_id:
        raise TeamsAuthError("not_configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise TeamsAuthError("missing_token")
    token = authorization[7:].strip()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TeamsAuthError("bad_token") from exc
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise TeamsAuthError("bad_algorithm")
    try:
        jwk = _key_for(str(header["kid"]))
    except outbound.BridgeHTTPError as exc:
        raise TeamsAuthError("jwks_unavailable") from exc
    if jwk is None:
        raise TeamsAuthError("unknown_key")
    channel_id = str(activity.get("channelId") or "")
    endorsements = jwk.get("endorsements")
    if isinstance(endorsements, list) and channel_id not in endorsements:
        raise TeamsAuthError("not_endorsed")
    try:
        key = jwt.PyJWK(jwk, algorithm="RS256").key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=app_id,
            issuer=ISSUER,
            leeway=LEEWAY,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TeamsAuthError("expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise TeamsAuthError("bad_audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise TeamsAuthError("bad_issuer") from exc
    except jwt.PyJWTError as exc:
        raise TeamsAuthError("bad_token") from exc
    service_url = str(activity.get("serviceUrl") or "")
    if not service_url or str(claims.get("serviceUrl") or claims.get("serviceurl") or "") != service_url:
        raise TeamsAuthError("service_url_mismatch")
    if not service_url_ok(service_url):
        raise TeamsAuthError("service_url_not_allowed")
    return claims


def service_url_ok(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.port in (None, 443)
        and not parsed.username
        and outbound.teams_service_host_ok(parsed.hostname or "")
    )


# --- parsing ----------------------------------------------------------------------------------


def tenant_of(activity: dict) -> str:
    tenant = (activity.get("conversation") or {}).get("tenantId") or ((activity.get("channelData") or {}).get("tenant") or {}).get("id") or ""
    tenant = str(tenant)
    return tenant.lower() if GUID.match(tenant) else ""


def clean_text(text: str) -> str:
    text = AT_TAG.sub("", text or "")
    text = TAG.sub("", text)
    return text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()[:MAX_TEXT]


def _mentions_bot(activity: dict) -> bool:
    bot = str((activity.get("recipient") or {}).get("id") or "")
    for entity in activity.get("entities") or []:
        if isinstance(entity, dict) and entity.get("type") == "mention" and str((entity.get("mentioned") or {}).get("id") or "") == bot:
            return True
    return False


def parse(activity: dict) -> dict | None:
    """A message for a buddy, an approval button press (Action.Submit), or None."""
    if not isinstance(activity, dict) or activity.get("type") != "message" or activity.get("channelId") != "msteams":
        return None
    sender = activity.get("from") or {}
    aad = str(sender.get("aadObjectId") or "").lower()
    conversation = activity.get("conversation") or {}
    conv_id = str(conversation.get("id") or "")
    activity_id = str(activity.get("id") or "")
    if not GUID.match(aad) or not CONVERSATION.match(conv_id) or not ACTIVITY_ID.match(activity_id):
        return None
    context = {
        "service_url": str(activity.get("serviceUrl") or "")[:300],
        "conversation": conv_id,
        "activity": activity_id,
        "conversation_type": str(conversation.get("conversationType") or "personal")[:20],
        "teams_user": str(sender.get("id") or "")[:200],
        "bot": str((activity.get("recipient") or {}).get("id") or "")[:200],
        "tenant": tenant_of(activity),
    }
    import hashlib

    event_id = hashlib.sha256(f"{conv_id}|{activity_id}".encode()).hexdigest()
    value = activity.get("value")
    if isinstance(value, dict) and value.get("flo_action") in ("approve", "reject"):
        reply_to = str(activity.get("replyToId") or "")
        return {
            "id": f"act:{event_id}",
            "kind": "decision",
            "sender": aad,
            "sender_name": str(sender.get("name") or "")[:120],
            "text": value["flo_action"],
            "context": {**context, "proposal": str(value.get("proposal") or "")[:64], "card_activity": reply_to if ACTIVITY_ID.match(reply_to) else ""},
        }
    if context["conversation_type"] != "personal" and not _mentions_bot(activity):
        return None
    text = clean_text(str(activity.get("text") or ""))
    return {"id": event_id, "kind": "message", "sender": aad, "sender_name": str(sender.get("name") or "")[:120], "text": text, "context": context}


# --- outbound ---------------------------------------------------------------------------------


def bot_token() -> str:
    """A Bot Connector access token (client credentials), cached in this process."""
    with _lock:
        cached = _token_cache.get("token")
        if cached and cached[1] > time.time() + 120:
            return cached[0]
    tenant = env("FLOBRAIN_TEAMS_TENANT_ID") or "botframework.com"
    if tenant != "botframework.com" and not GUID.match(tenant):
        raise outbound.BridgeHTTPError("not_configured")
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": env("FLOBRAIN_TEAMS_APP_ID"), "client_secret": env("FLOBRAIN_TEAMS_APP_SECRET"), "scope": BOT_SCOPE}
    ).encode()
    status, data = outbound.request(
        "POST", f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", body=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    token = str(data.get("access_token") or "")
    if not 200 <= status < 300 or not token:
        raise outbound.BridgeHTTPError(outbound.status_error(status) if status >= 400 else "invalid_response")
    expires = int(data.get("expires_in") or 3600)
    with _lock:
        _token_cache["token"] = (token, time.time() + expires)
    return token


def _send(workspace, method: str, service_url: str, path: str, payload: dict) -> dict:
    if outbound.simulated(workspace):
        outbound.record_simulated("teams.update" if method == "PUT" else "teams.send", payload)
        return {"ok": True, "id": f"demo-{int(time.time() * 1000)}"}
    if not service_url_ok(service_url):
        return {"ok": False, "error": "host_not_allowed"}
    url = service_url.rstrip("/") + path
    try:
        token = bot_token()
        status, body = outbound.request(
            method, url, body=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
    except outbound.BridgeHTTPError as exc:
        return {"ok": False, "error": exc.code}
    if not 200 <= status < 300:
        return {"ok": False, "error": outbound.status_error(status)}
    return {"ok": True, "id": str(body.get("id") or "")[:200]}


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def reply(workspace, context: dict, text: str = "", attachments: list | None = None) -> dict:
    """Answer in the conversation the activity came from (in the thread for channel posts)."""
    activity = {"type": "message", "text": text[:MAX_TEXT], "textFormat": "plain"}
    if attachments:
        activity["attachments"] = attachments
    conv, act = context.get("conversation", ""), context.get("activity", "")
    return _send(workspace, "POST", context.get("service_url", ""), f"/v3/conversations/{_q(conv)}/activities/{_q(act)}", activity)


def send_to(workspace, service_url: str, conversation: str, text: str = "", attachments: list | None = None) -> dict:
    activity = {"type": "message", "text": text[:MAX_TEXT], "textFormat": "plain"}
    if attachments:
        activity["attachments"] = attachments
    return _send(workspace, "POST", service_url, f"/v3/conversations/{_q(conversation)}/activities", activity)


def update(workspace, service_url: str, conversation: str, activity_id: str, attachments: list) -> dict:
    activity = {"type": "message", "id": activity_id, "attachments": attachments}
    return _send(workspace, "PUT", service_url, f"/v3/conversations/{_q(conversation)}/activities/{_q(activity_id)}", activity)


def open_personal(workspace, service_url: str, bot_id: str, teams_user: str, tenant: str) -> str:
    """The 1:1 conversation id between the bot and this person (created if needed)."""
    if outbound.simulated(workspace):
        outbound.record_simulated("teams.create_conversation", {"members": [{"id": teams_user}]})
        return "a:demo-personal"
    if not service_url_ok(service_url):
        return ""
    payload = {"bot": {"id": bot_id}, "members": [{"id": teams_user}], "isGroup": False, "tenantId": tenant, "channelData": {"tenant": {"id": tenant}}}
    try:
        token = bot_token()
        status, body = outbound.request(
            "POST", service_url.rstrip("/") + "/v3/conversations", body=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
    except outbound.BridgeHTTPError:
        return ""
    conv = str(body.get("id") or "") if 200 <= status < 300 else ""
    return conv if CONVERSATION.match(conv) else ""


def member_profile(workspace, context: dict) -> dict:
    """{id, name, email} of the sender from the conversation roster, {} when unknown."""
    if outbound.simulated(workspace) or not service_url_ok(context.get("service_url", "")):
        return {}
    path = f"/v3/conversations/{_q(context.get('conversation', ''))}/members/{_q(context.get('teams_user', ''))}"
    try:
        token = bot_token()
        status, body = outbound.request("GET", context["service_url"].rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})
    except outbound.BridgeHTTPError:
        return {}
    if not 200 <= status < 300:
        return {}
    email = str(body.get("email") or body.get("userPrincipalName") or "").strip().lower()[:254]
    return {"id": str(body.get("aadObjectId") or "").lower(), "name": str(body.get("name") or "")[:120], "email": email}


# --- Adaptive Cards ---------------------------------------------------------------------------


def _card(body: list, actions: list | None = None) -> list:
    content = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4", "body": body}
    if actions:
        content["actions"] = actions
    return [{"contentType": "application/vnd.microsoft.card.adaptive", "content": content}]


def approval_card(proposal, buddy_name: str) -> list:
    return _card(
        [
            {"type": "TextBlock", "text": "Waiting for your approval", "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": (proposal.summary or proposal.tool_key)[:2000], "wrap": True},
            {"type": "TextBlock", "text": f"Proposed by {buddy_name or 'your buddy'} in FloBrain. Only you can decide.", "isSubtle": True, "size": "Small", "wrap": True},
        ],
        [
            {"type": "Action.Submit", "title": "Approve", "style": "positive", "data": {"flo_action": "approve", "proposal": str(proposal.id)}},
            {"type": "Action.Submit", "title": "Reject", "style": "destructive", "data": {"flo_action": "reject", "proposal": str(proposal.id)}},
        ],
    )


def decided_card(proposal, result_text: str) -> list:
    return _card(
        [
            {"type": "TextBlock", "text": result_text[:300], "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": (proposal.summary or proposal.tool_key)[:2000], "wrap": True},
            {"type": "TextBlock", "text": "Decided in Teams. The record is in FloBrain, Approvals.", "isSubtle": True, "size": "Small", "wrap": True},
        ]
    )


# --- app manifest -----------------------------------------------------------------------------


def manifest(org, bot_id: str, website: str) -> dict:
    """A Teams app manifest (schema 1.17) for uploading as a custom app. Icons are added to the zip by the admin."""
    import uuid

    short = (org.name or "FloBrain")[:20]
    host = urllib.parse.urlparse(website).hostname or "flobrain.ai"
    return {
        "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
        "manifestVersion": "1.17",
        "version": "1.0.0",
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"flobrain-teams:{org.id}:{bot_id}")),
        "developer": {
            "name": "FloBrain",
            "websiteUrl": website,
            "privacyUrl": f"{website}/privacy",
            "termsOfUseUrl": f"{website}/terms",
        },
        "name": {"short": "FloBrain", "full": f"FloBrain for {short}"[:100]},
        "description": {
            "short": "Your FloBrain buddies and approvals in Teams.",
            "full": "Ask your FloBrain buddies in a chat or by mentioning FloBrain in a channel, and approve or reject what they propose. Only people linked to FloBrain get answers.",
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "accentColor": "#7C6BFF",
        "bots": [
            {
                "botId": bot_id,
                "scopes": ["personal", "team", "groupChat"],
                "supportsFiles": False,
                "isNotificationOnly": False,
                "commandLists": [
                    {"scopes": ["personal", "team", "groupChat"], "commands": [{"title": "help", "description": "What FloBrain can do here"}]}
                ],
            }
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": [host],
    }
