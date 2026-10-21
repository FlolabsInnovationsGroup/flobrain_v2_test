import base64

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from learning.models import Certificate, LearningPath, MentorNote
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from tasks.models import Task, TaskAssignment
from timetracking.models import TimeEntry
from users.jwt_utils import make_access_token
from users.models import User

KEY = base64.b64encode(bytes(range(32))).decode()


@override_settings(CERTIFICATE_SIGNING_KEY=KEY)
class LearningTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="L", slug="l-org", settings={"flags": {"learning": True, "public_portfolio": True}})
        self.users = {}
        for name, role in (("admin", "admin"), ("mentor", "member"), ("mentee", "member"), ("other", "member")):
            u = User.objects.create(email=f"{name}@l.test", username=name.title(), password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_paths_respect_teams_and_track_progress(self):
        team = Team.objects.create(org=self.org, name="Eng")
        TeamMembership.objects.create(team=team, user=self.users["mentee"])
        admin = self._as("admin")
        self.assertEqual(self._as("mentee").post(f"{self.base}/learning/paths", {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(admin.post(f"{self.base}/learning/paths", {"name": "bad", "steps": [{"kind": "link", "title": "x", "ref": "javascript:alert(1)"}]}, format="json").status_code, 400)
        made = admin.post(
            f"{self.base}/learning/paths",
            {"name": "Eng onboarding", "team": str(team.id), "steps": [{"kind": "link", "title": "Read the guide", "ref": "https://example.com"}]},
            format="json",
        ).json()
        self.assertEqual(self._as("other").get(f"{self.base}/learning/paths").json(), [], "team path hidden from others")
        done = self._as("mentee").post(f"{self.base}/learning/paths/{made['id']}/progress", {"step": 0}, format="json").json()
        self.assertIsNotNone(done["completed_at"])
        self.assertEqual(self._as("mentee").post(f"{self.base}/learning/paths/{made['id']}/progress", {"step": 5}, format="json").status_code, 400)

    def test_quiz_answers_stay_on_the_server(self):
        admin = self._as("admin")
        quiz = admin.post(
            f"{self.base}/learning/quizzes",
            {"title": "Q", "questions": [{"question": "2+2?", "options": ["3", "4"], "answer": 1}]},
            format="json",
        ).json()
        self.assertEqual(self._as("mentee").get(f"{self.base}/learning/quizzes").json(), [], "drafts are hidden")
        admin.patch(f"{self.base}/learning/quizzes/{quiz['id']}", {"status": "published"}, format="json")
        seen = self._as("mentee").get(f"{self.base}/learning/quizzes").json()[0]
        self.assertNotIn("answer", seen["questions"][0])
        result = self._as("mentee").post(f"{self.base}/learning/quizzes/{quiz['id']}/attempts", {"answers": [1]}, format="json").json()
        self.assertEqual((result["score"], result["passed"]), (100, True))

    def test_certificate_is_signed_from_real_data_and_verifiable(self):
        mentee = self.users["mentee"]
        task = Task.objects.create(org=self.org, title="Ship", status=Task.STATUS_DONE)
        TaskAssignment.objects.create(task=task, user=mentee)
        start = timezone.now() - timezone.timedelta(hours=3)
        TimeEntry.objects.create(org=self.org, user=mentee, started_at=start, ended_at=start + timezone.timedelta(hours=2))
        self.assertEqual(self._as("mentor").post(f"{self.base}/certificates", {"user": str(mentee.id), "kind": "internship_completion"}, format="json").status_code, 403)
        cert = self._as("admin").post(f"{self.base}/certificates", {"user": str(mentee.id), "kind": "internship_completion"}, format="json").json()
        self.assertEqual((cert["data"]["tasks_completed"], cert["data"]["hours_total"]), (1, 2.0))
        public = APIClient().get(f"/api/public/verify/{cert['public_slug']}").json()
        self.assertTrue(public["signature_valid"])
        self.assertNotIn("email", str(public))
        # Tampering with stored data breaks the signature.
        Certificate.objects.filter(pk=cert["id"]).update(data={**cert["data"], "hours_total": 999})
        self.assertFalse(APIClient().get(f"/api/public/verify/{cert['public_slug']}").json()["signature_valid"])
        self._as("admin").post(f"{self.base}/certificates/{cert['id']}/revoke")
        self.assertTrue(APIClient().get(f"/api/public/verify/{cert['public_slug']}").json()["revoked"])
        self.assertEqual(APIClient().get("/api/public/verify/guess").status_code, 404)

    def test_portfolio_is_private_until_published(self):
        mentee = self._as("mentee")
        item = mentee.post(f"{self.base}/portfolio", {"kind": "project", "title": "Launch site"}, format="json").json()
        self.assertFalse(item["is_public"])
        mentee.post(f"{self.base}/portfolio", {"kind": "project", "title": "Secret"}, format="json")
        mentee.patch(f"{self.base}/portfolio/{item['id']}", {"is_public": True}, format="json")
        slug = User.objects.get(pk=self.users["mentee"].pk).portfolio_slug
        page = APIClient().get(f"/api/public/portfolio/{slug}").json()
        self.assertEqual([i["title"] for i in page["items"]], ["Launch site"])
        self.assertEqual(self._as("other").patch(f"{self.base}/portfolio/{item['id']}", {"is_public": False}, format="json").status_code, 404)
        self.org.settings = {"flags": {"learning": True}}
        self.org.save()
        self.assertEqual(APIClient().get(f"/api/public/portfolio/{slug}").status_code, 404, "org has not allowed public portfolios")

    def test_mentor_notes_are_for_the_pair_only(self):
        m = self._as("admin").post(
            f"{self.base}/mentorships", {"mentor": str(self.users["mentor"].id), "mentee": str(self.users["mentee"].id)}, format="json"
        ).json()
        url = f"{self.base}/mentorships/{m['id']}/notes"
        self.assertEqual(self._as("mentor").post(url, {"body": "Goals for week 1"}, format="json").status_code, 201)
        self.assertEqual(len(self._as("mentee").get(url).json()), 1)
        for outsider in ("admin", "other"):
            self.assertEqual(self._as(outsider).get(url).status_code, 404, outsider)
        self.assertEqual(self._as("mentee").get(f"{self.base}/mentorships/{m['id']}/progress").status_code, 404, "mentees don't see mentor data")
        self.assertEqual(self._as("mentor").get(f"{self.base}/mentorships/{m['id']}/progress").status_code, 200)
        self.assertEqual(MentorNote.objects.count(), 1)

    def test_flag_off(self):
        self.org.settings = {}
        self.org.save()
        self.assertEqual(self._as("mentee").get(f"{self.base}/learning/paths").status_code, 501)

    @override_settings(CERTIFICATE_SIGNING_KEY="")
    def test_signing_not_configured(self):
        res = self._as("admin").post(f"{self.base}/certificates", {"user": str(self.users["mentee"].id), "kind": "internship_completion"}, format="json")
        self.assertEqual(res.status_code, 501)
        self.assertFalse(LearningPath.objects.exists())

    def test_review_quiz_steps_need_a_pass_and_failures_reveal_nothing(self):
        admin = self._as("admin")
        quiz = admin.post(f"{self.base}/learning/quizzes", {"title": "Q", "questions": [{"question": "2+2?", "options": ["3", "4"], "answer": 1}]}, format="json").json()
        admin.patch(f"{self.base}/learning/quizzes/{quiz['id']}", {"status": "published"}, format="json")
        path = admin.post(f"{self.base}/learning/paths", {"name": "P", "steps": [{"kind": "quiz", "title": "Check", "ref": quiz["id"]}]}, format="json").json()
        mentee = self._as("mentee")
        self.assertEqual(mentee.post(f"{self.base}/learning/paths/{path['id']}/progress", {"step": 0}, format="json").status_code, 409)
        failed = mentee.post(f"{self.base}/learning/quizzes/{quiz['id']}/attempts", {"answers": [0]}, format="json").json()
        self.assertEqual(set(failed), {"passed", "pass_mark"})
        mentee.post(f"{self.base}/learning/quizzes/{quiz['id']}/attempts", {"answers": [1]}, format="json")
        self.assertEqual(mentee.post(f"{self.base}/learning/paths/{path['id']}/progress", {"step": 0}, format="json").status_code, 200)
        for _ in range(3):
            mentee.post(f"{self.base}/learning/quizzes/{quiz['id']}/attempts", {"answers": [1]}, format="json")
        self.assertEqual(mentee.post(f"{self.base}/learning/quizzes/{quiz['id']}/attempts", {"answers": [1]}, format="json").status_code, 429)

    def test_review_cohort_lists_and_key_rotation(self):
        self.assertEqual(self._as("admin").post(f"{self.base}/cohorts", {"name": "C", "members": 5}, format="json").status_code, 400)
        cert = self._as("admin").post(f"{self.base}/certificates", {"user": str(self.users["mentee"].id), "kind": "internship_completion"}, format="json").json()
        self.assertEqual(cert["data"]["projects"], [], "internal names stay off unless asked")
        from learning import certs

        old_public = certs.public_key_b64()
        new_key = base64.b64encode(bytes(range(1, 33))).decode()
        with override_settings(CERTIFICATE_SIGNING_KEY=new_key, CERTIFICATE_PREVIOUS_PUBLIC_KEYS=old_public):
            self.assertTrue(APIClient().get(f"/api/public/verify/{cert['public_slug']}").json()["signature_valid"])
        with override_settings(CERTIFICATE_SIGNING_KEY=new_key):
            self.assertFalse(APIClient().get(f"/api/public/verify/{cert['public_slug']}").json()["signature_valid"])

    def test_cohort_progress_for_instructors_and_leads(self):
        from learning.models import Cohort

        eng, design = Team.objects.create(org=self.org, name="Eng"), Team.objects.create(org=self.org, name="Design")
        TeamMembership.objects.create(team=eng, user=self.users["mentee"])
        TeamMembership.objects.create(team=design, user=self.users["other"])
        TeamMembership.objects.create(team=eng, user=self.users["mentor"], team_role=TeamMembership.ROLE_LEAD)
        cohort = Cohort.objects.create(org=self.org, name="Autumn")
        cohort.members.set([self.users["mentee"], self.users["other"]])
        url = f"{self.base}/cohorts/{cohort.id}"
        # The lead of Eng sees the cohort and only Eng's members in it.
        listed = self._as("mentor").get(f"{self.base}/cohorts").json()
        self.assertEqual([(c["name"], c["can_view_progress"], c["instructor"]) for c in listed], [("Autumn", True, False)])
        self.assertEqual([m["name"] for m in self._as("mentor").get(url).json()["members"]], ["Mentee"])
        # A cohort member sees the cohort exists, not the others' progress.
        member_view = self._as("other").get(f"{self.base}/cohorts").json()
        self.assertEqual([(c["is_member"], c["can_view_progress"]) for c in member_view], [(True, False)])
        self.assertEqual(self._as("other").get(url).status_code, 404)
        cohort.instructors.set([self.users["other"]])
        self.assertEqual(len(self._as("other").get(url).json()["members"]), 2, "instructors see everyone")
        self.assertEqual(len(self._as("admin").get(url).json()["members"]), 2)
        other_org = Organization.objects.create(name="X", slug="x-org", settings={"flags": {"learning": True}})
        self.assertEqual(self._as("admin").get(f"/api/v2/orgs/{other_org.id}/cohorts/{cohort.id}").status_code, 403)

    def test_mentor_sees_mentee_progress_only(self):
        from learning.models import Mentorship

        pair = Mentorship.objects.create(org=self.org, mentor=self.users["mentor"], mentee=self.users["mentee"])
        url = f"{self.base}/mentorships/{pair.id}/progress"
        self.assertEqual(self._as("mentor").get(url).status_code, 200)
        self.assertEqual(self._as("mentee").get(url).status_code, 404)
        self.assertEqual(self._as("other").get(url).status_code, 404)

    def _notion(self, audience_property="Team", demo=False):
        from connectors.models import Connection, ExternalItem
        from rooms.services import ensure_team_room

        team = Team.objects.create(org=self.org, name="Everyone")
        for name in ("mentor", "mentee", "admin"):
            TeamMembership.objects.create(team=team, user=self.users[name])
        eng = Team.objects.create(org=self.org, name="Engineering")
        TeamMembership.objects.create(team=eng, user=self.users["mentee"])
        room = ensure_team_room(team)
        conn = Connection.objects.create(
            org=self.org, connector="notion", label="Notion", room=room,
            config={"database_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "audience_property": audience_property, **({"demo": True} if demo else {})},
        )
        for i, (title, audience) in enumerate((("b: git", ["engineering"]), ("A: design", ["design"]), ("c: all", []), ("d: mentor", ["mentor@l.test"]))):
            ExternalItem.objects.create(org=self.org, connection=conn, kind="masterclass", external_id=str(i), title=title, url=f"https://www.notion.so/{i}", meta={"audience": audience})
        return conn

    def test_masterclasses_not_configured(self):
        res = self._as("mentee").get(f"{self.base}/learning/masterclasses").json()
        self.assertEqual((res["configured"], res["items"], res["can_connect"]), (False, [], False))
        self.assertTrue(self._as("admin").get(f"{self.base}/learning/masterclasses").json()["can_connect"])

    def test_masterclasses_filter_by_team_and_room(self):
        self._notion()
        mentee = self._as("mentee").get(f"{self.base}/learning/masterclasses").json()
        self.assertEqual([i["title"] for i in mentee["items"]], ["b: git", "c: all"], "sorted by title, own team or for everyone")
        self.assertNotIn("audience", mentee["items"][0], "members don't see audience lists")
        mentor = self._as("mentor").get(f"{self.base}/learning/masterclasses").json()
        self.assertEqual([i["title"] for i in mentor["items"]], ["c: all", "d: mentor"], "people property matches by email")
        admin = self._as("admin").get(f"{self.base}/learning/masterclasses").json()
        self.assertEqual([i["title"] for i in admin["items"]], ["A: design", "b: git", "c: all", "d: mentor"])
        self.assertEqual(admin["items"][0]["audience"], ["design"])
        self.assertFalse(admin["items"][0]["for_you"])
        other = self._as("other").get(f"{self.base}/learning/masterclasses").json()
        self.assertEqual((other["configured"], other["in_room"], other["items"]), (True, False, []), "not in the connection's room")

    def test_masterclasses_without_audience_property_show_all(self):
        self._notion(audience_property="")
        self.assertEqual(len(self._as("mentee").get(f"{self.base}/learning/masterclasses").json()["items"]), 4)

    def test_masterclasses_disconnected_show_nothing(self):
        conn = self._notion()
        conn.status = "revoked"
        conn.save()
        self.assertFalse(self._as("mentee").get(f"{self.base}/learning/masterclasses").json()["configured"])


class DemoCertificateKeyTests(TestCase):
    def setUp(self):
        from learning import certs

        certs._PROCESS_DEMO_SEED.clear()

    @override_settings(CERTIFICATE_SIGNING_KEY="", DEMO_MODE=False)
    def test_no_key_outside_demo(self):
        from learning import certs

        with self.assertRaises(certs.NotConfigured):
            certs.sign({"a": 1})

    @override_settings(CERTIFICATE_SIGNING_KEY="", DEMO_MODE=True)
    def test_demo_key_is_kept_in_the_demo_org_and_labelled(self):
        from learning import certs

        org = Organization.objects.create(name="Demo", slug="demo", settings={"demo": True, "flags": {"learning": True}})
        data = {"recipient": "Sara", "kind": "internship_completion"}
        sig, kid = certs.sign(data), certs.key_id()
        self.assertTrue(kid.startswith("demo-"))
        org.refresh_from_db()
        stored = org.settings["demo_certificate_key"]
        certs._PROCESS_DEMO_SEED.clear()  # another process: same key from the org
        self.assertEqual(certs.sign(data), sig)
        self.assertEqual(Organization.objects.get(pk=org.pk).settings["demo_certificate_key"], stored)
        user = User.objects.create(email="sara@demo.test", username="Sara", password_hash=make_password("x"))
        cert = Certificate.objects.create(org=org, user=user, kind="internship_completion", data=data, signature=sig, key_id=kid)
        page = APIClient().get(f"/api/public/verify/{cert.public_slug}").json()
        self.assertTrue(page["signature_valid"])
        self.assertTrue(page["demo_key"])
        self.assertTrue(APIClient().get("/api/public/certificates/public-key").json()["demo"])

    @override_settings(CERTIFICATE_SIGNING_KEY="", DEMO_MODE=True)
    def test_demo_key_without_demo_org_is_per_process(self):
        from learning import certs

        self.assertEqual(certs.sign({"a": 1}), certs.sign({"a": 1}))
        self.assertTrue(certs.verify({"a": 1}, certs.sign({"a": 1}), certs.key_id()))

    def test_real_key_is_not_a_demo_key(self):
        from learning import certs

        with override_settings(CERTIFICATE_SIGNING_KEY=KEY, DEMO_MODE=True):
            self.assertFalse(certs.key_id().startswith("demo-"))


@override_settings(DEMO_MODE=True, DEMO_AI=True, CERTIFICATE_SIGNING_KEY="")
class DemoDocsLearningSeedTests(TestCase):
    def test_demo_seed_has_signed_certificate_masterclasses_and_working_syncs(self):
        import tempfile
        from unittest.mock import patch

        from connectors.models import Connection, ExternalItem
        from demo import seed
        from docs_app.models import Document, DocumentRevision, StoredFile

        with tempfile.TemporaryDirectory() as media, override_settings(DOCS_LOCAL_STORAGE_DIR=media), patch(
            "platform_api.net.fetch", side_effect=AssertionError("demo never calls the network")
        ):
            org = seed.reset()
            from demo.models import DemoAccount

            users = {a.role: a.user for a in DemoAccount.objects.select_related("user")}
            users["designer"] = User.objects.get(email=seed.email_for("designer"))
            cert = Certificate.objects.get(org=org, public_slug="demo-sara-internship")
            page = APIClient().get(f"/api/public/verify/{cert.public_slug}").json()
            self.assertTrue(page["signature_valid"] and page["demo_key"])
            plan = Document.objects.get(org=org, title="Launch plan")
            self.assertEqual((plan.version, DocumentRevision.objects.filter(document=plan).count()), (3, 3))
            self.assertEqual(StoredFile.objects.filter(document=plan, status="ready").count(), 1)

            def client(role):
                c = APIClient()
                c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(users[role].id))}")
                return c

            base = f"/api/v2/orgs/{org.id}"
            download = client("member").get(f"{base}/files/{StoredFile.objects.get(document=plan).id}/download")
            self.assertEqual(download.status_code, 200)
            classes = client("member").get(f"{base}/learning/masterclasses").json()
            self.assertTrue(classes["demo"])
            titles = [i["title"] for i in classes["items"]]
            self.assertEqual(titles, sorted(titles, key=str.casefold))
            self.assertIn("Writing good tickets", titles)
            lead_titles = [i["title"] for i in client("lead").get(f"{base}/learning/masterclasses").json()["items"]]
            self.assertNotIn("Design critique basics", lead_titles, "Layla is only in Engineering")
            for conn in Connection.objects.filter(org=org):
                synced = client("admin").post(f"{base}/integrations/connections/{conn.id}/sync")
                self.assertEqual((synced.status_code, synced.json()["last_error"], synced.json()["demo"]), (200, "", True))
            self.assertTrue(ExternalItem.objects.filter(connection__connector="github", external_id="44").exists())
            cohorts = client("lead").get(f"{base}/cohorts").json()
            self.assertTrue(cohorts[0]["can_view_progress"])
            progress = client("lead").get(f"{base}/cohorts/{cohorts[0]['id']}").json()
            self.assertTrue(any(m["paths"] for m in progress["members"]))
