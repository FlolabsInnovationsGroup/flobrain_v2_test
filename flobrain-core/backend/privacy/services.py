"""Privacy center logic (Phase 16): what we hold about a person, their export, erasure, retention."""

import io
import json
import zipfile
from datetime import timedelta

from django.db import transaction
from django.utils import timezone


def settings_for(user, org, create=False):
    from privacy.models import PrivacySettings

    if create:
        return PrivacySettings.objects.get_or_create(user=user, org=org)[0]
    return PrivacySettings.objects.filter(user=user, org=org).first() or PrivacySettings(user=user, org=org)


def hides_time_details(owner_id, org_id) -> bool:
    from privacy.models import PrivacySettings

    return PrivacySettings.objects.filter(user_id=owner_id, org_id=org_id, share_time_details_with_org=False).exists()


def inventory(user, org) -> dict:
    """Counts of what FloBrain holds about this person in this org, and who can see it."""
    from brain.models import Chat
    from docs_app.models import DocumentRevision
    from organizations.models import OrgMembership, TeamMembership
    from rooms.models import RoomMessage
    from tasks.models import TaskAssignment
    from telemetry.models import AITrace, UsageEvent
    from timetracking.models import TimeEntry

    leads = TeamMembership.objects.filter(
        team__org=org, team__memberships__user=user, team_role=TeamMembership.ROLE_LEAD
    ).exclude(user=user).select_related("user", "team")
    admins = OrgMembership.objects.filter(org=org, employment_status="active", org_role__in=["owner", "admin"]).count()
    return {
        "data": {
            "room_messages": RoomMessage.objects.filter(room__org=org, author=user, deleted_at__isnull=True).count(),
            "document_edits": DocumentRevision.objects.filter(document__org=org, created_by=user).count(),
            "task_assignments": TaskAssignment.objects.filter(task__org=org, user=user).count(),
            "time_entries": TimeEntry.objects.filter(org=org, user=user).count(),
            "ai_conversations": Chat.objects.filter(org=org, user=user, room__isnull=True).count(),
            "ai_usage_records": UsageEvent.objects.filter(org=org, user=user).count(),
            "ai_traces": AITrace.objects.filter(org=org, user=user).count(),
        },
        "who_can_see": {
            "team_leads": sorted({f"{m.user.username} ({m.team.name})" for m in leads}),
            "owners_and_admins": admins,
            "rules": [
                "Your direct messages and private groups: only their members. Owners and admins can't open them.",
                "Team and project rooms: their members, and owners and admins.",
                "Your time: your team leads and admins see totals; they see descriptions only if you share them.",
                "Your AI conversations: only you. Admins see usage counts and cost, not what you asked.",
                "Mentor notes: only you and your mentor.",
            ],
        },
    }


def _rows(qs, fields):
    return [{f: (str(v) if v is not None and not isinstance(v, (int, float, bool, str, list, dict)) else v) for f, v in zip(fields, row)} for row in qs.values_list(*fields)]


def build_export(user) -> tuple[bytes, dict]:
    """Everything that is the person's own, across orgs, as JSON files in a zip."""
    from brain.models import Chat, Message
    from commissions.models import Commission, Lead
    from learning.models import Certificate, PortfolioItem, QuizAttempt
    from notifications.models import Notification
    from organizations.models import MemberSkill, OrgMembership
    from rooms.models import RoomMessage
    from tasks.models import Task
    from telemetry.models import UsageEvent
    from timetracking.models import TimeEntry

    parts = {
        "profile.json": {
            "email": user.email,
            "username": user.username,
            "timezone": getattr(user, "timezone", None),
            "locale": getattr(user, "locale", None),
            "about_me": getattr(user, "about_me", None),
        },
        "memberships.json": _rows(OrgMembership.objects.filter(user=user), ["org__name", "org_role", "employment_status", "created_at"]),
        "messages_i_wrote.json": _rows(RoomMessage.objects.filter(author=user, deleted_at__isnull=True), ["room__org__name", "room__name", "body", "created_at"]),
        "tasks_assigned_to_me.json": _rows(Task.objects.filter(assignments__user=user), ["org__name", "title", "status", "due_on", "created_at"]),
        "time_entries.json": _rows(TimeEntry.objects.filter(user=user), ["org__name", "description", "started_at", "ended_at"]),
        "ai_conversations.json": [
            {"title": c.title, "created_at": c.created_at.isoformat(), "messages": _rows(Message.objects.filter(chat=c).order_by("created_at"), ["role", "text", "created_at"])}
            for c in Chat.objects.filter(user=user, room__isnull=True)
        ],
        "ai_usage.json": _rows(UsageEvent.objects.filter(user=user), ["org__name", "model", "operation", "total_tokens", "created_at"]),
        "notifications.json": _rows(Notification.objects.filter(user=user), ["org__name", "kind", "created_at", "read_at"]),
        "skills.json": _rows(MemberSkill.objects.filter(user=user), ["org__name", "skill__name"]),
        "certificates.json": _rows(Certificate.objects.filter(user=user), ["org__name", "kind", "data", "public_slug", "issued_at", "revoked_at"]),
        "portfolio.json": _rows(PortfolioItem.objects.filter(user=user), ["org__name", "kind", "title", "summary", "is_public"]),
        "quiz_attempts.json": _rows(QuizAttempt.objects.filter(user=user), ["quiz__title", "score", "passed", "created_at"]),
        "leads.json": _rows(Lead.objects.filter(owner_user=user), ["org__name", "project_or_product", "contact_name", "stage", "created_at"]),
        "commissions.json": _rows(Commission.objects.filter(user=user), ["org__name", "amount", "currency", "status", "created_at"]),
    }
    buffer = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, json.dumps(content, ensure_ascii=False, indent=2, default=str))
            counts[name] = len(content) if isinstance(content, list) else 1
        zf.writestr("README.txt", "Your FloBrain data. Each file is JSON. Messages others wrote are not included; ask them for theirs.\n")
    return buffer.getvalue(), counts


