from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from organizations.flags import client_ip
from organizations.models import (
    AuditEvent,
    OrgMembership,
    PermissionGrant,
    PermissionRequest,
    Project,
    TeamMembership,
)


def sync_user_type(user) -> str:
    """E9: derive user_type from memberships and persist if it changed."""
    memberships = list(
        OrgMembership.objects.filter(user=user, employment_status=OrgMembership.STATUS_ACTIVE)
    )
    next_type = "personal"
    if any(m.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN} for m in memberships):
        next_type = "company_adm"
    elif TeamMembership.objects.filter(user=user, team_role=TeamMembership.ROLE_LEAD).exists() or Project.objects.filter(
        lead=user
    ).exists():
        next_type = "company_lead"
    elif memberships:
        next_type = "company_member"
    if user.user_type != next_type:
        user.user_type = next_type
        user.save(update_fields=["user_type"])
    return next_type


def audit(actor, action: str, target=None, payload=None, request=None, org=None, impersonator=None):
    if org is None:
        org = getattr(request, "org", None) if request is not None else None
        if org is None and target is not None:
            org = getattr(target, "org", None)
    if org is None:
        raise ValueError("audit() requires an org")
    target_type = ""
    target_id = ""
    if target is not None:
        target_type = target.__class__.__name__
        target_id = str(getattr(target, "id", "") or "")
    ip = None
    user_agent = ""
    if request is not None:
        ip = client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
    return AuditEvent.objects.create(
        org=org,
        actor=actor,
        impersonator=impersonator,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
        ip=ip,
        user_agent=user_agent,
    )


def grant_permission(org, actor, grantee, perm_key: str, *, scope_type="org", scope_id=None, days=None, request=None, expires_at=None):
    if expires_at is None:
        expires_at = timezone.now() + timedelta(days=days) if days else None
    grant = PermissionGrant.objects.create(
        org=org,
        grantee=grantee,
        perm_key=perm_key,
        scope_type=scope_type,
        scope_id=scope_id,
        granted_by=actor,
        expires_at=expires_at,
    )
    audit(
        actor,
        "perm.grant",
        target=grant,
        payload={
            "perm_key": perm_key,
            "grantee": str(grantee.id),
            "scope_type": scope_type,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
        request=request,
        org=org,
    )
    return grant


def decide_request(req: PermissionRequest, actor, approve: bool, request=None, days=None):
    req.status = PermissionRequest.STATUS_APPROVED if approve else PermissionRequest.STATUS_REJECTED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "decided_by", "decided_at"])
    if approve:
        grant_permission(
            req.org,
            actor,
            req.requester,
            req.perm_key,
            scope_type=req.scope_type,
            scope_id=req.scope_id,
            request=request,
            days=days,
        )
    audit(
        actor,
        "perm.request.approve" if approve else "perm.request.reject",
        target=req,
        payload={"perm_key": req.perm_key},
        request=request,
        org=req.org,
    )
    return req
