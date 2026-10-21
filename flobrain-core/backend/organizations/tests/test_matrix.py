from django.contrib.auth.hashers import make_password
from django.test import TestCase

from organizations.models import OrgMembership, Organization
from organizations.permissions.engine import can
from organizations.permissions.registry import PHASE_0_TO_3_API_KEYS, PHASE0_KEYS, ROLE_DEFAULTS
from users.models import User


def _user(email: str) -> User:
    return User.objects.create(email=email, password_hash=make_password("pass-word-1"))


class PermissionMatrixTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="FloLabs", slug="flolabs")
        self.owner = _user("owner@example.com")
        self.admin = _user("admin@example.com")
        self.member = _user("member@example.com")
        self.outsider = _user("out@example.com")
        self.inactive = _user("paused@example.com")
        OrgMembership.objects.create(
            org=self.org,
            user=self.owner,
            org_role=OrgMembership.ORG_ROLE_OWNER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.admin,
            org_role=OrgMembership.ORG_ROLE_ADMIN,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.member,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.inactive,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_PAUSED,
        )

    def test_phase0_keys_allowed_and_denied_per_role(self):
        roles = {
            "owner": self.owner,
            "admin": self.admin,
            "member": self.member,
        }
        role_map = {
            "owner": OrgMembership.ORG_ROLE_OWNER,
            "admin": OrgMembership.ORG_ROLE_ADMIN,
            "member": OrgMembership.ORG_ROLE_MEMBER,
        }
        for role_name, user in roles.items():
            defaults = ROLE_DEFAULTS[role_map[role_name]]
            for key in PHASE_0_TO_3_API_KEYS:
                allowed = key in defaults
                self.assertEqual(
                    can(user, key, self.org),
                    allowed,
                    msg=f"{role_name} {key} expected {allowed}",
                )

    def test_inactive_and_outsider_denied(self):
        for key in PHASE_0_TO_3_API_KEYS:
            self.assertFalse(can(self.inactive, key, self.org))
            self.assertFalse(can(self.outsider, key, self.org))

    def test_platform_admin_bypasses(self):
        admin = _user("platform@example.com")
        admin.is_platform_admin = True
        admin.save(update_fields=["is_platform_admin"])
        for key in PHASE_0_TO_3_API_KEYS:
            self.assertTrue(can(admin, key, self.org))
