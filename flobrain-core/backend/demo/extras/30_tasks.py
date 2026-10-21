"""Tasks and time demo data (on top of the core seed's eight tasks and a week of time).

Gives the board real priorities and column order, one blocked task with its reason (the tour
stop "Drag Fix login timeout on Android and see why it's blocked"), one task due tomorrow and one
overdue (with their reminders sent), time across the three categories and the project, and one
entry submitted to the lead for approval. A demo project template is added for "Start a project
from a template". Everything stays in the demo org."""

from datetime import timedelta

PLAN = {
    # title: (priority, due in days, column position)
    "Fix login timeout on Android": ("urgent", 2, 0),
    "Push notifications API": ("high", 1, 1),
    "Design the onboarding screens": ("normal", 6, 2),
    "Security review of sign-in": ("high", 4, 0),
    "Write the launch blog post": ("normal", -2, 1),
    "App store screenshots": ("normal", 9, 2),
    "Crash reporting": ("low", 14, 3),
    "Set up CI for the mobile app": ("normal", -5, 0),
}


def seed(org, users, now):
    from organizations.models import Project
    from tasks.models import ProjectTemplate, Task, TaskActivity, TaskAssignment
    from tasks.services import send_due_reminders
    from timetracking.models import Tag, TimeEntry

    lead, member, designer, admin = users["lead"], users["member"], users["designer"], users["admin"]
    today = now.date()
    tasks = {t.title: t for t in Task.objects.filter(org=org)}

    for title, (priority, due_in, position) in PLAN.items():
        task = tasks.get(title)
        if task is None:
            continue
        task.priority = priority
        task.position = position
        task.due_on = today + timedelta(days=due_in)
        if task.status == Task.STATUS_DONE:
            task.completed_at = now - timedelta(days=1, hours=3)
        task.save(update_fields=["priority", "position", "due_on", "completed_at", "updated_at"])
        TaskAssignment.objects.filter(task=task).exclude(user=lead).update(assigned_by=lead)

    blocked = tasks.get("Fix login timeout on Android")
    if blocked is not None:
        blocked.description = "Sessions on Android drop after about 5 minutes in the background. Reproduce on a real device, then fix the token refresh."
        blocked.blocked_reason = "Waiting for the Android test device (Omar ordered one on Monday)"
        blocked.save(update_fields=["description", "blocked_reason", "updated_at"])
        TaskActivity.objects.create(task=blocked, actor=member, verb="blocked", payload={"reason": blocked.blocked_reason}, created_at=now - timedelta(days=2))

    # Reminders the hourly tick would have sent: "due tomorrow" for Push notifications API,
    # "overdue" for the blog post.
    send_due_reminders(today=today, org=org)

    project = Project.objects.filter(org=org, name="Mobile app launch").first()
    push = tasks.get("Push notifications API")
    entries = TimeEntry.objects.filter(org=org).order_by("started_at")
    plan = {
        member.id: ["projects", "projects", "masterclass", "projects", "onboarding", "projects", "projects"],
        lead.id: ["projects", "masterclass", "projects", "projects", "projects", "projects", "projects"],
        designer.id: ["projects", "projects", "onboarding", "projects", "masterclass", "projects", "projects"],
    }
    seen = {}
    review = Tag.objects.get_or_create(org=org, name="code review")[0]
    for entry in entries:
        index = seen.get(entry.user_id, 0)
        seen[entry.user_id] = index + 1
        categories = plan.get(entry.user_id)
        if not categories:
            continue
        entry.category = categories[index % len(categories)]
        entry.source = TimeEntry.SOURCE_TIMER if index % 3 else TimeEntry.SOURCE_MANUAL
        if entry.category == "projects":
            entry.project = project
            if entry.user_id == member.id and push is not None and index % 2 == 0:
                entry.task = push
                entry.description = "Push notifications API: token registration"
            elif entry.user_id == member.id and blocked is not None and index % 2 == 1:
                entry.task = blocked
                entry.description = "Android login timeout: logs and emulator tries"
        elif entry.category == "masterclass":
            entry.description = "Masterclass: secure mobile auth"
        else:
            entry.description = "Onboarding: dev setup and codebase tour"
        entry.save()
        if push is not None and entry.task_id == push.id:
            entry.tags.add(review)

    # One finished entry from this week waits for Layla's approval; an older one is approved.
    mine = list(TimeEntry.objects.filter(org=org, user=member, ended_at__isnull=False).order_by("-started_at"))
    if mine:
        TimeEntry.objects.filter(pk=mine[0].pk).update(approval_status=TimeEntry.APPROVAL_SUBMITTED, submitted_at=now - timedelta(hours=2))
    if len(mine) > 3:
        TimeEntry.objects.filter(pk=mine[3].pk).update(
            approval_status=TimeEntry.APPROVAL_APPROVED, submitted_at=now - timedelta(days=4), approved_by=lead, approved_at=now - timedelta(days=3)
        )

    ProjectTemplate.objects.get_or_create(
        org=org,
        name="Feature launch (demo template)",
        defaults={
            "created_by": admin,
            "spec": {
                "description": "A small feature from kickoff to release notes.",
                "tasks": [
                    {"title": "Kickoff and scope", "priority": "high", "due_in_days": 1},
                    {"title": "Design review", "due_in_days": 4},
                    {"title": "Build and test", "priority": "high", "due_in_days": 10},
                    {"title": "Release notes", "priority": "low", "due_in_days": 12},
                ],
            },
        },
    )
