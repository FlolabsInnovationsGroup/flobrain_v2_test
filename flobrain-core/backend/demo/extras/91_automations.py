"""Automations demo data: four workflows (two on) and ten runs with mixed results, one of them
paused on an email approval for Omar (admin). Emails and webhooks are never sent in demo mode."""

from datetime import timedelta


def seed(org, users, now):
    from actions.models import ActionProposal
    from automations.models import AutomationSettings, RunApproval, Workflow, WorkflowRun
    from automations.schedule import next_run
    from rooms.models import Room
    from tasks.models import Task

    admin, lead = users["admin"], users["lead"]
    launch = Room.objects.filter(org=org, kind=Room.KIND_PROJECT).first()
    if launch is None:
        return
    AutomationSettings.objects.update_or_create(
        org=org, defaults={"webhook_hosts": ["hooks.example.com"], "trusted_hosts": [], "updated_by": admin}
    )
    tz = "Africa/Cairo"

    def workflow(name, description, trigger, steps, enabled, key):
        wf = Workflow.objects.create(
            org=org, name=name, description=description, trigger=trigger, trigger_type=trigger["type"], steps=steps,
            enabled=enabled, created_by=admin, run_as=admin, template_key=key, created_at=now - timedelta(days=30),
        )
        if enabled and trigger["type"] == "schedule":
            wf.next_run_at = next_run(trigger, org, now)
            wf.save(update_fields=["next_run_at"])
        return wf

    digest = workflow(
        "Weekly blocked-tasks digest",
        "Every Monday at 09:00, summarise the launch's blocked tasks and post them in the launch room.",
        {"type": "schedule", "every": "week", "weekday": 0, "at": "09:00", "timezone": tz},
        [
            {"type": "ai_prompt", "label": "Summarise blocked tasks", "context": "blocked_tasks", "room": str(launch.id),
             "prompt": "Summarise the blocked tasks: what is blocked, for how long, and who can unblock each one. Short bullet points."},
            {"type": "post_to_room", "room": str(launch.id), "text": "Blocked tasks this week\n\n{{steps.1.output}}"},
        ],
        True,
        "weekly_blocked_digest",
    )
    alert = workflow(
        "Tell the lead when a task is blocked",
        "When a task is marked blocked, notify the lead of its team.",
        {"type": "task_blocked"},
        [{"type": "notify", "roles": ["team_leads"], "text": "“{{trigger.title}}” is blocked: {{trigger.reason}}"}],
        True,
        "blocked_task_alert",
    )
    monthly = workflow(
        "Monthly report by email",
        "On the 1st of each month, write a short report of last month's work and email it after approval.",
        {"type": "schedule", "every": "month", "day": 1, "at": "09:00", "timezone": tz},
        [
            {"type": "ai_prompt", "label": "Write the report", "context": "recent_tasks",
             "prompt": "Write a short monthly report: what was finished, what is in progress, and the main risks."},
            {"type": "send_email", "to": ["leadership@example.com"], "subject": "Nile Labs monthly report (demo)", "body": "{{steps.1.output}}"},
        ],
        False,
        "monthly_report_email",
    )
    brief = workflow(
        "Daily brief for everyone",
        "Each morning at 08:00, every member gets their tasks due today, meetings and approvals waiting.",
        {"type": "schedule", "every": "day", "at": "08:00", "timezone": tz},
        [{"type": "daily_brief", "label": "Send each person their day"}],
        False,
        "daily_brief",
    )

    summary = (
        "1 item(s) need attention:\n- Fix login timeout on Android: blocked 2 days, waiting for the Android test device. "
        "Omar can unblock it by ordering the device.\n\n(Demo summary from FloBrain's demo model.)"
    )

    def entry(n, kind, status, output=None, detail=None, at=None, label=""):
        return {"step": n, "type": kind, "label": label, "status": status, "output": output, "detail": detail or {}, "at": (at or now).isoformat()}

    def run(wf, status, when, reason, log, current, error="", payload=None, triggered_by=None):
        r = WorkflowRun.objects.create(
            org=org, workflow=wf, status=status, reason=reason, trigger_payload=payload or {}, steps=wf.steps,
            step_log=log, current_step=current, error=error, triggered_by=triggered_by, created_at=when,
            started_at=when, finished_at=None if status == WorkflowRun.WAITING else when + timedelta(seconds=4),
            event_key=f"demo:{wf.pk}:{when.isoformat()}",
        )
        return r

    for weeks in (3, 2, 1):
        when = now - timedelta(weeks=weeks, hours=2)
        run(digest, WorkflowRun.DONE, when, "schedule", [
            entry(1, "ai_prompt", "done", summary, {"context": "blocked_tasks"}, when, "Summarise blocked tasks"),
            entry(2, "post_to_room", "done", "Blocked tasks this week", {"room": str(launch.id)}, when),
        ], 2)
    when = now - timedelta(weeks=4, hours=2)
    run(digest, WorkflowRun.FAILED, when, "schedule", [
        entry(1, "ai_prompt", "failed", None, {"error": "The AI step could not run (budget_exceeded)."}, when, "Summarise blocked tasks"),
    ], 0, "The AI step could not run (budget_exceeded).")

    blocked = Task.objects.filter(org=org, is_blocked=True).first()
    payload = {"task": str(blocked.id), "title": blocked.title, "team": str(blocked.team_id or ""), "reason": blocked.blocked_reason} if blocked else {}
    for days, text in ((2, "“Fix login timeout on Android” is blocked: Waiting for the Android test device"), (9, "“Security review of sign-in” is blocked: Waiting for the auth vendor's answer")):
        when = now - timedelta(days=days)
        run(alert, WorkflowRun.DONE, when, "task_blocked", [entry(1, "notify", "done", text, {"notified": 1}, when)], 1, payload=payload)
    when = now - timedelta(days=12)
    run(alert, WorkflowRun.CANCELLED, when, "task_blocked", [], 0, "Automations are switched off.", payload=payload)

    report = (
        "October so far: CI for the mobile app is done; onboarding screens, the push notifications API and the Android "
        "login fix are in progress. Main risk: the Android login timeout is blocked on a test device.\n\n(Demo summary from FloBrain's demo model.)"
    )
    when = now - timedelta(days=33)
    run(monthly, WorkflowRun.DONE, when, "manual", [
        entry(1, "ai_prompt", "done", report, {"context": "recent_tasks"}, when, "Write the report"),
        entry(2, "send_email", "done", "Email “Nile Labs monthly report (demo)” to 1 recipient(s)", {"result": {"sent": False, "simulated": True, "recipients": 1}}, when),
    ], 2, triggered_by=admin)
    when = now - timedelta(hours=3)
    waiting = run(monthly, WorkflowRun.WAITING, when, "manual", [entry(1, "ai_prompt", "done", report, {"context": "recent_tasks"}, when, "Write the report")], 1, triggered_by=admin)
    args = {"workflow": str(monthly.id), "run": str(waiting.id), "to": ["leadership@example.com"], "subject": "Nile Labs monthly report (demo)", "body": report}
    proposal = ActionProposal.objects.create(
        org=org, user=admin, tool_key="automations.send_email", arguments=args,
        summary="Email “Nile Labs monthly report (demo)” to 1 recipient(s)", expires_at=now + timedelta(hours=69), created_at=when,
    )
    RunApproval.objects.create(run=waiting, step=1, proposal=proposal, created_at=when)
    log = list(waiting.step_log) + [entry(2, "send_email", "waiting", None, {"approval": str(proposal.id), "summary": proposal.summary}, when)]
    WorkflowRun.objects.filter(pk=waiting.pk).update(step_log=log)

    when = now - timedelta(days=1, hours=1)
    run(brief, WorkflowRun.DONE, when, "manual", [entry(1, "daily_brief", "done", "Sent 4 daily brief(s).", {"notified": 4}, when, "Send each person their day")], 1, triggered_by=lead)
    for wf in (digest, alert, monthly, brief):
        last = wf.runs.order_by("-created_at").first()
        Workflow.objects.filter(pk=wf.pk).update(last_run_at=last.created_at if last else None)
