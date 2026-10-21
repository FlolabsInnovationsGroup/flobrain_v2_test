from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission

from organizations.models import Organization
from organizations.permissions.engine import can


def resolve_org(request, view=None):
    org = getattr(request, "org", None)
    if org is not None:
        return org
    org_id = None
    if view is not None:
        org_id = view.kwargs.get("org_id")
    if not org_id:
        org_id = request.headers.get("X-Org-Id") if hasattr(request, "headers") else None
    if not org_id:
        org_id = request.META.get("HTTP_X_ORG_ID")
    if not org_id:
        return None
    org = Organization.objects.filter(pk=org_id, is_active=True).first()
    request.org = org
    return org


class IsActiveOrgMember(BasePermission):
    def has_permission(self, request, view) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            return False
        if getattr(request.user, "is_platform_admin", False):
            return True
        org = resolve_org(request, view)
        if org is None:
            return False
        from organizations.models import OrgMembership

        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        return bool(membership and membership.is_active_member)


class HasPerm(BasePermission):
    def __init__(self, perm_key: str | None = None):
        self.perm_key = perm_key

    def __call__(self):
        # DRF instantiates permission classes; allow HasPerm("key") in permission_classes.
        clone = HasPerm(self.perm_key)
        return clone

    def has_permission(self, request, view) -> bool:
        perm = getattr(view, "required_perm", None) or self.perm_key
        if not perm:
            return True
        org = resolve_org(request, view)
        if not can(request.user, perm, org):
            raise PermissionDenied(f"Missing permission: {perm}")
        return True


def get_scoped_or_404(user, perm_key: str, obj):
    if not can(user, perm_key, obj):
        raise NotFound()
    return obj
