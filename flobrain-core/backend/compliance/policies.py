"""Security policy templates, installed into an org as Documents, published as versions, acknowledged by members.

The markdown templates live in ``compliance/policy_templates/`` (a copy of ``docs/v2/compliance/templates/``;
a test keeps the two equal). Installing a template creates a Document in the org's "Security policies" room
(every active member is added to that room so they can read it), with the placeholders filled in. Admins edit
the Document like any other, then publish it: publishing snapshots the Document text as a numbered version
with its SHA-256. Members acknowledge a version; a new version needs a new acknowledgement.
"""

from __future__ import annotations

import hashlib
import os

from django.db import transaction
from django.utils import timezone

from compliance.models import Policy, PolicyAck, PolicyVersion
from organizations.models import OrgMembership
from organizations.services.core import audit

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "policy_templates")
ROOM_NAME = "Security policies"

TEMPLATES = [
    {"key": "information-security", "title": "Information security policy", "description": "The top policy: principles, roles, risk, exceptions."},
    {"key": "access-control", "title": "Access control policy", "description": "Accounts, SSO and MFA, granting, quarterly reviews, leavers."},
    {"key": "acceptable-use", "title": "Acceptable use policy (including AI use)", "description": "Using company systems, data and AI tools responsibly."},
    {"key": "incident-response", "title": "Incident response policy", "description": "Reporting, severity, steps, notifying customers, learning."},
    {"key": "data-retention", "title": "Data retention policy", "description": "How long each kind of data is kept and how it is deleted."},
    {"key": "vendor-management", "title": "Vendor management policy", "description": "Checking vendors, AI providers, outside agents, subprocessors."},
    {"key": "business-continuity", "title": "Business continuity policy", "description": "Backups, exports, recovery targets, tests."},
]
BY_KEY = {t["key"]: t for t in TEMPLATES}


def template_text(key) -> str:
    if key not in BY_KEY:
        raise KeyError(key)
    with open(os.path.join(TEMPLATE_DIR, f"{key}.md"), encoding="utf-8") as fh:
        return fh.read()


def _retention_values(org):
    from privacy.models import RetentionPolicy

    policy = RetentionPolicy.objects.filter(org=org).first()

    def days(field):
        value = getattr(policy, field, None) if policy else None
        return str(value) if value else "(not set)"

    return days


def fill(text, org, owner_name="", now=None) -> str:
    from compliance.models import ComplianceProfile

    now = now or timezone.now()
    profile = ComplianceProfile.objects.filter(org=org).first()
    days = _retention_values(org)
    values = {
        "ORG_NAME": org.name,
        "POLICY_OWNER": owner_name or "(policy owner)",
        "EFFECTIVE_DATE": now.date().isoformat(),
        "REQUEST_DAYS": str(profile.request_age_days if profile else 14),
        "MESSAGES_DAYS": days("messages_days"),
        "RECORDINGS_DAYS": days("recordings_days"),
        "TRANSCRIPTS_DAYS": days("transcripts_days"),
        "TIME_DAYS": days("time_entries_days"),
        "CRITICAL_SERVICE": "(your main service)",
        "RTO": "(hours)",
        "RPO": "(hours)",
    }
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def policy_room(org, actor):
    """The org's "Security policies" room, created once; every active member is added so they can read it."""
    from rooms.models import Room, RoomMember

    room = Room.objects.filter(org=org, name=ROOM_NAME, kind=Room.KIND_GROUP, is_active=True).first()
    if room is None:
        room = Room.objects.create(org=org, name=ROOM_NAME, kind=Room.KIND_GROUP)
    active = OrgMembership.objects.filter(org=org, employment_status=OrgMembership.STATUS_ACTIVE).values_list("user_id", flat=True)
    have = set(RoomMember.objects.filter(room=room).values_list("user_id", flat=True))
    RoomMember.objects.bulk_create([RoomMember(room=room, user_id=uid) for uid in active if uid not in have])
    return room