@transaction.atomic
def erase_member_data(org, user) -> dict:
    """Approved deletion request: remove the person's content in this org and its search vectors.
    Records the org must keep (commissions, audit log) stay; the person is offboarded."""
    from brain.models import Chat
    from knowledge.index import delete_source
    from organizations.models import OrgMembership
    from rooms.models import RoomMessage
    from timetracking.models import TimeEntry

    from rooms.models import MessageTranslation

    messages = list(RoomMessage.objects.filter(room__org=org, author=user, deleted_at__isnull=True).values_list("id", flat=True))
    now = timezone.now()
    RoomMessage.objects.filter(pk__in=messages).update(body="", deleted_at=now, updated_at=now)
    MessageTranslation.objects.filter(message_id__in=messages).delete()  # cached translations hold the text too
    for message_id in messages:
        delete_source("room_message", message_id)
    times = TimeEntry.objects.filter(org=org, user=user).update(description="")
    chats = Chat.objects.filter(org=org, user=user, room__isnull=True)  # room threads are shared, keep them
    chat_count = chats.count()
    chats.delete()
    OrgMembership.objects.filter(org=org, user=user).update(employment_status=OrgMembership.STATUS_OFFBOARDING, status_changed_at=timezone.now(), status_reason="deletion request")
    return {"messages": len(messages), "time_entry_descriptions": times, "ai_conversations": chat_count}


def apply_retention(policy, now=None) -> dict:
    """Delete data older than the policy allows, with its vectors. Returns what was removed."""
    from knowledge.index import delete_source
    from meetings.models import Recording, Transcript
    from rooms.models import RoomMessage
    from timetracking.models import TimeEntry

    now = now or timezone.now()
    org, out = policy.org, {}
    if policy.messages_days:
        cutoff = now - timedelta(days=policy.messages_days)
        ids = list(RoomMessage.objects.filter(room__org=org, created_at__lt=cutoff).values_list("id", flat=True)[:50000])
        for message_id in ids:
            delete_source("room_message", message_id)
        out["messages"] = RoomMessage.objects.filter(pk__in=ids).delete()[0]
    if policy.transcripts_days:
        from meetings.models import MeetingSummary

        cutoff = now - timedelta(days=policy.transcripts_days)
        out["transcripts"] = Transcript.objects.filter(recording__org=org, created_at__lt=cutoff).delete()[0]
        out["summaries"] = MeetingSummary.objects.filter(meeting__org=org, created_at__lt=cutoff).delete()[0]  # built from them
    if policy.recordings_days:
        cutoff = now - timedelta(days=policy.recordings_days)
        out["recordings"] = Recording.objects.filter(org=org, recorded_at__lt=cutoff).delete()[0]
    if policy.time_entries_days:
        cutoff = now - timedelta(days=policy.time_entries_days)
        out["time_entries"] = TimeEntry.objects.filter(org=org, started_at__lt=cutoff, ended_at__isnull=False).delete()[0]
    policy.last_run_at, policy.last_run_summary = now, out
    policy.save(update_fields=["last_run_at", "last_run_summary"])
    return out
