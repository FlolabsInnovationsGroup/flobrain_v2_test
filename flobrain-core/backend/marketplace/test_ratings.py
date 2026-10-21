"""Ratings, reviews, version history and "Verified by FloBrain" (growth round)."""

from marketplace.models import Listing, Rating
from marketplace.tests import MarketplaceBase
from organizations.models import AuditEvent, OrgMembership
from users.jwt_utils import make_access_token
from users.models import User


class RatingTests(MarketplaceBase):
    def setUp(self):
        super().setUp()
        made = self._as("admin").post(self.base, {"kind": "buddy", "source": str(self.buddy.id)}, format="json")
        self.listing = made.json()["id"]
        self.assertEqual(self._as("owner").post(f"{self.base}/{self.listing}/approve").status_code, 200)
        self.assertEqual(self._as("bob").post(f"{self.base}/{self.listing}/install").status_code, 201)

    def _rate(self, who, stars=5, review="Great", listing=None):
        return self._as(who).post(f"{self.base}/{listing or self.listing}/ratings", {"stars": stars, "review": review}, format="json")

    def _card(self, who):
        return next(l for l in self._as(who).get(self.base).json() if l["id"] == self.listing)

    def test_only_installers_rate_once_each(self):
        self.assertEqual(self._rate("ana").status_code, 403, "not installed")
        self.assertEqual(self._rate("admin").status_code, 403, "own listing")
        first = self._rate("bob", 4, "Useful")
        self.assertEqual(first.status_code, 201, first.content)
        again = self._rate("bob", 2, "Changed my mind")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(Rating.objects.filter(user=self.users["bob"]).count(), 1)
        self.assertEqual(Rating.objects.get(user=self.users["bob"]).stars, 2)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="marketplace.rate").exists())

    def test_range_and_review_length(self):
        for bad in (0, 6, "5", True, 4.5, None):
            self.assertEqual(self._rate("bob", bad).status_code, 400, bad)
        self.assertEqual(self._rate("bob", 3, "x" * 501).status_code, 400)
        self.assertEqual(self._rate("bob", 3, "").status_code, 201, "the review is optional")

    def test_average_count_and_reviews(self):
        self.assertEqual(self._as("ana").post(f"{self.base}/{self.listing}/install").status_code, 201)
        self._rate("bob", 5, "Great")
        self._rate("ana", 4, "Good")
        card = self._card("ana")
        self.assertEqual(card["rating"], {"average": 4.5, "count": 2})
        self.assertEqual(card["my_rating"]["stars"], 4)
        self.assertIsNone(self._card("owner")["my_rating"])
        self.assertFalse(card["verified"])
        reviews = self._as("owner").get(f"{self.base}/{self.listing}/ratings").json()
        self.assertEqual((reviews["average"], reviews["count"], reviews["can_rate"]), (4.5, 2, False))
        self.assertEqual({r["review"] for r in reviews["results"]}, {"Great", "Good"})
        self.assertTrue(self._as("bob").get(f"{self.base}/{self.listing}/ratings").json()["can_rate"])
        self.assertEqual(self._as("ana").delete(f"{self.base}/{self.listing}/ratings").status_code, 204)
        self.assertEqual(self._card("ana")["rating"], {"average": 5.0, "count": 1})
        self.assertEqual(self._as("ana").delete(f"{self.base}/{self.listing}/ratings").status_code, 404)

    def test_ratings_follow_the_listing_across_versions(self):
        self._rate("bob", 5)
        self.buddy.system_prompt = "Be briefer."
        self.buddy.save()
        v2 = self._as("admin").post(f"{self.base}/{self.listing}/versions", {"changelog": "Briefer"}, format="json").json()["id"]
        self.assertEqual(self._as("owner").post(f"{self.base}/{v2}/approve").status_code, 200)
        card = next(l for l in self._as("bob").get(self.base).json() if l["id"] == v2)
        self.assertEqual(card["rating"]["count"], 1)
        self.assertEqual(self._rate("bob", 3, listing=v2).status_code, 200, "still one rating for the listing")
        history = self._as("ana").get(f"{self.base}/{v2}/versions").json()["results"]
        self.assertEqual([(h["version"], h["status"]) for h in history], [(2, "approved"), (1, "superseded")])

    def test_hidden_listings_cannot_be_rated_or_read(self):
        pending = Listing.objects.create(
            org=self.org, kind=Listing.KIND_BUDDY, source_id=self.buddy.id, title="P", snapshot={}, submitted_by=self.users["admin"]
        )
        self.assertEqual(self._as("bob").get(f"{self.base}/{pending.id}/ratings").status_code, 404)
        self.assertEqual(self._rate("bob", listing=pending.id).status_code, 404)
        self.assertEqual(self._as("bob").get(f"{self.base}/{pending.id}/versions").status_code, 404)

    def test_verified_is_platform_staff_only(self):
        url = f"{self.base}/{self.listing}/verified"
        for who in ("owner", "admin", "bob"):
            self.assertEqual(self._as(who).post(url, {"verified": True}, format="json").status_code, 403, who)
        staff = User.objects.create(email="staff@flobrain.test", is_platform_admin=True)
        client = self._as("bob")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(staff.id))}")
        self.assertEqual(client.post(url, {"verified": "yes"}, format="json").status_code, 400)
        done = client.post(url, {"verified": True}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        self.assertTrue(done.json()["verified"])
        self.assertTrue(self._card("bob")["verified"])
        self.assertEqual(client.post(url, {"verified": False}, format="json").json()["verified"], False)
        self.assertFalse(OrgMembership.objects.filter(user=staff).exists())
