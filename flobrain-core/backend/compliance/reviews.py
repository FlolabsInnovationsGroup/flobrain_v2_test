"""Access reviews: who has access to what, and a person's decision to keep, revoke or change it.

Items: every active member (role and teams), every open permission grant, every personal write
connection (Google, Microsoft and the rest), and every custom buddy a member shared with a team or the org.

Reviewers: the lead of a team the person is in (``team_leads``), otherwise admins (anyone with
``compliance.manage``). Nobody decides on their own access.

Applying: decisions by an owner or admin are applied at once through the same code paths the rest of
FloBrain uses (grant revoke, role change, status change, connection disconnect), and each change is
audited. A lead's revoke or change waits until an owner or admin applies it (``apply_pending``).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from compliance.models import AccessReview, AccessReviewItem
from organizations.models import OrgMembership, PermissionGrant, TeamMembership
from organizations.permissions import can, is_org_owner_or_admin
from organizations.services.core import audit

MANAGE = "compliance.manage"
GRANT_DAYS = (7, 30, 90, 180)


class ReviewError(Exception):
    def __init__(self, code, details, status=400):
        super().__init__(details)
        self.code, self.details, self.status = code, details, status


def _name(user):
    return user.username or user.email


def _leads_by_member(org):
    """{member user id: [lead user ids of teams they are in]}."""
    rows = TeamMembership.objects.filter(team__org=org, team__is_active=True).values_list("team_id", "user_id", "team_role")
    leads, members = {}, {}
    for team_id, user_id, role in rows:
        members.setdefault(team_id, []).append(user_id)
        if role == TeamMembership.ROLE_LEAD:
            leads.setdefault(team_id, []).append(user_id)
    out = {}
    for team_id, users in members.items():
        for uid in users:
            out.setdefault(uid, [])
            out[uid] += [lead for lead in leads.get(team_id, []) if lead != uid and lead not in out[uid]]
    return out


def _teams_by_member(org):
    out = {}
    for user_id, name, role in TeamMembership.objects.filter(team__org=org, team__is_active=True).values_list("user_id", "team__name", "team_role"):
        out.setdefault(user_id, []).append({"name": name, "lead": role == TeamMembership.ROLE_LEAD})
    return out


def collect_items(org, now=None):
    """The access to review right now, as unsaved item dicts."""
    now = now or timezone.now()
    memberships = list(OrgMembership.objects.filter(org=org).select_related("user"))
    by_user = {m.user_id: m for m in memberships}
    teams = _teams_by_member(org)
    items = []
    for m in sorted(memberships, key=lambda m: (_name(m.user) or "").lower()):
        if m.employment_status != OrgMembership.STATUS_ACTIVE:
            continue
        items.append({
            "subject": m.user, "kind": AccessReviewItem.MEMBERSHIP, "ref_id": str(m.id),
            "label": f"{m.get_org_role_display()} in the organization",
            "details": {"org_role": m.org_role, "status": m.employment_status, "teams": teams.get(m.user_id, []),
                        "last_active": m.user.last_active.isoformat() if m.user.last_active else None},
        })
    grants = PermissionGrant.objects.filter(org=org, revoked_at__isnull=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).select_related("grantee")
    for g in grants.order_by("created_at"):
        m = by_user.get(g.grantee_id)
        items.append({
            "subject": g.grantee, "kind": AccessReviewItem.GRANT, "ref_id": str(g.id),
            "label": f"Extra permission: {g.perm_key}",
            "details": {"perm_key": g.perm_key, "scope_type": g.scope_type, "scope_id": str(g.scope_id) if g.scope_id else None,
                        "expires_at": g.expires_at.isoformat() if g.expires_at else None, "granted_at": g.created_at.isoformat(),
                        "member_status": m.employment_status if m else "not a member"},
        })
    try:
        from integrations.write.models import WriteConnection

        for conn in WriteConnection.objects.filter(org=org, owner__isnull=False).select_related("owner").order_by("created_at"):
            items.append({
                "subject": conn.owner, "kind": AccessReviewItem.INTEGRATION, "ref_id": str(conn.id),
                "label": f"Personal {conn.provider} connection",
                "details": {"provider": conn.provider, "account": conn.account_label, "scopes": list(conn.scopes or [])[:10],
                            "status": conn.status, "last_used_at": conn.last_used_at.isoformat() if conn.last_used_at else None},
            })
    except Exception:  # noqa: BLE001 - the write integrations app may be absent
        pass
    from buddies.models import Buddy

    shared = Buddy.objects.filter(org=org, created_by__isnull=False, is_builtin=False, visibility__in=[Buddy.VIS_TEAM, Buddy.VIS_ORG]).select_related("created_by", "team")
    for b in shared.order_by("name"):
        items.append({
            "subject": b.created_by, "kind": AccessReviewItem.BUDDY, "ref_id": str(b.id),
            "label": f"Shared buddy: {b.name}",
            "details": {"visibility": b.visibility, "team": b.team.name if b.team_id and b.team else None, "tools": list(b.allowed_tools or [])[:20]},
        })
    return items


def _reviewer_for(org, subject_id, mode, leads, roles):
    if mode != AccessReview.REVIEWERS_LEADS:
        return None
    if roles.get(subject_id) in (OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN):
        return None  # admins review admins
    candidates = leads.get(subject_id) or []
    return candidates[0] if candidates else None


@transaction.atomic
def create_review(org, actor, name, period="", reviewer_mode=AccessReview.REVIEWERS_LEADS, due_days=14, request=None):
    if AccessReview.objects.filter(org=org, status=AccessReview.OPEN).exists():
        raise ReviewError("conflict", "Finish or cancel the open access review first", 409)
    now = timezone.now()
    review = AccessReview.objects.create(
        org=org, name=name, period=period, reviewer_mode=reviewer_mode, status=AccessReview.OPEN,
        due_at=now + timedelta(days=due_days), created_by=actor,
    )
    leads = _leads_by_member(org)
    roles = dict(OrgMembership.objects.filter(org=org).values_list("user_id", "org_role"))
    rows = []
    for position, item in enumerate(collect_items(org, now)):
        reviewer_id = _reviewer_for(org, item["subject"].id, reviewer_mode, leads, roles)
        rows.append(AccessReviewItem(review=review, subject=item["subject"], kind=item["kind"], ref_id=item["ref_id"],
                                     label=item["label"][:200], details=item["details"], reviewer_id=reviewer_id, position=position))
    AccessReviewItem.objects.bulk_create(rows)
    audit(actor, "compliance.review.create", target=review, org=org, request=request, payload={"items": len(rows), "reviewers": reviewer_mode})
    transaction.on_commit(lambda: notify_reviewers(review, "compliance.review_assigned"))
    return review


def reviewers_for_unassigned(org):
    admins = OrgMembership.objects.filter(org=org, employment_status="active", org_role__in=["owner", "admin"]).select_related("user")
    return [m.user for m in admins if can(m.user, MANAGE, org)]


def notify_reviewers(review, kind="compliance.review_reminder"):
    from notifications.services import notify

    pending = review.items.filter(decision=AccessReviewItem.PENDING)
    assigned = set(pending.exclude(reviewer__isnull=True).values_list("reviewer_id", flat=True))
    targets = set(assigned)
    if pending.filter(reviewer__isnull=True).exists():
        targets |= {u.id for u in reviewers_for_unassigned(review.org)}
    if not targets:
        return 0
    text = f"Access review \"{review.name}\" needs your decisions" if kind == "compliance.review_assigned" else f"Reminder: access review \"{review.name}\" is waiting for you"
    return notify(review.org, list(targets), kind, {"text": text, "title": review.name, "review": str(review.id),
                                                    "due_at": review.due_at.isoformat() if review.due_at else None},
                  link=f"settings/compliance?tab=reviews&review={review.id}", push=True, push_title=text)


def remind(review, actor, request=None, force=False):
    now = timezone.now()
    if review.status != AccessReview.OPEN:
        raise ReviewError("invalid", "Only an open review sends reminders")
    if not force and review.last_reminded_at and review.last_reminded_at > now - timedelta(hours=1):
        raise ReviewError("too_many_requests", "A reminder went out less than an hour ago", 429)
    sent = notify_reviewers(review)
    review.last_reminded_at = now
    review.save(update_fields=["last_reminded_at"])
    if actor is not None:
        audit(actor, "compliance.review.remind", target=review, org=review.org, request=request, payload={"sent": sent})
    return sent


def may_decide(user, item, manager=None) -> bool:
    """``manager``: whether ``user`` has compliance.manage (pass it when checking many items)."""
    if item.subject_id == user.id:
        return False
    if manager is None:
        manager = can(user, MANAGE, item.review.org)
    if manager:
        return True
    return item.reviewer_id is not None and item.reviewer_id == user.id


def _can_apply(user, org) -> bool:
    return is_org_owner_or_admin(user, org) and can(user, MANAGE, org)


def _validate(item, decision, change_to):
    if decision not in AccessReviewItem.DECISIONS:
        raise ReviewError("invalid", "decision must be keep, revoke or change")
    if item.kind == AccessReviewItem.MEMBERSHIP and item.details.get("org_role") == OrgMembership.ORG_ROLE_OWNER and decision != AccessReviewItem.KEEP:
        raise ReviewError("invalid", "The owner's access can't be removed or changed in a review. Hand over ownership first.")
    if decision != AccessReviewItem.CHANGE:
        return {}
    change_to = change_to if isinstance(change_to, dict) else {}
    if item.kind == AccessReviewItem.MEMBERSHIP:
        role = change_to.get("org_role")
        if role not in (OrgMembership.ORG_ROLE_ADMIN, OrgMembership.ORG_ROLE_MEMBER) or role == item.details.get("org_role"):
            raise ReviewError("invalid", "Pick a different role: admin or member")
        return {"org_role": role}
    if item.kind == AccessReviewItem.GRANT:
        try:
            days = int(change_to.get("expires_in_days"))
        except (TypeError, ValueError):
            days = 0
        if days not in GRANT_DAYS:
            raise ReviewError("invalid", "Choose an end date: 7, 30, 90 or 180 days")
        return {"expires_in_days": days}
    raise ReviewError("invalid", "This access can only be kept or revoked")


def decide(item, actor, decision, change_to=None, note="", request=None):
    review = item.review
    if review.status != AccessReview.OPEN:
        raise ReviewError("invalid", "This review is closed")
    if not may_decide(actor, item):
        if item.subject_id == actor.id:
            raise ReviewError("permission_denied", "You can't review your own access", 403)
        raise ReviewError("permission_denied", "You are not a reviewer for this item", 403)
    change = _validate(item, decision, change_to)
    with transaction.atomic():
        item = AccessReviewItem.objects.select_for_update().get(pk=item.pk)
        if item.applied_at is not None and item.decision in (AccessReviewItem.REVOKE, AccessReviewItem.CHANGE):
            raise ReviewError("conflict", "This change was already applied", 409)
        item.decision, item.change_to, item.note = decision, change, str(note or "")[:500]
        item.decided_by, item.decided_at = actor, timezone.now()
        item.applied_at, item.apply_error = None, ""
        item.save()
        audit(actor, "compliance.review.decide", target=item, org=review.org, request=request,
              payload={"review": str(review.id), "kind": item.kind, "decision": decision, "subject": str(item.subject_id), "change_to": change})
        if decision == AccessReviewItem.KEEP:
            item.applied_at = timezone.now()
            item.save(update_fields=["applied_at"])
        elif _can_apply(actor, review.org):
            _apply(item, actor, request)
    item.refresh_from_db()
    return item


def apply_pending(review, actor, request=None):
    if not _can_apply(actor, review.org):
        raise ReviewError("permission_denied", "Only an owner or admin applies changes", 403)
    done = 0
    for item in review.items.filter(decision__in=[AccessReviewItem.REVOKE, AccessReviewItem.CHANGE], applied_at__isnull=True).select_related("subject"):
        if item.subject_id == actor.id:
            continue
        with transaction.atomic():
            _apply(item, actor, request)
        done += 1
    return done


def _apply(item, actor, request):
    """Make the decided change through the existing services. Records ``applied_at`` or ``apply_error``."""
    org = item.review.org
    try:
        handler = {
            AccessReviewItem.MEMBERSHIP: _apply_membership,
            AccessReviewItem.GRANT: _apply_grant,
            AccessReviewItem.INTEGRATION: _apply_integration,
            AccessReviewItem.BUDDY: _apply_buddy,
        }[item.kind]
        handler(item, actor, org, request)
    except ReviewError as exc:
        item.apply_error = exc.details[:200]
        item.save(update_fields=["apply_error"])
        return
    item.applied_at, item.apply_error = timezone.now(), ""
    item.save(update_fields=["applied_at", "apply_error"])


def _apply_membership(item, actor, org, request):
    from organizations.services.members import change_member_status

    membership = OrgMembership.objects.filter(org=org, pk=item.ref_id).select_related("user").first()
    if membership is None:
        return  # already gone: nothing left to remove
    if membership.org_role == OrgMembership.ORG_ROLE_OWNER:
        raise ReviewError("invalid", "The owner's access can't be changed here")
    if item.decision == AccessReviewItem.REVOKE:
        if membership.employment_status == OrgMembership.STATUS_ACTIVE:
            change_member_status(org, actor, membership.user, OrgMembership.STATUS_PAUSED, reason=f"Access review: {item.review.name}")
        return
    role = item.change_to.get("org_role")
    if role and role != membership.org_role:
        before = membership.org_role
        membership.org_role = role
        membership.save(update_fields=["org_role", "updated_at"])
        audit(actor, "member.role", target=membership, org=org, request=request, payload={"from": before, "to": role, "via": "access_review"})
        from organizations.services.core import sync_user_type

        sync_user_type(membership.user)


def _apply_grant(item, actor, org, request):
    grant = PermissionGrant.objects.filter(org=org, pk=item.ref_id).first()
    if grant is None or grant.revoked_at is not None:
        return
    if item.decision == AccessReviewItem.REVOKE:
        grant.revoked_at, grant.revoked_by = timezone.now(), actor
        grant.save(update_fields=["revoked_at", "revoked_by"])
        audit(actor, "perm.revoke", target=grant, org=org, request=request, payload={"perm_key": grant.perm_key, "grantee": str(grant.grantee_id), "via": "access_review"})
        return
    days = int(item.change_to.get("expires_in_days") or 0)
    new_end = timezone.now() + timedelta(days=days)
    if grant.expires_at is None or new_end < grant.expires_at:
        grant.expires_at = new_end
        grant.save(update_fields=["expires_at"])
    audit(actor, "perm.expiry", target=grant, org=org, request=request, payload={"perm_key": grant.perm_key, "grantee": str(grant.grantee_id), "expires_at": grant.expires_at.isoformat(), "via": "access_review"})


def _apply_integration(item, actor, org, request):
    from integrations.write.models import WriteConnection

    conn = WriteConnection.objects.filter(org=org, pk=item.ref_id).first()
    if conn is None:
        return
    audit(actor, "integration.write.disconnect", target=conn, org=org, request=request, payload={"provider": conn.provider, "scope": conn.scope, "via": "access_review"})
    conn.wipe()
    conn.delete()


def _apply_buddy(item, actor, org, request):
    from buddies.models import Buddy

    buddy = Buddy.objects.filter(org=org, pk=item.ref_id).first()
    if buddy is None or buddy.visibility == Buddy.VIS_PRIVATE:
        return
    before = buddy.visibility
    buddy.visibility, buddy.team, buddy.share_status, buddy.share_target = Buddy.VIS_PRIVATE, None, Buddy.SHARE_NONE, ""
    buddy.save(update_fields=["visibility", "team", "share_status", "share_target", "updated_at"])
    audit(actor, "buddy.unshare", target=buddy, org=org, request=request, payload={"from": before, "via": "access_review"})


def progress(review):
    items = list(review.items.values_list("decision", "applied_at", "apply_error"))
    total = len(items)
    decided = sum(1 for d, _, _ in items if d != AccessReviewItem.PENDING)
    waiting = sum(1 for d, applied, _ in items if d in (AccessReviewItem.REVOKE, AccessReviewItem.CHANGE) and applied is None)
    errors = sum(1 for _, _, err in items if err)
    return {"total": total, "decided": decided, "pending": total - decided, "waiting_apply": waiting, "errors": errors}


def report(review):
    rows = list(review.items.select_related("subject", "decided_by", "reviewer"))
    by_kind = {}
    for item in rows:
        bucket = by_kind.setdefault(item.kind, {"keep": 0, "revoke": 0, "change": 0, "pending": 0})
        bucket[item.decision] += 1
    changes = [
        {"subject": _name(i.subject), "kind": i.kind, "label": i.label, "decision": i.decision, "change_to": i.change_to,
         "decided_by": _name(i.decided_by) if i.decided_by else "", "decided_at": i.decided_at.isoformat() if i.decided_at else None,
         "applied_at": i.applied_at.isoformat() if i.applied_at else None, "note": i.note}
        for i in rows if i.decision in (AccessReviewItem.REVOKE, AccessReviewItem.CHANGE)
    ]
    reviewers = sorted({_name(i.decided_by) for i in rows if i.decided_by})
    return {
        "review": {"id": str(review.id), "name": review.name, "period": review.period, "status": review.status,
                   "created_at": review.created_at.isoformat(), "completed_at": review.completed_at.isoformat() if review.completed_at else None},
        "progress": progress(review), "by_kind": by_kind, "changes": changes, "reviewers": reviewers,
    }


def complete(review, actor, request=None):
    if review.status != AccessReview.OPEN:
        raise ReviewError("invalid", "This review is not open")
    p = progress(review)
    if p["pending"]:
        raise ReviewError("conflict", f"{p['pending']} items still need a decision", 409)
    if p["waiting_apply"]:
        raise ReviewError("conflict", f"{p['waiting_apply']} changes still need to be applied", 409)
    review.status, review.completed_at, review.completed_by = AccessReview.COMPLETED, timezone.now(), actor
    review.summary = report(review)
    review.save(update_fields=["status", "completed_at", "completed_by", "summary"])
    audit(actor, "compliance.review.complete", target=review, org=review.org, request=request, payload={"items": p["total"]})
    return review


def cancel(review, actor, request=None):
    if review.status != AccessReview.OPEN:
        raise ReviewError("invalid", "This review is not open")
    review.status = AccessReview.CANCELLED
    review.save(update_fields=["status"])
    audit(actor, "compliance.review.cancel", target=review, org=review.org, request=request)
    return review


def item_payload(item, viewer=None, manager=None):
    return {
        "id": str(item.id),
        "subject": {"id": str(item.subject_id), "name": _name(item.subject), "email": item.subject.email},
        "kind": item.kind, "label": item.label, "details": item.details,
        "reviewer": {"id": str(item.reviewer_id), "name": _name(item.reviewer)} if item.reviewer_id and item.reviewer else None,
        "decision": item.decision, "change_to": item.change_to, "note": item.note,
        "decided_by": _name(item.decided_by) if item.decided_by_id and item.decided_by else "",
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "applied_at": item.applied_at.isoformat() if item.applied_at else None,
        "apply_error": item.apply_error,
        "can_decide": bool(viewer and item.review.status == AccessReview.OPEN and may_decide(viewer, item, manager)),
    }


def review_payload(review):
    return {
        "id": str(review.id), "name": review.name, "period": review.period, "reviewer_mode": review.reviewer_mode,
        "status": review.status, "due_at": review.due_at.isoformat() if review.due_at else None,
        "created_at": review.created_at.isoformat(), "completed_at": review.completed_at.isoformat() if review.completed_at else None,
        "created_by": _name(review.created_by) if review.created_by_id and review.created_by else "",
        "progress": progress(review),
    }
