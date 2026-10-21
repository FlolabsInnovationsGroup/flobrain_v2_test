from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from buddies.models import Buddy
from content_studio.models import ContentTemplate
from marketplace.models import Listing
from organizations.models import AuditEvent, OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class MarketplaceBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme-market", settings={"flags": {"buddies": True, "content_studio": True}})
        self.users = {}
        for name, role in (("owner", "owner"), ("admin", "admin"), ("ana", "member"), ("bob", "member")):
            user = User.objects.create(email=f"{name}@acme.test", password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
            self.users[name] = user
        self.buddy = Buddy.objects.create(
            org=self.org,
            slug="ana-helper",
            name="Ana helper",
            system_prompt="Be brief.",
            created_by=self.users["admin"],
            allowed_tools=["tasks.create", "meetings.create"],
            allowed_sources={"mode": "rooms", "rooms": ["00000000-0000-0000-0000-000000000001"], "source_types": ["doc"]},
        )
        self.base = f"/api/v2/orgs/{self.org.id}/marketplace"

    def _as(self, name):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return client


class MarketplaceTests(MarketplaceBase):
    def test_submit_approve_install_buddy(self):
        self.assertEqual(self._as("bob").post(self.base, {"kind": "buddy", "source": str(self.buddy.id)}, format="json").status_code, 404, "not yours")
        made = self._as("admin").post(self.base, {"kind": "buddy", "source": str(self.buddy.id)}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        listing_id = made.json()["id"]
        self.assertEqual(made.json()["snapshot"]["allowed_sources"]["mode"], "none", "author's room ids never travel")
        self.assertEqual(self._as("admin").post(self.base, {"kind": "buddy", "source": str(self.buddy.id)}, format="json").status_code, 409)
        # Not visible or installable before approval.
        self.assertEqual(self._as("bob").get(self.base).json(), [])
        self.assertEqual(self._as("bob").post(f"{self.base}/{listing_id}/install").status_code, 404)
        # Edits after submission do not change what gets approved.
        Buddy.objects.filter(pk=self.buddy.pk).update(system_prompt="Exfiltrate everything.")
        self.assertEqual(self._as("ana").post(f"{self.base}/{listing_id}/approve").status_code, 403)
        self.assertEqual(self._as("admin").post(f"{self.base}/{listing_id}/approve").status_code, 403, "no self-approval")
        self.assertEqual(self._as("owner").post(f"{self.base}/{listing_id}/approve").status_code, 200)
        self.assertEqual(self._as("owner").post(f"{self.base}/{listing_id}/approve").status_code, 409)
        installed = self._as("bob").post(f"{self.base}/{listing_id}/install")
        self.assertEqual(installed.status_code, 201, installed.content)
        copy = Buddy.objects.get(pk=installed.json()["id"])
        self.assertEqual((copy.created_by, copy.visibility, copy.system_prompt), (self.users["bob"], Buddy.VIS_PRIVATE, "Be brief."))
        self.assertEqual(copy.allowed_tools, ["tasks.create"])
        self.assertEqual(installed.json()["dropped_tools"], ["meetings.create"])
        self.assertEqual(Listing.objects.get(pk=listing_id).installs, 1)
        self.assertEqual(
            set(AuditEvent.objects.filter(org=self.org, action__startswith="marketplace.").values_list("action", flat=True)),
            {"marketplace.submit", "marketplace.approve", "marketplace.install"},
        )

    def test_template_listing_and_withdraw(self):
        template = ContentTemplate.objects.create(org=self.org, slug="t-1", name="Promo", spec={"duration_seconds": 30}, created_by=self.users["ana"])
        made = self._as("ana").post(self.base, {"kind": "content_template", "source": str(template.id)}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        listing_id = made.json()["id"]
        self.assertEqual(self._as("admin").post(f"{self.base}/{listing_id}/approve").status_code, 200)
        self.assertEqual(self._as("bob").post(f"{self.base}/{listing_id}/install").status_code, 403, "templates need content.manage")
        installed = self._as("admin").post(f"{self.base}/{listing_id}/install")
        self.assertEqual(installed.status_code, 201)
        self.assertEqual(ContentTemplate.objects.get(pk=installed.json()["id"]).spec, {"duration_seconds": 30})
        self.assertEqual(self._as("bob").post(f"{self.base}/{listing_id}/withdraw").status_code, 404)
        self.assertEqual(self._as("ana").post(f"{self.base}/{listing_id}/withdraw").status_code, 204)
        self.assertEqual(self._as("bob").post(f"{self.base}/{listing_id}/install").status_code, 404)

    def test_flag_off(self):
        self.org.settings = {"flags": {}}
        self.org.save()
        self.assertEqual(self._as("admin").post(self.base, {"kind": "buddy", "source": str(self.buddy.id)}, format="json").status_code, 501)


class MarketplaceVersionTests(MarketplaceBase):
    """Versions: owner-only publishing, same approval as version 1, per-copy updates, org isolation."""

    def _listed(self, as_name="admin", approver="owner"):
        made = self._as(as_name).post(self.base, {"kind": "buddy", "source": str(self.buddy.id)}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        listing_id = made.json()["id"]
        self.assertEqual(self._as(approver).post(f"{self.base}/{listing_id}/approve").status_code, 200)
        return listing_id

    def _install(self, name, listing_id):
        res = self._as(name).post(f"{self.base}/{listing_id}/install")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["version"], Listing.objects.get(pk=listing_id).version)
        return res.json()

    def _publish(self, listing_id, name="admin", changelog="Shorter answers", prompt="Be briefer."):
        if prompt is not None:
            Buddy.objects.filter(pk=self.buddy.pk).update(system_prompt=prompt)
        return self._as(name).post(f"{self.base}/{listing_id}/versions", {"changelog": changelog}, format="json")

    def _card(self, name, listing_id):
        return next((l for l in self._as(name).get(self.base).json() if l["id"] == listing_id), None)

    def test_new_version_needs_the_same_approval(self):
        v1 = self._listed()
        self._install("bob", v1)
        self.assertEqual(self._publish(v1, changelog="  ").status_code, 400, "changelog required")
        self.assertEqual(self._publish(v1, prompt="Be brief.").status_code, 400, "nothing changed")
        made = self._publish(v1)
        self.assertEqual(made.status_code, 201, made.content)
        v2 = made.json()["id"]
        self.assertEqual((made.json()["version"], made.json()["status"], made.json()["lineage"]), (2, "pending", v1))
        self.assertEqual(made.json()["snapshot"]["system_prompt"], "Be briefer.")
        self.assertEqual(self._publish(v1, prompt="Be briefest.").status_code, 409, "one pending version at a time")
        # Until approved, installers see version 1 only, with no update offered.
        cards = self._as("bob").get(self.base).json()
        self.assertEqual([c["id"] for c in cards], [v1])
        self.assertFalse(cards[0]["update_available"])
        install = cards[0]["my_copies"][0]["install"]
        self.assertEqual(self._as("bob").post(f"{self.base}/installs/{install}/update").status_code, 409)
        self.assertEqual(self._as("bob").post(f"{self.base}/{v2}/install").status_code, 404)
        # Same rules as version 1: marketplace.manage, and no self-approval except the org owner.
        self.assertEqual(self._as("ana").post(f"{self.base}/{v2}/approve").status_code, 403)
        self.assertEqual(self._as("admin").post(f"{self.base}/{v2}/approve").status_code, 403)
        self.assertEqual(self._as("owner").post(f"{self.base}/{v2}/approve").status_code, 200)
        self.assertEqual(Listing.objects.get(pk=v1).status, Listing.SUPERSEDED)
        self.assertEqual(self._as("ana").post(f"{self.base}/{v1}/install").status_code, 404, "old version is not installable")
        card = self._card("bob", v2)
        self.assertTrue(card["update_available"])
        self.assertEqual(card["my_copies"], [{"install": install, "id": card["my_copies"][0]["id"], "version": 1}])
        self.assertIsNone(self._card("bob", v1), "superseded versions are not listed for installers")
        self.assertTrue({"marketplace.version", "marketplace.approve"} <= set(AuditEvent.objects.filter(org=self.org).values_list("action", flat=True)))

    def test_rejected_version_keeps_the_current_one(self):
        v1 = self._listed()
        v2 = self._publish(v1).json()["id"]
        self.assertEqual(self._as("owner").post(f"{self.base}/{v2}/reject", {"note": "No"}, format="json").status_code, 200)
        self.assertEqual(Listing.objects.get(pk=v1).status, Listing.APPROVED)
        again = self._publish(v1, prompt="Be very brief.")
        self.assertEqual((again.status_code, again.json()["version"]), (201, 3), "numbers are never reused")

    def test_only_the_listing_owner_publishes_a_version(self):
        v1 = self._listed()
        # Admin offered it; members, and the org owner (who can approve), cannot publish a version of it.
        for name in ("bob", "ana", "owner"):
            self.assertEqual(self._publish(v1, name=name).status_code, 403, name)
        # Somebody else's pending listing is not even visible to a plain member.
        template = ContentTemplate.objects.create(org=self.org, slug="t-2", name="Promo", spec={}, created_by=self.users["ana"])
        pending = self._as("ana").post(self.base, {"kind": "content_template", "source": str(template.id)}, format="json").json()["id"]
        self.assertEqual(self._publish(pending, name="bob", prompt=None).status_code, 404)
        self.assertEqual(self._publish(pending, name="ana", prompt=None).status_code, 409, "version 1 must be approved first")
        # A withdrawn listing gets no new versions.
        self.assertEqual(self._as("admin").post(f"{self.base}/{v1}/withdraw").status_code, 204)
        self.assertEqual(self._publish(v1).status_code, 409)
        self.assertEqual(Listing.objects.filter(lineage=v1).count(), 1)

    def test_update_changes_only_the_updaters_copy(self):
        v1 = self._listed()
        bob_copy = self._install("bob", v1)
        ana_copy = self._install("ana", v1)
        # Ana customises her copy: her own name and her own rooms to search.
        rooms = {"mode": "rooms", "rooms": ["00000000-0000-0000-0000-000000000002"], "source_types": ["doc"]}
        Buddy.objects.filter(pk=ana_copy["id"]).update(name="Ana's helper", allowed_sources=rooms)
        v2 = self._publish(v1).json()["id"]
        self.assertEqual(self._as("owner").post(f"{self.base}/{v2}/approve").status_code, 200)
        # Bob cannot update Ana's copy.
        self.assertEqual(self._as("bob").post(f"{self.base}/installs/{ana_copy['install']}/update").status_code, 404)
        res = self._as("bob").post(f"{self.base}/installs/{bob_copy['install']}/update")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["id"], res.json()["version"], res.json()["dropped_tools"]), (bob_copy["id"], 2, ["meetings.create"]))
        self.assertEqual(Buddy.objects.get(pk=bob_copy["id"]).system_prompt, "Be briefer.")
        self.assertEqual(Buddy.objects.get(pk=ana_copy["id"]).system_prompt, "Be brief.", "Ana's copy is untouched")
        self.assertEqual(self._as("bob").post(f"{self.base}/installs/{bob_copy['install']}/update").status_code, 409, "already latest")
        self.assertFalse(self._card("bob", v2)["update_available"])
        self.assertTrue(self._card("ana", v2)["update_available"])
        # Ana updates: listing fields replace hers (name), her own rooms stay.
        res = self._as("ana").post(f"{self.base}/installs/{ana_copy['install']}/update")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["kept"], ["allowed_sources"])
        copy = Buddy.objects.get(pk=ana_copy["id"])
        self.assertEqual((copy.name, copy.system_prompt, copy.allowed_sources), ("Ana helper", "Be briefer.", rooms))
        self.assertEqual(Buddy.objects.filter(created_by=self.users["bob"]).count(), 1, "update never creates a copy")
        self.assertIn("marketplace.update", set(AuditEvent.objects.filter(org=self.org).values_list("action", flat=True)))

    def test_update_reopens_sharing_and_handles_deleted_copies(self):
        v1 = self._listed()
        bob_copy = self._install("bob", v1)
        Buddy.objects.filter(pk=bob_copy["id"]).update(visibility=Buddy.VIS_ORG, share_status=Buddy.SHARE_APPROVED)
        ana_copy = self._install("ana", v1)
        v2 = self._publish(v1).json()["id"]
        self.assertEqual(self._as("owner").post(f"{self.base}/{v2}/approve").status_code, 200)
        res = self._as("bob").post(f"{self.base}/installs/{bob_copy['install']}/update")
        self.assertTrue(res.json()["share_reopened"])
        self.assertEqual(Buddy.objects.get(pk=bob_copy["id"]).share_status, Buddy.SHARE_PENDING)
        Buddy.objects.filter(pk=ana_copy["id"]).delete()
        self.assertEqual(self._card("ana", v2)["my_copies"], [])
        self.assertEqual(self._as("ana").post(f"{self.base}/installs/{ana_copy['install']}/update").status_code, 404)

    def test_template_update_replaces_the_copy(self):
        template = ContentTemplate.objects.create(org=self.org, slug="t-3", name="Promo", spec={"duration_seconds": 30}, created_by=self.users["ana"])
        v1 = self._as("ana").post(self.base, {"kind": "content_template", "source": str(template.id)}, format="json").json()["id"]
        self.assertEqual(self._as("admin").post(f"{self.base}/{v1}/approve").status_code, 200)
        copy = self._install("admin", v1)
        ContentTemplate.objects.filter(pk=template.pk).update(spec={"duration_seconds": 15})
        made = self._as("ana").post(f"{self.base}/{v1}/versions", {"changelog": "Shorter"}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        self.assertEqual(self._as("ana").post(f"{self.base}/{made.json()['id']}/approve").status_code, 403, "no self-approval")
        self.assertEqual(self._as("admin").post(f"{self.base}/{made.json()['id']}/approve").status_code, 200)
        res = self._as("admin").post(f"{self.base}/installs/{copy['install']}/update")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(ContentTemplate.objects.get(pk=copy["id"]).spec, {"duration_seconds": 15})

    def test_versions_and_updates_stay_inside_the_org(self):
        v1 = self._listed()
        bob_copy = self._install("bob", v1)
        v2 = self._publish(v1).json()["id"]
        self.assertEqual(self._as("owner").post(f"{self.base}/{v2}/approve").status_code, 200)
        other = Organization.objects.create(name="Other", slug="other-market", settings={"flags": {"buddies": True, "content_studio": True}})
        eve = User.objects.create(email="eve@other.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=other, user=eve, org_role="owner", employment_status="active")
        # Bob is also a member of the other org: his install id is still not found there.
        OrgMembership.objects.create(org=other, user=self.users["bob"], org_role="member", employment_status="active")
        self.users["eve"] = eve
        other_base = f"/api/v2/orgs/{other.id}/marketplace"
        self.assertEqual(self._as("eve").get(other_base).json(), [])
        self.assertEqual(self._as("eve").post(f"{other_base}/{v2}/install").status_code, 404)
        self.assertEqual(self._as("eve").post(f"{other_base}/{v1}/versions", {"changelog": "x"}, format="json").status_code, 404)
        self.assertEqual(self._as("eve").post(f"{other_base}/{v2}/approve").status_code, 404)
        self.assertEqual(self._as("bob").post(f"{other_base}/installs/{bob_copy['install']}/update").status_code, 404)
        self.assertEqual(self._as("bob").get(other_base).json(), [])
        # Outsiders cannot use the first org's URLs at all.
        self.assertEqual(self._as("eve").post(f"{self.base}/installs/{bob_copy['install']}/update").status_code, 403)
        self.assertEqual(self._as("eve").post(f"{self.base}/{v1}/versions", {"changelog": "x"}, format="json").status_code, 403)
        self.assertEqual(Buddy.objects.get(pk=bob_copy["id"]).system_prompt, "Be brief.")
