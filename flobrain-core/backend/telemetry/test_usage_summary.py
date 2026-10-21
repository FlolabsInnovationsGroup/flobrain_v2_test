from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, Team, TeamMembership
from telemetry.models import PriceTable, UsageEvent
from users.jwt_utils import make_access_token
from users.models import User


def _member(org, email, role=OrgMembership.ORG_ROLE_MEMBER):
    user = User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))
    OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE)
    return user


class UsageSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Sum Org", slug="sum-org")
        self.other = Organization.objects.create(name="Sum Other", slug="sum-other")
        self.owner = _member(self.org, "sum-owner@example.com", OrgMembership.ORG_ROLE_OWNER)
        self.lead = _member(self.org, "sum-lead@example.com")
        self.member = _member(self.org, "sum-member@example.com")
        self.peer = _member(self.org, "sum-peer@example.com")
        self.team = Team.objects.create(org=self.org, name="Eng")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team, user=self.member)
        PriceTable.objects.create(provider="p", model="m", input_price=Decimal("1"), output_price=Decimal("2"))
        UsageEvent.objects.create(
            org=self.org, user=self.member, provider="p", model="m", input_tokens=1_000_000, output_tokens=1_000_000,
            total_tokens=2_000_000, surface="buddy", team=self.team,
        )
        UsageEvent.objects.create(
            org=self.org, user=self.member, provider="openai", model="gpt", total_tokens=500, surface="room_ai",
            credential_source=UsageEvent.CREDENTIAL_CUSTOMER,
        )
        UsageEvent.objects.create(org=self.org, user=self.peer, provider="p", model="m", total_tokens=10, surface="room_ai")
        UsageEvent.objects.create(org=self.other, user=self.member, provider="p", model="m", total_tokens=999)
        self.url = f"/api/v2/orgs/{self.org.id}/usage/summary"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_owner_sees_org_per_member_with_platform_and_own_key_apart(self):
        self._auth(self.owner)
        body = self.client.get(self.url, {"group": "member"}).json()
        self.assertEqual(body["scope"], "org")
        rows = {r["label"]: r for r in body["results"]}
        me = rows["sum-member"]
        self.assertEqual(me["platform_cost"], "3.0000")
        self.assertEqual(me["own_key_tokens"], 500)
        self.assertEqual(me["platform_tokens"], 2_000_000)
        self.assertIn("sum-peer", rows)
        self.assertEqual(body["totals"]["calls"], 3, "the other org is not counted")
        self.assertEqual(rows["sum-peer"]["unpriced_calls"], 0)

    def test_groups(self):
        self._auth(self.owner)
        by_surface = {r["key"]: r for r in self.client.get(self.url, {"group": "surface"}).json()["results"]}
        self.assertEqual(set(by_surface), {"buddy", "room_ai"})
        by_team = {r["label"]: r for r in self.client.get(self.url, {"group": "team"}).json()["results"]}
        self.assertEqual(by_team["Eng"]["calls"], 1)
        by_model = {r["label"] for r in self.client.get(self.url, {"group": "model"}).json()["results"]}
        self.assertEqual(by_model, {"m", "gpt"})
        self.assertEqual(self.client.get(self.url, {"group": "planet"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"days": "abc"}).status_code, 200)

    def test_lead_sees_team_members_member_sees_self(self):
        self._auth(self.lead)
        body = self.client.get(self.url).json()
        self.assertEqual(body["scope"], "teams")
        self.assertEqual({r["label"] for r in body["results"]}, {"Your team members (combined)"}, "never per person for leads")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/usage/export").status_code, 403)
        self._auth(self.peer)
        body = self.client.get(self.url).json()
        self.assertEqual(body["scope"], "own")
        self.assertEqual({r["label"] for r in body["results"]}, {"sum-peer"})

    def test_export_csv_is_scoped_and_formula_safe(self):
        UsageEvent.objects.create(org=self.org, user=self.peer, provider="p", model="=HYPERLINK(1)", total_tokens=1)
        self._auth(self.peer)
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/usage/export")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Type"].startswith("text/csv"))
        text = res.content.decode()
        self.assertIn("sum-peer", text)
        self.assertNotIn("sum-member", text)
        self.assertIn("'=HYPERLINK(1)", text)
        self._auth(self.owner)
        text = self.client.get(f"/api/v2/orgs/{self.org.id}/usage/export").content.decode()
        self.assertIn("own key", text)
        self.assertIn("3.000000", text)

    def test_people_who_keep_insights_personal_have_no_row(self):
        from privacy.models import PrivacySettings

        PrivacySettings.objects.create(org=self.org, user=self.peer, analytics_personal_only=True)
        self._auth(self.owner)
        labels = {r["label"] for r in self.client.get(self.url, {"group": "member"}).json()["results"]}
        self.assertNotIn("sum-peer", labels)
        self.assertIn("People who keep their insights personal", labels)
        text = self.client.get(f"/api/v2/orgs/{self.org.id}/usage/export").content.decode()
        self.assertNotIn("sum-peer", text)
        self._auth(self.peer)
        self.assertEqual({r["label"] for r in self.client.get(self.url).json()["results"]}, {"sum-peer"}, "you still see yourself")

    def test_outsider_is_403(self):
        outsider = _member(self.other, "sum-out@example.com", OrgMembership.ORG_ROLE_OWNER)
        self._auth(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/usage/export").status_code, 403)

    def test_writer_records_surface_and_room_team(self):
        from brain.llm.providers import ProviderResult
        from brain.models import Chat
        from rooms.services import ensure_team_room
        from telemetry.writers import record_v2_provider_event

        room = ensure_team_room(self.team)
        chat = Chat.objects.create(user=self.member, org=self.org, room=room, title="t")
        record_v2_provider_event(self.member, ProviderResult(text="ok", model="m", total_tokens=3), surface="room_ai", org=self.org, chat=chat)
        row = UsageEvent.objects.filter(chat=chat).get()
        self.assertEqual(row.surface, "room_ai")
        self.assertEqual(row.team_id, self.team.id)
