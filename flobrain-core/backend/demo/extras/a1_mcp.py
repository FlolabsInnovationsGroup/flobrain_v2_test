"""MCP hub demo data (growth round M1): "Claude (demo)" connected to FloBrain through OAuth by the
owner and one member, 30 MCP calls in the log (in and out, a few errors, arguments redacted), and
rules on the demo partner agent (one tool turned off, read-only, an end date, one buddy).

Nothing here can be used to sign in: the demo tokens are random and only their hashes are stored,
and no secret is ever shown. No network is used.
"""

import random
import secrets
from datetime import timedelta

CLIENT_ID = "fbc_demo_claude"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"

INBOUND = [
    # (tool, args, ok, error)
    ("tasks_list", {"status": "in_progress"}, True, ""),
    ("knowledge_search", {"query": "launch checklist for the mobile app"}, True, ""),
    ("meetings_recent", {"days": 7}, True, ""),
    ("buddy_ask", {"buddy": "release-notes-helper", "question": "Draft release notes for 2.4"}, True, ""),
    ("approvals_list", {}, True, ""),
    ("tasks_create", {"title": "Book the Android test device"}, True, ""),
    ("rooms_list", {}, True, ""),
    ("time_report", {"days": 7}, False, "missing_scope"),
    ("buddy_ask", {"buddy": "finance-helper", "question": "Q4 spend?"}, False, "not_found"),
    ("data_ask", {"question": "Sign-ups by channel last month"}, True, ""),
]
OUTBOUND = [
    ("partner_status", {"reference": "NL-2041"}, True, ""),
    ("partner_status", {"reference": "NL-2077"}, True, ""),
    ("echo", {"text": "ping"}, False, "tool_denied"),
]


def seed(org, users, now):
    from buddies.models import Buddy
    from platform_api import mcp_hub
    from platform_api.models import (
        ExternalAgentServer,
        MCPCallLog,
        OAuthAccessToken,
        OAuthClient,
        OAuthGrant,
        OAuthRefreshToken,
        hash_token,
    )
    from platform_api.oauth_mcp import DEFAULT_SCOPES, canonical

    from django.conf import settings

    base = (getattr(settings, "PUBLIC_API_BASE_URL", "") or "http://localhost:8000").rstrip("/")
    resource = canonical(base + "/api/mcp")
    client, _ = OAuthClient.objects.update_or_create(
        client_id=CLIENT_ID,
        defaults={"name": "Claude (demo)", "client_uri": "https://claude.ai", "redirect_uris": [REDIRECT], "is_demo": True, "last_used_at": now - timedelta(minutes=12)},
    )
    grants = {}
    for key, scopes, age in (("owner", DEFAULT_SCOPES + ["tasks:write", "automations:write"], 9), ("member", DEFAULT_SCOPES, 3)):
        grant = OAuthGrant.objects.create(
            client=client, user=users[key], org=org, scopes=list(dict.fromkeys(scopes)), resource=resource,
            created_at=now - timedelta(days=age), last_used_at=now - timedelta(minutes=12 if key == "owner" else 95),
        )
        # Random, never shown: the connection looks live, but nobody holds these tokens.
        OAuthAccessToken.objects.create(
            token_hash=hash_token("fba_" + secrets.token_urlsafe(32)), grant=grant, user=users[key], org=org,
            scopes=grant.scopes, resource=resource, expires_at=now + timedelta(minutes=48),
        )
        OAuthRefreshToken.objects.create(token_hash=hash_token("fbr_" + secrets.token_urlsafe(32)), grant=grant, expires_at=now + timedelta(days=27))
        grants[key] = grant

    server = ExternalAgentServer.objects.filter(org=org, name="Partner agent (Demo)").first()
    buddy = Buddy.objects.filter(org=org, slug="release-notes-helper").first()
    if server is not None:
        mcp_hub.save_policy(
            server, users["owner"],
            {"tool_rules": {"echo": "deny"}, "read_only": True, "expires_at": now + timedelta(days=60), "buddy_ids": [str(buddy.id)] if buddy else []},
        )

    rng = random.Random(41)
    rows = []
    for i in range(30):
        at = now - timedelta(minutes=12 + i * 330 + rng.randint(0, 120))
        if server is not None and i % 4 == 3:
            tool, args, ok, error = OUTBOUND[(i // 4) % len(OUTBOUND)]
            rows.append(MCPCallLog(
                org=org, user=users["member"], direction=MCPCallLog.OUTBOUND, client_name=server.name, server=server, tool=tool,
                ok=ok, error=error, duration_ms=rng.randint(80, 900), args_summary=mcp_hub.redact_summary(args), created_at=at,
            ))
            continue
        key = "owner" if i % 3 else "member"
        tool, args, ok, error = INBOUND[i % len(INBOUND)]
        rows.append(MCPCallLog(
            org=org, user=users[key], direction=MCPCallLog.INBOUND, client_name=client.name, grant=grants[key], tool=tool,
            ok=ok, error=error, duration_ms=rng.randint(40, 2400 if tool in ("buddy_ask", "data_ask") else 400),
            args_summary=mcp_hub.redact_summary(args), created_at=at,
        ))
    MCPCallLog.objects.bulk_create(rows)
