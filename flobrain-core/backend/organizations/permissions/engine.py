from __future__ import annotations

from typing import Optional

from django.utils import timezone

from organizations.models import (
    OrgMembership,
    Organization,
    PermissionGrant,
    Project,
    ProjectMembership,
    Team,
    TeamMembership,
)
from organizations.permissions.registry import PERMISSION_CATALOG, ROLE_DEFAULTS


def _active_membership(user, org) -> Optional[OrgMembership]:
    if user is None or org is None:
        return None
    return (
        OrgMembership.objects.filter(org=org, user=user)
        .select_related("org", "user")
        .first()
    )


def can(user, perm_key: str, obj=None) -> bool:
    """org role → team/project scope → active grants. Inactive membership → False."""
    if user is None or not perm_key:
        return False
    if perm_key not in PERMISSION_CATALOG:
        return False
    if getattr(user, "is_platform_admin", False):
        return True

    org = None
    team = None
    project = None
    if obj is None:
        return False
    if isinstance(obj, Organization):
        org = obj
    elif isinstance(obj, Team):
        team = obj
        org = obj.org
    elif isinstance(obj, Project):
        project = obj
        org = obj.org
    elif isinstance(obj, dict):
        org = obj.get("org")
        team = obj.get("team")
        project = obj.get("project")
    else:
        org = getattr(obj, "org", obj)
        team = getattr(obj, "team", None)
        project = getattr(obj, "project", None)

    membership = _active_membership(user, org)
    if membership is None or not membership.is_active_member:
        return False

    if perm_key in ROLE_DEFAULTS.get(membership.org_role, frozenset()):
        matrix = PERMISSION_CATALOG.get(perm_key, {}).get("matrix", "org")
        if matrix == "org":
            return True
        if matrix == "team":
            if membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}:
                return True
            if team is None:
                return True
            return TeamMembership.objects.filter(team=team, user=user).exists()
        if matrix == "project":
            if membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}:
                return True
            if project is None:
                return True
            if ProjectMembership.objects.filter(project=project, user=user).exists():
                return True
            if team is not None and TeamMembership.objects.filter(team=team, user=user).exists():
                return True
            return False

    now = timezone.now()
    grants = PermissionGrant.objects.filter(
        org=org,
        grantee=user,
        perm_key=perm_key,
        revoked_at__isnull=True,
    )
    for grant in grants:
        if grant.expires_at and grant.expires_at <= now:
            continue
        if grant.scope_type == PermissionGrant.SCOPE_ORG:
            return True
        if grant.scope_type == PermissionGrant.SCOPE_TEAM and team is not None:
            if str(grant.scope_id) == str(team.id):
                return True
        if grant.scope_type == PermissionGrant.SCOPE_PROJECT and project is not None:
            if str(grant.scope_id) == str(project.id):
                return True

    if perm_key == "mission.view":
        lead_qs = TeamMembership.objects.filter(user=user, team__org=org, team_role=TeamMembership.ROLE_LEAD)
        if team is not None:
            return lead_qs.filter(team=team).exists()
        return lead_qs.exists()

    if team is not None and TeamMembership.objects.filter(team=team, user=user).exists():
        if perm_key in {"team.view", "project.view", "task.view", "task.write", "time.view", "time.write"}:
            return True
    if project is not None and ProjectMembership.objects.filter(project=project, user=user).exists():
        if perm_key in {"project.view", "task.view", "task.write", "time.view", "time.write"}:
            return True
    return False


def is_org_owner_or_admin(user, org) -> bool:
    if getattr(user, "is_platform_admin", False):
        return True
    membership = _active_membership(user, org)
    return bool(
        membership
        and membership.is_active_member
        and membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}
    )


def visible_team_ids(user, org):
    """None means every team in the org (owner/admin/platform)."""
    if is_org_owner_or_admin(user, org):
        return None
    return list(
        TeamMembership.objects.filter(user=user, team__org=org).values_list("team_id", flat=True)
    )
