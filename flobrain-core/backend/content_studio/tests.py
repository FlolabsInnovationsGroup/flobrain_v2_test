from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from content_studio.models import ContentProject, ContentTemplate, MediaAsset
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from users.jwt_utils import make_access_token
from users.models import User


def _user(email):
    return User.objects.create(email=email, password_hash=make_password("x"))


@override_settings(CONTENT_STORAGE="local")
class StudioBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="CS", slug="cs-org", settings={"flags": {"content_studio": True}})
        self.other_org = Organization.objects.create(name="CS2", slug="cs-org2", settings={"flags": {"content_studio": True}})
        self.owner = _user("cs-owner@example.com")
        self.lead = _user("cs-lead@example.com")
        self.m1 = _user("cs-m1@example.com")
        self.m2 = _user("cs-m2@example.com")
        self.outsider = _user("cs-out@example.com")
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.lead, OrgMembership.ORG_ROLE_MEMBER),
            (self.m1, OrgMembership.ORG_ROLE_MEMBER),
            (self.m2, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE)
        OrgMembership.objects.create(
            org=self.other_org, user=self.outsider, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        team = Team.objects.create(org=self.org, name="Media")
        TeamMembership.objects.create(team=team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        self.base = f"/api/v2/orgs/{self.org.id}/content"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _ready_asset(self, user, kind="video", content_type="video/mp4"):
        self._auth(user)
        made = self.client.post(
            f"{self.base}/assets", {"kind": kind, "content_type": content_type, "size_bytes": 1000, "name": "a.mp4"}, format="json"
        )
        self.assertEqual(made.status_code, 201, made.content)
        done = self.client.post(f"{self.base}/assets/{made.json()['id']}/complete", {"duration_seconds": 60}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        return made.json()["id"]


class StudioBasicsTests(StudioBase):
    def test_flag_storage_and_outsider(self):
        self._auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/projects").status_code, 403)
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self._auth(self.m1)
        self.assertEqual(self.client.get(f"{self.base}/projects").status_code, 501)
        self.org.settings = {"flags": {"content_studio": True}}
        self.org.save(update_fields=["settings"])
        with override_settings(CONTENT_STORAGE=""):
            response = self.client.post(
                f"{self.base}/assets", {"kind": "video", "content_type": "video/mp4", "size_bytes": 10}, format="json"
            )
        self.assertEqual(response.status_code, 501)

    def test_upload_rules(self):
        self._auth(self.m1)
        for body in (
            {"kind": "video", "content_type": "text/html", "size_bytes": 10},
            {"kind": "exe", "content_type": "video/mp4", "size_bytes": 10},
            {"kind": "video", "content_type": "video/mp4", "size_bytes": 0},
            {"kind": "video", "content_type": "video/mp4", "size_bytes": 10**13},
        ):
            self.assertEqual(self.client.post(f"{self.base}/assets", body, format="json").status_code, 400, body)
        made = self.client.post(
            f"{self.base}/assets", {"kind": "video", "content_type": "video/mp4", "size_bytes": 10, "name": "../../x y.mp4"}, format="json"
        ).json()
        asset = MediaAsset.objects.get(pk=made["id"])
        self.assertTrue(asset.storage_key.startswith(f"content/{self.org.id}/{asset.id}/"))
        self.assertNotIn("/", asset.storage_key.split(f"{asset.id}/")[1])
        too_long = self.client.post(f"{self.base}/assets/{asset.id}/complete", {"duration_seconds": 10**6}, format="json")
        self.assertEqual(too_long.status_code, 400)
        self._auth(self.m2)
        self.assertEqual(self.client.post(f"{self.base}/assets/{asset.id}/complete", {}, format="json").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/assets/{asset.id}").status_code, 404)

    @override_settings(CONTENT_STORAGE="s3", CONTENT_S3_BUCKET="test-bucket")
    def test_complete_requires_the_object_in_storage(self):
        with patch("content_studio.storage._client") as client:
            client.return_value.generate_presigned_url.return_value = "https://s3.example/put"
            self._auth(self.m1)
            made = self.client.post(
                f"{self.base}/assets", {"kind": "video", "content_type": "video/mp4", "size_bytes": 10}, format="json"
            ).json()
            self.assertEqual(made["upload_url"], "https://s3.example/put")
            from botocore.exceptions import ClientError

            client.return_value.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
            self.assertEqual(self.client.post(f"{self.base}/assets/{made['id']}/complete", {}, format="json").status_code, 409)
            client.return_value.head_object.side_effect = None
            client.return_value.head_object.return_value = {"ContentLength": 99, "ContentType": "video/mp4"}
            self.assertEqual(self.client.post(f"{self.base}/assets/{made['id']}/complete", {}, format="json").status_code, 400)
            client.return_value.head_object.return_value = {"ContentLength": 10, "ContentType": "video/mp4", "ETag": '"abc"'}
            no_length = self.client.post(f"{self.base}/assets/{made['id']}/complete", {}, format="json")
            self.assertEqual(no_length.status_code, 400, "video needs a duration")
            ok = self.client.post(f"{self.base}/assets/{made['id']}/complete", {"duration_seconds": 5}, format="json")
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(MediaAsset.objects.get(pk=made["id"]).source_etag, "abc")

    def test_projects_are_own_for_members_and_all_for_leads_and_admins(self):
        asset = self._ready_asset(self.m1)
        created = self.client.post(f"{self.base}/projects", {"title": "Shorts", "source_assets": [asset]}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        pid = created.json()["id"]
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/projects/{pid}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/projects").json(), [])
        stolen = self.client.post(f"{self.base}/projects", {"title": "x", "source_assets": [asset]}, format="json")
        self.assertEqual(stolen.status_code, 400, "another member's asset cannot be used")
        for viewer in (self.lead, self.owner):
            self._auth(viewer)
            self.assertEqual(self.client.get(f"{self.base}/projects/{pid}").status_code, 200)
        self._auth(self.outsider)
        foreign = f"/api/v2/orgs/{self.other_org.id}/content/projects"
        self.assertEqual(self.client.post(foreign, {"title": "x", "source_assets": [asset]}, format="json").status_code, 400)

    def test_brand_kits_and_templates_need_manage_to_edit(self):
        self._auth(self.m1)
        templates = self.client.get(f"{self.base}/templates").json()
        floq = next(t for t in templates if t["slug"] == "floq-question-card")
        self.assertEqual(floq["spec"]["resolution"], [1920, 1080])
        self.assertEqual(floq["spec"]["duration_seconds"], 3.0)
        self.assertEqual(self.client.post(f"{self.base}/brand-kits", {"name": "K"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{self.base}/templates/{floq['id']}", {"name": "x"}, format="json").status_code, 403)
        self._auth(self.owner)
        bad = self.client.post(f"{self.base}/brand-kits", {"name": "K", "colors": {"primary": "red"}}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(f"{self.base}/brand-kits", {"name": "K", "colors": {"primary": "#112233"}}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(
            self.client.post(f"{self.base}/templates", {"name": "T", "kind": "quote", "spec": {"resolution": [99999, 1]}}, format="json").status_code,
            400,
        )
        self.assertEqual(ContentTemplate.objects.filter(org=self.org).count(), 1)
        self.assertEqual(ContentProject.objects.count(), 0)
