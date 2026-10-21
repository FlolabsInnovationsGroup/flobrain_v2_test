from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from organizations.models import OrgMembership, Organization
from users.models import User


class CreateOrgCommandTests(TestCase):
    def test_creates_org_and_owner_with_temporary_password(self):
        out = StringIO()
        call_command("create_org", "--name", "FloLabs", "--slug", "flolabs", "--owner-email", "Boss@Example.com", "--all-features", stdout=out)
        org = Organization.objects.get(slug="flolabs")
        user = User.objects.get(email="boss@example.com")
        self.assertTrue(user.must_change_password)
        self.assertEqual(OrgMembership.objects.get(org=org, user=user).org_role, "owner")
        self.assertTrue(org.settings["flags"]["buddies"])
        temp = out.getvalue().split("first sign-in): ")[1].strip()
        from django.contrib.auth.hashers import check_password

        self.assertTrue(check_password(temp, user.password_hash))
        self.assertFalse(user.is_platform_admin)

    def test_refuses_bad_or_taken_slugs_and_reuses_accounts(self):
        with self.assertRaises(CommandError):
            call_command("create_org", "--name", "X", "--slug", "demo", "--owner-email", "a@b.co", stdout=StringIO())
        User.objects.create(email="old@example.com", username="old")
        out = StringIO()
        call_command("create_org", "--name", "Acme", "--slug", "acme", "--owner-email", "old@example.com", "--platform-admin", stdout=out)
        self.assertIn("already had an account", out.getvalue())
        self.assertTrue(User.objects.get(email="old@example.com").is_platform_admin)
        self.assertEqual(Organization.objects.get(slug="acme").settings, {})
        with self.assertRaises(CommandError):
            call_command("create_org", "--name", "Acme 2", "--slug", "acme", "--owner-email", "x@example.com", stdout=StringIO())
