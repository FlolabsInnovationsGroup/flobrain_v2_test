"""Bridges demo: a Slack workspace and a Microsoft Teams tenant, both simulated and labelled demo.

Omar, Layla and Youssef are linked in Slack, Layla also in Teams, and Sara has a Teams account
waiting for her to confirm. One approval card already went to Youssef in Slack and was approved.
The settings page has "Simulate a Slack mention", which runs the whole flow without a network.
"""

from datetime import timedelta


def seed(org, users, now):
    from actions.models import ActionProposal
    from bridges.models import (
        SLACK,
        TEAMS,
        BridgeCard,
        BridgeEvent,
        BridgeLink,
        BridgeWorkspace,
    )
    from bridges.slack import decided_blocks
    from buddies.models import Buddy

    admin, lead, member, designer = users["admin"], users["lead"], users["member"], users["designer"]
    planner = Buddy.objects.filter(org=org, slug="project-management").first()

    slack = BridgeWorkspace.objects.create(
        org=org, platform=SLACK, external_id="T0NILEDEMO", name="Nile Labs Slack (demo)", status=BridgeWorkspace.ACTIVE, demo=True,
        config={"bot_user_id": "U0FLOBRAIN", "scopes": "app_mentions:read,chat:write,commands,im:history,im:read,im:write,users:read,users:read.email"},
        default_buddy=planner, mirror={"approvals": True, "automations": True, "escalations": True},
        installed_by=admin, last_checked_at=now - timedelta(hours=2), created_at=now - timedelta(days=6), mirror_cursor=now,
    )
    teams = BridgeWorkspace.objects.create(
        org=org, platform=TEAMS, external_id="0d3e5f00-0000-4000-8000-00000000de30", name="Nile Labs Teams (demo)",
        status=BridgeWorkspace.ACTIVE, demo=True, config={"bot_id": "00000000-0000-4000-8000-000000000de0"},
        mirror={"approvals": True, "automations": False, "escalations": False},
        installed_by=admin, last_checked_at=now - timedelta(hours=2), created_at=now - timedelta(days=4), mirror_cursor=now,
    )

    def link(ws, user, external, name, email, days, status=BridgeLink.ACTIVE, via=BridgeLink.FROM_FLOBRAIN, config=None):
        local, domain = email.split("@", 1)
        return BridgeLink.objects.create(
            org=org, user=user, workspace=ws, status=status, external_id=external, external_name=name,
            email_masked=f"{local[:1]}•••@{domain}", found_via=via, config=config or {},
            created_at=now - timedelta(days=days, minutes=5), confirmed_at=None if status == BridgeLink.PENDING else now - timedelta(days=days),
        )

    link(slack, admin, "U0DEMOOMAR", "Omar Khaled", "omar@nile-labs.example", 6, config={"dm_channel": "D0DEMOOMAR"})
    link(slack, lead, "U0DEMOLAYLA", "Layla Mansour", "layla@nile-labs.example", 5, via=BridgeLink.FROM_PLATFORM, config={"dm_channel": "D0DEMOLAYLA"})
    youssef = link(slack, member, "U0DEMOYOUSSEF", "Youssef Adel", "youssef@nile-labs.example", 3, config={"dm_channel": "D0DEMOYOUSSEF"})
    teams_config = {"service_url": "https://smba.trafficmanager.net/emea/", "conversation": "a:demo-layla", "teams_user": "29:demo-layla", "bot": "28:demo"}
    link(teams, lead, "1a2b3c4d-0000-4000-8000-00000000a001", "Layla Mansour", "layla@nile-labs.example", 4, config=teams_config)
    link(teams, designer, "1a2b3c4d-0000-4000-8000-00000000a002", "Sara Nabil", "sara@nile-labs.example", 0, status=BridgeLink.PENDING, via=BridgeLink.FROM_PLATFORM)

    for i, (who, text, outcome) in enumerate(
        (
            ("U0DEMOLAYLA", "Finance Buddy: what is left in the launch budget?", "answered:0"),
            ("U0DEMOYOUSSEF", "create a task to update the store screenshots", "answered:1"),
            ("U0DEMOOMAR", "help", "help"),
            ("U0DEMOSTRANGER", "who is on call this week?", "not_linked"),
        )
    ):
        BridgeEvent.objects.create(
            org=org, workspace=slack, event_id=f"EvDEMO{i}", sender=who, text=text, status=BridgeEvent.DONE, outcome=outcome,
            context={"channel": "C0DEMOLAUNCH", "ts": f"1760000{i:03d}.000100", "channel_type": "channel"}, created_at=now - timedelta(hours=20 - i),
        )

    if planner is not None:
        proposal = ActionProposal.objects.create(
            org=org, user=member, buddy=planner, tool_key="tasks.create", arguments={"title": "Update the store screenshots"},
            summary="Create task: Update the store screenshots", status=ActionProposal.STATUS_REJECTED, decided_by=member,
            decided_at=now - timedelta(hours=17), created_at=now - timedelta(hours=18),
        )
        BridgeCard.objects.create(
            org=org, workspace=slack, link=youssef, proposal=proposal, channel="D0DEMOYOUSSEF", message_id="1760000001.000200",
            status="decided", payload={"blocks": decided_blocks(proposal, "Rejected")}, created_at=now - timedelta(hours=18),
        )
