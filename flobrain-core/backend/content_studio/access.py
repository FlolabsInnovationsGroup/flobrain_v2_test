"""Who sees what in Content Studio (spec permission matrix).

- Members (``content.use``): their own projects and uploads; view brand kits and templates.
- Owners, admins (``content.manage``) and team leads: every project and asset in the org.
- Brand kits and templates are edited with ``content.manage``.
- Publishing and approving are separate keys (9d).
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, TeamMembership
from organizations.permissions import HasPerm, can

FLAG = "content_studio"


def gate(request, view, org_id, perm="content.use", flag=FLAG):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, flag, default=False):
        return org, Response({"error": "not_implemented", "details": f"{flag} is not enabled"}, status=501)
    return org, None


def sees_all(user, org) -> bool:
    if can(user, "content.manage", org):
        return True
    return TeamMembership.objects.filter(team__org=org, user=user, team_role=TeamMembership.ROLE_LEAD).exists()


def visible_projects(user, org):
    from content_studio.models import ContentProject

    qs = ContentProject.objects.filter(org=org)
    return qs if sees_all(user, org) else qs.filter(owner=user)


def visible_assets(user, org):
    from content_studio.models import MediaAsset

    qs = MediaAsset.objects.filter(org=org)
    if sees_all(user, org):
        return qs
    return qs.filter(Q(uploaded_by=user) | Q(projects__owner=user)).distinct()


def not_found(what="Not found"):
    return Response({"error": "not_found", "details": what}, status=404)


def invalid(details):
    return Response({"error": "invalid", "details": str(details)}, status=400)
