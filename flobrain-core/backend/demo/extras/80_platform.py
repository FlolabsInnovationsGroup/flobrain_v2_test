"""Platform demo data: a resolved incident, webhook deliveries in the built-in demo inbox, plans
with a subscription and invoice lines, and an external agent connected to the built-in demo MCP
server (journey 17: its answer carries a prompt injection that FloBrain quotes and ignores).

Everything is labelled "Demo". No network is used: the inbox and the MCP server run in-process.
"""

import json
import time
from datetime import timedelta
from decimal import Decimal

PLANS = (
    ("starter", "Starter (Demo)", 800, ["buddies", "memory_search", "room_ai", "realtime", "ai_actions"], {"seats": 10}),
    ("team", "Team (Demo)", 1900, None, {"seats": 50, "renders_per_month": 100}),
    ("business", "Business (Demo)", 3900, None, {"seats": 500, "renders_per_month": 1000}),
)


def seed(org, users, now):
    _incidents(org, users, now)
    _billing(org, now)
    _webhooks(org, users, now)
    _external_agent(org, users, now)


def _incidents(org, users, now):
    from platform_api.models import Incident

    Incident.objects.create(
        org=org, created_by=users["admin"], title="Demo: room messages arrived late", severity="minor", status="resolved",
        components=["Realtime"], impact="Some messages took up to a minute to appear for the Engineering team.",
        mitigation="Restarted the realtime worker.", user_action="Nothing. Refresh the page if a message looks missing.",
        created_at=now - timedelta(days=3, hours=2), resolved_at=now - timedelta(days=3),
        updates=[
            {"at": (now - timedelta(days=3, hours=2)).isoformat(), "status": "investigating", "message": "Messages are slow to arrive. Looking into it."},
            {"at": (now - timedelta(days=3, hours=1)).isoformat(), "status": "identified", "message": "One realtime worker was stuck."},
            {"at": (now - timedelta(days=3)).isoformat(), "status": "resolved", "message": "Restarted the worker. Messages are on time again."},
        ],
    )
    # Platform-wide demo incident for the public status page (replaced on every demo reset).
    Incident.objects.filter(org__isnull=True, title__startswith="Demo: ").delete()
    Incident.objects.create(
        org=None, title="Demo: AI answers were slow", severity="major", status="resolved", components=["AI"], is_public=True,
        impact="AI answers took longer than usual for about 40 minutes.", mitigation="Moved traffic to a second model host.",
        user_action="Nothing.", created_at=now - timedelta(days=6, hours=1), resolved_at=now - timedelta(days=6),
        updates=[
            {"at": (now - timedelta(days=6, hours=1)).isoformat(), "status": "investigating", "message": "AI answers are slow. We are checking the model host."},
            {"at": (now - timedelta(days=6)).isoformat(), "status": "resolved", "message": "Traffic moved to a second host. Answers are back to normal speed."},
        ],
    )


def _billing(org, now):
    from billing_v2.models import Plan, Subscription, UsageInvoiceLine
    from demo.seed import FLAGS

    plans = {}
    for code, name, price, flags, limits in PLANS:
        plans[code], _ = Plan.objects.update_or_create(
            code=code,
            defaults={"name": name, "price_cents": price, "entitlements": {"flags": flags if flags is not None else list(FLAGS), "limits": limits}, "is_public": True},
        )
    sub = Subscription.objects.create(org=org, plan=plans["team"], status="active", seats=8, current_period_end=now + timedelta(days=12))
    month = now.replace(day=1)
    previous = (month - timedelta(days=1)).strftime("%Y-%m")
    current = month.strftime("%Y-%m")
    for period, ai_cost, gpu in ((previous, "18.4210", 1260), (current, "6.1080", 420)):
        rows = (
            ("seats", Decimal(8), Decimal("19.00")),
            ("ai_platform_cost", Decimal(ai_cost), Decimal("1")),
            ("render_gpu_seconds", Decimal(gpu), Decimal("0.0006")),
        )
        for metric, quantity, unit in rows:
            UsageInvoiceLine.objects.create(org=org, subscription=sub, period=period, metric=metric, quantity=quantity, unit_price=unit, amount=quantity * unit)


