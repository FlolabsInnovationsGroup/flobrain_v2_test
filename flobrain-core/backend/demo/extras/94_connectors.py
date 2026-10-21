"""Write-back connectors demo: all six providers connected as simulated accounts (labelled demo,
no tokens, never any network), Youssef's own Google account, a "Back office buddy" that may propose
every connector action, a few connector actions on the Project Management buddy, one action an
admin turned off, and a recent actions log with done, waiting, failed and rejected rows.

Approving a demo action runs the simulated executor, which returns an example.com link."""

from datetime import timedelta

BACK_OFFICE_PROMPT = (
    "You help with back-office work in the tools this workspace connected: email, calendar, Jira, "
    "HubSpot, Odoo and Zoho. Propose one action at a time and say exactly what it will do. "
    "Never claim it ran: a person approves every write."
)
PM_EXTRA = ["jira.create_issue", "jira.add_comment", "jira.transition_issue", "google_workspace.gmail_send", "hubspot.create_contact"]


def seed(org, users, now):
    from actions.models import ActionProposal
    from brain.models import Chat, Message
    from buddies.models import Buddy
    from integrations.write import registry
    from integrations.write.models import WriteActionToggle, WriteConnection

    admin, member, lead = users["admin"], users["member"], users["lead"]

    conns = {}
    for provider in registry.providers():
        conns[provider.key] = WriteConnection.objects.create(
            org=org,
            provider=provider.key,
            account_label=provider.demo_label or f"{provider.name} (demo, simulated)",
            scopes=provider.scopes(),
            config=dict(provider.demo_config),
            status=WriteConnection.STATUS_CONNECTED,
            demo=True,
            connected_by=admin,
            created_at=now - timedelta(days=12),
            last_used_at=now - timedelta(hours=3),
        )
    WriteConnection.objects.create(
        org=org, owner=member, provider="google_workspace", account_label="youssef@nile-labs.example (demo, simulated)",
        scopes=registry.get("google_workspace").scopes(), status=WriteConnection.STATUS_CONNECTED, demo=True,
        connected_by=member, created_at=now - timedelta(days=5),
    )
    WriteActionToggle.objects.create(org=org, tool_key="zoho.books_create_invoice", enabled=False, updated_by=admin)

    buddy = Buddy.objects.create(
        org=org, slug="back-office", name="Back office buddy", icon="briefcase", created_by=admin,
        description="Sends email, books meetings and updates Jira, HubSpot, Odoo and Zoho. Every write waits for your approval.",
        system_prompt=BACK_OFFICE_PROMPT,
        preset_prompts=[
            {"label": "Jira bug", "prompt": "Create a Jira issue for the Android login bug"},
            {"label": "Send the NDA", "prompt": "Send the NDA to counsel by Gmail"},
            {"label": "New contact", "prompt": "Add Mona Saleh from Delta Trading to HubSpot"},
            {"label": "Draft invoice", "prompt": "Create a draft invoice for Delta Trading in Odoo for 2,500"},
        ],
        allowed_sources={"mode": "accessible", "source_types": ["doc", "room_message"]},
        allowed_tools=[a.tool_key for a in registry.actions()],
        visibility=Buddy.VIS_ORG, share_status=Buddy.SHARE_APPROVED, share_decided_by=admin,
    )
    pm = Buddy.objects.filter(org=org, slug="project-management").first()
    if pm is not None:
        pm.allowed_tools = list(dict.fromkeys([*(pm.allowed_tools or []), *PM_EXTRA]))
        pm.save(update_fields=["allowed_tools"])

    rows = (
        # (hours ago, who, tool, arguments, summary, status, result or error)
        (
            50, member, "jira.create_issue",
            {"project_key": "APP", "summary": "Android login times out on slow networks", "issue_type": "Bug"},
            "Create Jira Bug in APP: “Android login times out on slow networks” [demo, simulated]",
            ActionProposal.STATUS_EXECUTED,
            {"id": "APP-214", "url": "https://jira.example.com/browse/APP-214", "title": "APP-214 Android login times out on slow networks"},
        ),
        (
            30, admin, "hubspot.create_contact",
            {"email": "mona.saleh@example.com", "firstname": "Mona", "lastname": "Saleh", "company": "Delta Trading"},
            "Add HubSpot contact Mona Saleh <mona.saleh@example.com> at Delta Trading [demo, simulated]",
            ActionProposal.STATUS_EXECUTED,
            {"id": "4410021", "url": "https://crm.example.com/hubspot/record/0-1/4410021", "title": "Mona Saleh"},
        ),
        (
            20, admin, "odoo.create_invoice_draft",
            {"customer": "Nile Freight", "lines": [{"description": "Onboarding workshop", "quantity": 1, "unit_price": "4000"}]},
            "Create a draft Odoo invoice for Nile Freight: 1 line, total 4,000.00 (draft only, not posted or sent) [demo, simulated]",
            ActionProposal.STATUS_FAILED,
            "No Odoo customer named “Nile Freight”",
        ),
        (
            8, lead, "microsoft_365.teams_post_message",
            {"team_id": "11111111-2222-4333-8444-555555555555", "channel_id": "19:general@thread.tacv2", "channel_name": "General", "body": "Release 2.4 is live."},
            "Post in #General on Microsoft Teams: “Release 2.4 is live.” [demo, simulated]",
            ActionProposal.STATUS_REJECTED,
            None,
        ),
        (
            1, member, "google_workspace.gmail_send",
            {"to": ["counsel@example.com"], "subject": "NDA for review", "body": "Hello,\n\nSharing the NDA with Delta Trading for your review.\n\nBest regards"},
            "Send email to counsel@example.com: Subject “NDA for review” [demo, simulated]",
            ActionProposal.STATUS_PROPOSED,
            None,
        ),
    )
    for hours, who, tool, args, summary, status, outcome in rows:
        at = now - timedelta(hours=hours)
        chat = Chat.objects.create(user=who, org=org, buddy=buddy, title=summary[:60])
        Message.objects.create(chat=chat, role=Message.ROLE_USER, text=summary.split(" [demo")[0], created_at=at)
        provider_key = tool.split(".", 1)[0]
        fields = dict(
            org=org, user=who, thread=chat, buddy=buddy, tool_key=tool, arguments=args, summary=summary, status=status,
            created_at=at, expires_at=at + timedelta(days=1) if status != ActionProposal.STATUS_PROPOSED else now + timedelta(hours=23),
        )
        if status != ActionProposal.STATUS_PROPOSED:
            fields.update(decided_by=who, decided_at=at + timedelta(minutes=6))
        if status == ActionProposal.STATUS_EXECUTED:
            fields["result"] = {
                "provider": provider_key, "action": tool.split(".", 1)[1], **outcome, "simulated": True,
                "connection": str(conns[provider_key].id), "account": conns[provider_key].account_label,
            }
        if status == ActionProposal.STATUS_FAILED:
            fields["error"] = outcome
        ActionProposal.objects.create(**fields)
