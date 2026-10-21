"""One way to notify people (2026-10-21). Use this instead of creating Notification rows by hand.

``notify(org, users, kind, payload, link=None, push=False)`` creates one in-app notification per
active member of ``org`` among ``users`` (User rows or ids), skips people who switched that type
off (``NotificationPreference.enabled=False``), and optionally sends a Web Push with only the
title and link (never message text). ``payload`` should carry what the screen needs to word it
(``text`` as an English fallback, plus fields like ``title``, ``by``); ``link`` is a path inside
the workspace such as ``tasks`` or ``rooms/<id>``.
"""

from django.db import transaction


# The settings page stores switches under these names; a kind not listed uses its own name with
# dots turned into underscores (``meeting.summary_ready`` -> ``meeting_summary_ready``).
PREF_TYPES = {
    "task.assigned": "task_assigned",
    "task.due_soon": "task_deadline_reached",
    "task.overdue": "task_deadline_reached",
    "impersonation.started": "impersonation_started",
}


def pref_type(kind: str) -> str:
    return PREF_TYPES.get(kind, kind.replace(".", "_"))


def notify(org, users, kind: str, payload: dict | None = None, link: str | None = None, push: bool = False, push_title: str = "") -> int:
    from notifications.models import Notification, NotificationPreference
    from organizations.models import OrgMembership

    ids = {getattr(u, "id", u) for u in users if u is not None}
    if not ids:
        return 0
    active = set(OrgMembership.objects.filter(org=org, user_id__in=ids, employment_status="active").values_list("user_id", flat=True))
    prefs = NotificationPreference.objects.filter(user_id__in=active, type__in={kind, pref_type(kind)})
    muted = {p.user_id for p in prefs if not p.enabled}
    no_push = {p.user_id for p in prefs if not p.push}
    targets = sorted(active - muted, key=str)
    data = dict(payload or {})
    if link:
        data["link"] = link
    Notification.objects.bulk_create([Notification(org=org, user_id=uid, kind=kind, payload=data) for uid in targets])
    push_targets = [uid for uid in targets if uid not in no_push]
    if push and push_targets:
        from jobs.queue import enqueue

        url = f"/w/{org.slug}/{link}" if link else f"/w/{org.slug}"
        title = (push_title or data.get("text") or kind)[:120]
        transaction.on_commit(lambda: enqueue("notifications.push", {"users": [str(u) for u in push_targets], "title": title, "url": url, "kind": kind}))
    return len(targets)