def _webhooks(org, users, now):
    from integrations import crypto
    from platform_api import demo_hosts, demo_inbox, webhooks
    from platform_api.models import DemoInboxDelivery, WebhookDelivery, WebhookEndpoint
    from tasks.models import Task

    if not crypto.is_configured():
        return  # the signing secret needs encryption; the inbox stays empty without it
    hook = WebhookEndpoint(org=org, url=demo_hosts.inbox_url(org), events=["task.created", "task.completed", "member.joined"], created_by=users["owner"])
    hook.secret_ciphertext = crypto.encrypt("whsec_demo_" + str(org.id).replace("-", "")[:24], hook.id, org.id)
    hook.key_version = crypto.current_key_version()
    hook.save()
    secret = hook.secret()
    tasks = list(Task.objects.filter(org=org).order_by("created_at")[:2])
    sent = [("member.joined", {"user": str(users["designer"].id)}, 50, secret)]
    sent += [("task.created", {"task": str(t.id), "team": str(t.team_id) if t.team_id else None}, 30 - i * 10, secret) for i, t in enumerate(tasks)]
    # One sent with an old secret, so the inbox shows a failed signature check (and the log a 401).
    if tasks:
        sent.append(("task.completed", {"task": str(tasks[0].id), "team": str(tasks[0].team_id) if tasks[0].team_id else None}, 5, "whsec_old_rotated_secret"))
    for event, data, minutes_ago, key in sent:
        at = now - timedelta(minutes=minutes_ago)
        payload = {"id": f"demo-{event}-{minutes_ago}", "event": event, "org": str(org.id), "created_at": at.isoformat(), "data": data}
        body = json.dumps(payload, sort_keys=True).encode()
        headers = {"FloBrain-Event": event, "FloBrain-Signature": webhooks.sign(key, int(time.time()), body)}
        code = demo_inbox.receive(hook, body, headers)
        ok = code == 200
        WebhookDelivery.objects.create(
            endpoint=hook, event=event, payload=payload, status="delivered" if ok else "failed", attempts=1 if ok else webhooks.MAX_ATTEMPTS,
            response_code=code, error="" if ok else f"http_{code}", created_at=at, delivered_at=at if ok else None,
        )
    DemoInboxDelivery.objects.filter(org=org).update(received_at=now)


def _external_agent(org, users, now):
    from buddies.models import Buddy
    from platform_api import demo_hosts, demo_mcp, external_agents, mcp_client
    from platform_api.models import ExternalAgentCall, ExternalAgentHost, ExternalAgentServer

    owner, member = users["owner"], users["member"]
    ExternalAgentHost.objects.create(org=org, host=demo_hosts.DEMO_MCP_HOST, note="Built-in demo server (no network)", added_by=owner)
    tools = mcp_client.clean_tools(demo_mcp.TOOLS)
    server = ExternalAgentServer(
        org=org, name="Partner agent (Demo)", url=demo_hosts.DEMO_MCP_URL, allowed=True, created_by=owner,
        server_info={"name": "demo-partner-agent", "version": "demo"}, last_checked_at=now,
    )
    external_agents._apply_tools(server, server.server_info, tools)
    server.tools_approved_hash, server.tools_approved_by = server.tools_hash, owner
    server.save()
    buddy = Buddy.objects.filter(org=org, slug="release-notes-helper").first()
    answered = demo_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "partner_status", "arguments": {"reference": "NL-2041"}}})
    text = answered["result"]["content"][0]["text"]
    ExternalAgentCall.objects.create(
        org=org, server=server, user=member, buddy=buddy, via=ExternalAgentCall.VIA_BUDDY, tool="partner_status",
        arguments={"reference": "NL-2041"}, status=ExternalAgentCall.EXECUTED, output=text,
        flags=["untrusted", "instructions_ignored"] if external_agents.instruction_like(text) else ["untrusted"],
        created_at=now - timedelta(hours=2), decided_at=now - timedelta(hours=2), expires_at=now + timedelta(hours=22),
    )
    ExternalAgentCall.objects.create(
        org=org, server=server, user=member, buddy=buddy, via=ExternalAgentCall.VIA_BUDDY, tool="partner_status",
        arguments={"reference": "NL-2077"}, created_at=now - timedelta(minutes=5), expires_at=now + timedelta(hours=23),
    )