@transaction.atomic
def install(org, actor, keys, publish=False, request=None):
    """Install templates as Documents. Already installed templates are kept as they are."""
    from docs_app.models import Document

    room = policy_room(org, actor)
    owner = actor.username or actor.email
    created = []
    for key in keys:
        if key not in BY_KEY or Policy.objects.filter(org=org, template=key).exists():
            continue
        meta = BY_KEY[key]
        doc = Document.objects.create(org=org, room=room, title=meta["title"], content_text=fill(template_text(key), org, owner), created_by=actor)
        policy = Policy.objects.create(org=org, template=key, title=meta["title"], document=doc, created_by=actor)
        audit(actor, "compliance.policy.install", target=policy, org=org, request=request, payload={"template": key, "document": str(doc.id)})
        if publish:
            publish_version(policy, actor, request=request, notify_members=False)
        created.append(policy)
    if publish and created:
        _notify_new_versions(org, created)
    return created


def current_version(policy):
    return policy.versions.order_by("-version").first()


def publish_version(policy, actor, request=None, notify_members=True):
    """Snapshot the Document as a new version. Same text as the current version: nothing changes."""
    text = policy.document.content_text if policy.document_id and policy.document else ""
    if not text.strip():
        return None, False
    digest = sha256(text)
    current = current_version(policy)
    if current is not None and current.sha256 == digest:
        return current, False
    version = PolicyVersion.objects.create(policy=policy, version=(current.version + 1) if current else 1, body=text, sha256=digest, published_by=actor)
    audit(actor, "compliance.policy.publish", target=policy, org=policy.org, request=request, payload={"version": version.version, "sha256": digest})
    if notify_members:
        transaction.on_commit(lambda: _notify_new_versions(policy.org, [policy]))
    return version, True


def _notify_new_versions(org, policies):
    from notifications.services import notify

    users = list(OrgMembership.objects.filter(org=org, employment_status=OrgMembership.STATUS_ACTIVE).values_list("user_id", flat=True))
    names = ", ".join(p.title for p in policies)[:200]
    notify(org, users, "compliance.policy_published", {"text": f"Please read and acknowledge: {names}", "title": names},
           link="settings/compliance?tab=mine")


def acknowledge(policy, user, version_number, request=None):
    current = current_version(policy)
    if current is None or int(version_number or 0) != current.version:
        return None, False
    ack, created = PolicyAck.objects.get_or_create(version=current, user=user)
    if created:
        audit(user, "compliance.policy.ack", target=policy, org=policy.org, request=request, payload={"version": current.version, "sha256": current.sha256})
    return ack, created


def ack_stats(policy, active_ids=None):
    current = current_version(policy)
    if active_ids is None:
        active_ids = set(OrgMembership.objects.filter(org=policy.org, employment_status="active").values_list("user_id", flat=True))
    acked = set(PolicyAck.objects.filter(version=current, user_id__in=active_ids).values_list("user_id", flat=True)) if current else set()
    return {"acknowledged": len(acked), "members": len(active_ids), "missing_ids": [str(u) for u in active_ids - acked]}


def policy_payload(policy, active_ids=None, with_body=False):
    current = current_version(policy)
    data = {
        "id": str(policy.id), "template": policy.template, "title": policy.title,
        "document_id": str(policy.document_id) if policy.document_id else None,
        "room_id": str(policy.document.room_id) if policy.document_id and policy.document else None,
        "requires_ack": policy.requires_ack,
        "version": current.version if current else None,
        "sha256": current.sha256 if current else None,
        "published_at": current.published_at.isoformat() if current else None,
        "draft_changed": bool(policy.document_id and policy.document and (current is None or sha256(policy.document.content_text) != current.sha256)),
        "stats": ack_stats(policy, active_ids),
    }
    if with_body and current:
        data["body"] = current.body
    return data


def my_policies(org, user):
    out = []
    for policy in Policy.objects.filter(org=org, requires_ack=True).select_related("document").order_by("title"):
        current = current_version(policy)
        if current is None:
            continue
        ack = PolicyAck.objects.filter(version=current, user=user).first()
        out.append({
            "id": str(policy.id), "title": policy.title, "version": current.version, "sha256": current.sha256,
            "published_at": current.published_at.isoformat(), "body": current.body,
            "acknowledged_at": ack.acknowledged_at.isoformat() if ack else None,
        })
    return out
