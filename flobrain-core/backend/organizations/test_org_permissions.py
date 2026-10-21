from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone

from organizations.models import OrgMembership, Organization, PermissionGrant, Team, TeamMembership
from organizations.permissions.engine import can, org_permissions
from organizations.permissions.registry import PERMISSION_CATALOG
from users.models import User


class OrgPermissionsTests(TestCase):
    def test_org_permissions_matches_can(self):
        org = Organization.objects.create(name="P", slug="perm-org")
        team = Team.objects.create(org=org, name="T")
        people = {}
        for name, role, status in (("owner", "owner", "active"), ("admin", "admin", "active"), ("member", "member", "active"), ("lead", "member", "active"), ("granted", "member", "active"), ("paused", "admin", "paused")):
            u = User.objects.create(email=f"{name}@p.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=org, user=u, org_role=role, employment_status=status)
            people[name] = u
        TeamMembership.objects.create(team=team, user=people["lead"], team_role="lead")
        PermissionGrant.objects.create(org=org, grantee=people["granted"], perm_key="audit.view", scope_type=PermissionGrant.SCOPE_ORG, granted_by=people["owner"])
        PermissionGrant.objects.create(org=org, grantee=people["granted"], perm_key="hr.view", scope_type=PermissionGrant.SCOPE_ORG, granted_by=people["owner"], expires_at=timezone.now() - timedelta(days=1))
        PermissionGrant.objects.create(org=org, grantee=people["granted"], perm_key="exports.memory", scope_type=PermissionGrant.SCOPE_ORG, granted_by=people["owner"])
        people["staff"] = User.objects.create(email="s@p.test", username="s", password_hash=make_password("x"), is_platform_admin=True)
        people["outsider"] = User.objects.create(email="o@p.test", username="o", password_hash=make_password("x"))
        for name, user in people.items():
            expected = {k for k in PERMISSION_CATALOG if can(user, k, org)}
            self.assertEqual(org_permissions(user, org), expected, name)
