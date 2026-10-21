"""Data buddy API: flag off, permissions, sharing, uploads, sheets, PostgreSQL (mocked), asking,
cards, reports, the scheduled runner and the buddy tool. Nothing reaches the network."""

from datetime import datetime
from datetime import timezone as dt_timezone
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from datasets import services
from datasets.models import Dataset, Report, ReportRun, SavedQuestion
from notifications.models import Notification
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from users.jwt_utils import make_access_token
from users.models import User

TEST_KEY = "cd" * 32  # test-only, never a real key
SIGNUPS = (
    "Week,Channel,Signups\n"
    "2026-10-05,Website,40\n2026-10-05,Referral,12\n"
    "2026-10-12,Website,45\n2026-10-12,Referral,15\n"
).encode()
SHEET = "https://docs.google.com/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv"
DSN = "postgresql://reader:Sup3r-Secret-pw@db.example.com:5432/sales"
DEMO = override_settings(DEMO_MODE=True, DEMO_AI=True)


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY)
class DataBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="D Org", slug="d-org", settings={"flags": {"data_buddy": True}})
        self.users = {}
        for key, role in (("owner", "owner"), ("admin", "admin"), ("member", "member"), ("teammate", "member"), ("other", "member")):
            user = User.objects.create(email=f"d-{key}@example.com", password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
            self.users[key] = user
        self.outsider = User.objects.create(email="d-out@example.com", password_hash=make_password("x"))
        self.team = Team.objects.create(org=self.org, name="Growth")
        for key in ("member", "teammate"):
            TeamMembership.objects.create(team=self.team, user=self.users[key])
        self.base = f"/api/v2/orgs/{self.org.id}/data"

    def auth(self, key):
        user = self.users[key] if isinstance(key, str) else key
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def upload(self, key="admin", data=SIGNUPS, name="signups.csv", **fields):
        self.auth(key)
        body = {"file": SimpleUploadedFile(name, data, content_type="text/csv"), "visibility": "org", **fields}
        return self.client.post(f"{self.base}/datasets/upload", body, format="multipart")

    def dataset(self, **fields):
        response = self.upload(**fields)
        self.assertEqual(response.status_code, 201, response.content)
        return Dataset.objects.get(pk=response.json()["id"])


class GateTests(DataBase):
    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {"data_buddy": False}}
        self.org.save()
        self.auth("admin")
        for path in ("/datasets", "/meta", "/cards", "/reports"):
            self.assertEqual(self.client.get(self.base + path).status_code, 501, path)
        self.assertEqual(self.client.post(f"{self.base}/ask", {"dataset_id": "x", "question": "q"}, format="json").status_code, 501)

    def test_flag_off_for_one_member(self):
        membership = OrgMembership.objects.get(org=self.org, user=self.users["member"])
        membership.feature_flags = {"data_buddy": False}
        membership.save()
        self.auth("member")
        self.assertEqual(self.client.get(f"{self.base}/datasets").status_code, 501)
        self.auth("teammate")
        self.assertEqual(self.client.get(f"{self.base}/datasets").status_code, 200)

    def test_outsider_and_anonymous_refused(self):
        self.assertEqual(self.client.get(f"{self.base}/datasets").status_code, 401)
        self.auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/datasets").status_code, 403)

    def test_data_use_required(self):
        self.auth("member")
        with patch("datasets.views.can", return_value=False):
            self.assertEqual(self.client.get(f"{self.base}/datasets").status_code, 403)

    def test_members_cannot_add_sources(self):
        response = self.upload("member")
        self.assertEqual(response.status_code, 403)
        self.auth("member")
        self.assertEqual(self.client.post(f"{self.base}/datasets/sheet", {"url": SHEET, "name": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{self.base}/datasets/postgres", {"dsn": DSN, "name": "x"}, format="json").status_code, 403)

    def test_meta(self):
        self.auth("member")
        body = self.client.get(f"{self.base}/meta").json()
        self.assertFalse(body["can_manage"])
        self.assertEqual(body["max_upload_mb"], 10)
        self.assertEqual(body["query_max_rows"], 5000)


class UploadTests(DataBase):
    def test_upload_creates_typed_dataset_outside_main_db(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["row_count"], 4)
        columns = body["tables"][0]["columns"]
        self.assertEqual([(c["name"], c["type"]) for c in columns], [("week", "date"), ("channel", "text"), ("signups", "integer")])
        self.assertEqual(len(body["tables"][0]["sample_rows"]), 4)
        ds = Dataset.objects.get(pk=body["id"])
        self.assertTrue(services.store.path_for(ds.file_key).endswith(".sqlite3"))
        self.assertEqual(services.run_sql(ds, "SELECT SUM(signups) FROM data")["rows"], [[112]])

    @override_settings(DATASETS_MAX_UPLOAD_MB=0)
    def test_too_large(self):
        self.assertEqual(self.upload().status_code, 413)

    @override_settings(DATASETS_MAX_ROWS=2)
    def test_too_many_rows(self):
        response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "too_many_rows")

    def test_bad_type_and_missing_file(self):
        self.assertEqual(self.upload(name="x.exe", data=b"MZ").json()["error"], "unsupported")
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/datasets/upload", {}, format="multipart").status_code, 400)

    def test_delete_removes_file(self):
        ds = self.dataset()
        path = services.store.path_for(ds.file_key)
        self.auth("admin")
        self.assertEqual(self.client.delete(f"{self.base}/datasets/{ds.id}").status_code, 204)
        self.assertFalse(Dataset.objects.filter(pk=ds.pk).exists())
        import os

        self.assertFalse(os.path.exists(path))

    def test_upload_cannot_be_refreshed(self):
        ds = self.dataset()
        self.assertEqual(self.client.post(f"{self.base}/datasets/{ds.id}/refresh").status_code, 409)


class SharingTests(DataBase):
    def ids(self, key):
        self.auth(key)
        return {d["id"] for d in self.client.get(f"{self.base}/datasets").json()}

    def test_visibility(self):
        org_ds = self.dataset(visibility="org", name="org.csv")
        team_ds = self.dataset(visibility="team", team=str(self.team.id), name="team.csv")
        mine = self.dataset(visibility="owner", name="mine.csv")
        everyone, team, private = str(org_ds.id), str(team_ds.id), str(mine.id)
        self.assertEqual(self.ids("admin"), {everyone, team, private})
        self.assertEqual(self.ids("teammate"), {everyone, team})
        self.assertEqual(self.ids("other"), {everyone})
        self.assertEqual(self.ids("owner"), {everyone, team})  # owner-only means only its owner
        self.auth("other")
        self.assertEqual(self.client.get(f"{self.base}/datasets/{team}").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/ask", {"dataset_id": private, "question": "q"}, format="json").status_code, 404)

    def test_team_sharing_needs_a_team_you_are_in(self):
        self.assertEqual(self.upload(visibility="team").status_code, 400)  # no team picked
        with patch("datasets.views.can", return_value=True):  # "other" may add sources but is not in Growth
            response = self.upload("other", visibility="team", team=str(self.team.id))
        self.assertEqual(response.status_code, 400)

    def test_only_owner_or_admin_manages(self):
        ds = self.dataset(visibility="org")
        self.auth("member")
        self.assertEqual(self.client.patch(f"{self.base}/datasets/{ds.id}", {"name": "x"}, format="json").status_code, 403)
        self.auth("owner")
        response = self.client.patch(f"{self.base}/datasets/{ds.id}", {"name": "Renamed", "visibility": "team", "team": str(self.team.id)}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["visibility"], "team")


class SheetTests(DataBase):
    def fake_fetch(self, body=b"Category,Budgeted,Spent\nAds,100,40\nRent,50,50\n"):
        return patch("platform_api.net.fetch_full", return_value=(200, {"content-type": "text/csv"}, body))

    def test_add_sheet(self):
        self.auth("admin")
        with self.fake_fetch():
            response = self.client.post(f"{self.base}/datasets/sheet", {"url": SHEET, "name": "Budget", "visibility": "org"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["kind"], body["row_count"], body["refresh_every_hours"]), ("sheet", 2, 24))
        self.assertIsNotNone(body["next_refresh_at"])

    def test_bad_url_never_fetched(self):
        self.auth("admin")
        with patch("platform_api.net.fetch_full") as fetch:
            response = self.client.post(f"{self.base}/datasets/sheet", {"url": "https://evil.example/x.csv", "name": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_url")
        fetch.assert_not_called()

    def test_scheduled_refresh(self):
        self.auth("admin")
        with self.fake_fetch():
            ds_id = self.client.post(f"{self.base}/datasets/sheet", {"url": SHEET, "name": "B", "visibility": "org"}, format="json").json()["id"]
        Dataset.objects.filter(pk=ds_id).update(next_refresh_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc))
        with self.fake_fetch(b"Category,Budgeted,Spent\nAds,100,40\nRent,50,50\nTravel,9,1\n"):
            self.assertEqual(services.refresh_due_sheets(), 1)
            self.assertEqual(services.refresh_due_sheets(), 0)  # not due again
        ds = Dataset.objects.get(pk=ds_id)
        self.assertEqual(ds.row_count, 3)
        Dataset.objects.filter(pk=ds_id).update(next_refresh_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc))
        with patch("platform_api.net.fetch_full", side_effect=OSError("down")):
            services.refresh_due_sheets()
        ds.refresh_from_db()
        self.assertEqual(ds.status, "error")
        self.assertEqual(ds.row_count, 3)  # the old copy stays usable


class PostgresTests(DataBase):
    TABLES = [{"name": "orders", "label": "orders", "columns": [{"name": "total", "label": "total", "type": "real"}], "sample_rows": [[1.5]], "row_count": None}]

    def create(self, dsn=DSN, key="admin"):
        self.auth(key)
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]), patch("psycopg2.connect", return_value=MagicMock()), \
                patch("datasets.pg.introspect", return_value=self.TABLES):
            return self.client.post(f"{self.base}/datasets/postgres", {"dsn": dsn, "name": "Sales", "visibility": "org"}, format="json")

    def test_dsn_encrypted_and_masked(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotIn("Sup3r-Secret-pw", response.content.decode())
        self.assertEqual(response.json()["connection"], "postgresql://reader:••••@db.example.com:5432/sales")
        ds = Dataset.objects.get(pk=response.json()["id"])
        self.assertNotIn(b"Sup3r-Secret-pw", bytes(ds.dsn_ciphertext))
        self.assertEqual(services.decrypt_dsn(ds), DSN)
        self.assertNotIn("Sup3r", repr(ds))
        listed = self.client.get(f"{self.base}/datasets").content.decode()
        self.assertNotIn("Sup3r-Secret-pw", listed)

    def test_private_host_blocked_until_admin_allows(self):
        self.auth("admin")
        response = self.client.post(f"{self.base}/datasets/postgres", {"dsn": "postgresql://u:pw@10.0.0.5/db", "name": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "private_host")
        self.auth("member")
        self.assertEqual(self.client.patch(f"{self.base}/settings", {"allow_private_hosts": True}, format="json").status_code, 403)
        self.auth("admin")
        self.assertEqual(self.client.patch(f"{self.base}/settings", {"allow_private_hosts": True}, format="json").status_code, 200)
        with patch("psycopg2.connect", return_value=MagicMock()), patch("datasets.pg.introspect", return_value=self.TABLES):
            response = self.client.post(f"{self.base}/datasets/postgres", {"dsn": "postgresql://u:pw@10.0.0.5/db", "name": "x"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_needs_encryption_key(self):
        with override_settings(CREDENTIALS_ENCRYPTION_KEY=""):
            self.assertEqual(self.create().status_code, 501)

    def test_queries_stay_in_shared_tables(self):
        ds = Dataset.objects.get(pk=self.create().json()["id"])
        with self.assertRaises(services.DataError) as ctx:
            services.run_sql(ds, "SELECT * FROM customers")
        self.assertEqual(ctx.exception.code, "sql_rejected")
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchmany.return_value = [(3.5,)]
        cursor.description = [("sum",)]
        with patch("datasets.pg.connect", return_value=conn):
            self.assertEqual(services.run_sql(ds, "SELECT sum(total) FROM orders")["rows"], [[3.5]])
        conn.close.assert_called()


@DEMO
class AskTests(DataBase):
    def ask(self, ds, question, key="admin"):
        self.auth(key)
        return self.client.post(f"{self.base}/ask", {"dataset_id": str(ds.id), "question": question}, format="json")

    def test_happy_path(self):
        ds = self.dataset()
        response = self.ask(ds, "sign-ups by channel")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIn("GROUP BY channel", body["sql"])
        self.assertEqual(body["columns"], ["channel", "signups"])
        self.assertEqual(body["rows"], [["Website", 85], ["Referral", 27]])
        self.assertEqual(body["chart"], {"type": "bar", "x": "channel", "y": ["signups"], "series": None})
        self.assertIn("(Demo answer)", body["answer"])

    def test_this_week_vs_last(self):
        body = self.ask(self.dataset(), "sign-ups this week vs last").json()
        self.assertEqual(body["rows"], [["2026-10-05", 52], ["2026-10-12", 60]])
        self.assertIn("+15%", body["answer"])

    def test_hostile_model_sql_never_runs(self):
        ds = self.dataset()
        for sql in ("DELETE FROM data", "SELECT * FROM sqlite_master", "SELECT 1; DROP TABLE data", "ATTACH 'x' AS y"):
            with patch("datasets.services._llm", return_value={"sql": sql}):
                response = self.ask(ds, "anything")
            self.assertEqual(response.status_code, 422, sql)
            self.assertEqual(response.json()["error"], "sql_rejected")
        self.assertEqual(services.run_sql(ds, "SELECT count(*) FROM data")["rows"], [[4]])

    def test_invalid_chart_is_replaced(self):
        ds = self.dataset()
        answers = iter([{"sql": "SELECT channel, SUM(signups) AS n FROM data GROUP BY channel"}, {"answer": "x", "chart": {"type": "pie", "x": "nope"}}])
        with patch("datasets.services._llm", side_effect=lambda *a: next(answers)):
            body = self.ask(ds, "q").json()
        self.assertTrue(body["chart_fixed"])
        self.assertEqual(body["chart"]["type"], "bar")

    def test_row_cap_in_response(self):
        ds = self.dataset()
        with override_settings(DATASETS_QUERY_MAX_ROWS=2), patch("datasets.services._llm", side_effect=[{"sql": "SELECT * FROM data"}, {"answer": "a", "chart": {"type": "table"}}]):
            body = self.ask(ds, "q").json()
        self.assertEqual(len(body["rows"]), 2)
        self.assertTrue(body["truncated"])

    def test_question_validated(self):
        ds = self.dataset()
        self.assertEqual(self.ask(ds, "").status_code, 400)
        self.assertEqual(self.ask(ds, "x" * 501).status_code, 400)

    def test_not_configured_without_ai(self):
        ds = self.dataset()
        with override_settings(DEMO_MODE=False, DEMO_AI=False, AI_DIRECT_BASE_URL="", AI_DIRECT_API_KEY=""):
            self.assertEqual(self.ask(ds, "q").status_code, 501)


@DEMO
class CardAndReportTests(DataBase):
    def card(self, ds, key="admin", sql="SELECT channel, SUM(signups) AS signups FROM data GROUP BY channel ORDER BY signups DESC"):
        self.auth(key)
        return self.client.post(f"{self.base}/cards", {"dataset_id": str(ds.id), "title": "By channel", "question": "q", "sql": sql,
                                                       "chart": {"type": "bar", "x": "channel", "y": ["signups"]}}, format="json")

    def test_save_card_checks_sql(self):
        ds = self.dataset()
        response = self.card(ds)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["result"]["rows"][0], ["Website", 85])
        bad = self.card(ds, sql="DELETE FROM data")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(SavedQuestion.objects.count(), 1)

    def test_cards_follow_dataset_visibility(self):
        ds = self.dataset(visibility="owner")
        self.card(ds)
        self.auth("member")
        self.assertEqual(self.client.get(f"{self.base}/cards").json(), [])
        self.assertEqual(self.card(ds, key="member").status_code, 404)

    def test_card_run_and_edit_rights(self):
        ds = self.dataset()
        card_id = self.card(ds).json()["id"]
        self.auth("member")
        self.assertEqual(self.client.post(f"{self.base}/cards/{card_id}/run").status_code, 200)
        self.assertEqual(self.client.delete(f"{self.base}/cards/{card_id}").status_code, 403)
        self.auth("admin")
        self.assertEqual(self.client.patch(f"{self.base}/cards/{card_id}", {"chart": {"type": "line", "x": "nope", "y": ["x"]}}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"{self.base}/cards/{card_id}").status_code, 204)

    def test_next_run(self):
        report = Report(cadence="weekly", weekday=0, hour=8)
        after = datetime(2026, 10, 21, 12, tzinfo=dt_timezone.utc)  # a Wednesday
        self.assertEqual(services.next_run(report, after), datetime(2026, 10, 26, 8, tzinfo=dt_timezone.utc))
        self.assertEqual(services.next_run(report, datetime(2026, 10, 26, 7, tzinfo=dt_timezone.utc)), datetime(2026, 10, 26, 8, tzinfo=dt_timezone.utc))
        monthly = Report(cadence="monthly", day_of_month=15, hour=6)
        self.assertEqual(services.next_run(monthly, after), datetime(2026, 11, 15, 6, tzinfo=dt_timezone.utc))
        self.assertEqual(services.next_run(monthly, datetime(2026, 12, 20, tzinfo=dt_timezone.utc)), datetime(2027, 1, 15, 6, tzinfo=dt_timezone.utc))

    def make_report(self, **extra):
        ds = self.dataset()
        card_id = self.card(ds).json()["id"]
        self.auth("admin")
        response = self.client.post(f"{self.base}/reports", {"name": "Monday", "cards": [card_id], "cadence": "weekly", "weekday": 0, "hour": 8,
                                                             "recipients": [str(self.users["member"].id)], **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return Report.objects.get(pk=response.json()["id"])

    def test_due_report_runs_once_and_notifies(self):
        from rooms.models import Room, RoomMember, RoomMessage

        room = Room.objects.create(org=self.org, name="Numbers", kind=Room.KIND_GROUP)
        RoomMember.objects.create(room=room, user=self.users["admin"])
        report = self.make_report(room=str(room.id))
        Report.objects.filter(pk=report.pk).update(next_run_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc))
        out = StringIO()
        call_command("run_data_reports", stdout=out)
        self.assertIn("reports_sent 1", out.getvalue())
        call_command("run_data_reports", stdout=out)
        self.assertEqual(ReportRun.objects.filter(report=report).count(), 1)
        notes = Notification.objects.filter(kind="data.report")
        self.assertEqual({n.user_id for n in notes}, {self.users["admin"].id, self.users["member"].id})
        self.assertIn("Website: 85 signups", notes.first().payload["text"])
        self.assertTrue(RoomMessage.objects.filter(room=room, author=self.users["admin"]).exists())
        report.refresh_from_db()
        self.assertGreater(report.next_run_at, datetime(2026, 1, 1, tzinfo=dt_timezone.utc))

    def test_report_skipped_when_flag_off(self):
        report = self.make_report()
        Report.objects.filter(pk=report.pk).update(next_run_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc))
        self.org.settings = {"flags": {"data_buddy": False}}
        self.org.save()
        self.assertEqual(services.run_due_reports(), 0)
        self.assertFalse(ReportRun.objects.exists())

    def test_recipient_who_cannot_see_is_skipped(self):
        report = self.make_report()
        ds = report.cards.first().dataset
        ds.visibility, ds.team = "team", self.team
        ds.save()
        report.recipients.set([self.users["other"]])
        services.run_report(report)
        self.assertEqual(set(Notification.objects.filter(kind="data.report").values_list("user_id", flat=True)), {self.users["admin"].id})

    def test_report_access(self):
        report = self.make_report()
        self.auth("other")
        self.assertEqual(self.client.get(f"{self.base}/reports").json(), [])
        self.assertEqual(self.client.delete(f"{self.base}/reports/{report.id}").status_code, 404)
        self.auth("member")  # a recipient sees it but cannot change it
        self.assertEqual(len(self.client.get(f"{self.base}/reports").json()), 1)
        self.assertEqual(self.client.patch(f"{self.base}/reports/{report.id}", {"hour": 9}, format="json").status_code, 404)
        self.auth("admin")
        response = self.client.post(f"{self.base}/reports/{report.id}/run")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run"]["status"], "ok")

    def test_report_validation(self):
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/reports", {"name": "x", "cards": []}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/reports", {"name": "x", "cards": [str(self.org.id)]}, format="json").status_code, 404)


@DEMO
class ToolTests(DataBase):
    def test_registered_read_only(self):
        from actions.plugins import handler
        from actions.registry import TOOLS

        spec = TOOLS["data.ask"]
        self.assertEqual((spec["perm_key"], spec["risk"]), ("data.use", "read"))
        self.assertIsNotNone(handler("data.ask"))

    def test_check_and_execute(self):
        from actions.service import ActionDenied, check, execute

        ds = self.dataset(visibility="owner")
        args = {"question": "tickets by status", "dataset": str(ds.id)}
        self.assertIn(ds.name, check("data.ask", self.users["admin"], self.org, args))
        result = execute("data.ask", self.users["admin"], self.org, {"question": "sign-ups by channel", "dataset_name": ds.name})
        self.assertEqual(result["rows"][0], ["Website", 85])
        self.assertIn("SELECT", result["sql"])
        with self.assertRaises(ActionDenied):
            check("data.ask", self.users["member"], self.org, args)  # owner-only dataset
        self.org.settings = {"flags": {"data_buddy": False}}
        self.org.save()
        with self.assertRaises(ActionDenied):
            check("data.ask", self.users["admin"], self.org, args)


@DEMO
class DemoSeedTests(DataBase):
    def test_demo_extra_seeds_three_datasets_cards_and_report(self):
        import importlib

        from django.utils import timezone

        module = importlib.import_module("demo.extras.93_datasets")
        users = {"owner": self.users["owner"], "admin": self.users["admin"], "lead": self.users["member"], "member": self.users["teammate"], "designer": self.users["other"]}
        Team.objects.create(org=self.org, name="Engineering")
        module.seed(self.org, users, timezone.now())
        self.assertEqual(Dataset.objects.filter(org=self.org).count(), 3)
        self.assertEqual(SavedQuestion.objects.filter(org=self.org).count(), 4)
        report = Report.objects.get(org=self.org)
        self.assertEqual(report.cards.count(), 3)
        self.assertEqual(ReportRun.objects.filter(report=report).count(), 1)
        budget = Dataset.objects.get(org=self.org, name="Q4 budget lines")
        result = services.run_sql(budget, "SELECT category, ROUND(SUM(budgeted) - SUM(spent), 2) AS budget_left FROM data GROUP BY category ORDER BY budget_left DESC")
        self.assertEqual(result["rows"][0], ["Travel", 7900.0])
        self.auth("admin")
        with patch("platform_api.net.fetch_full") as fetch:
            response = self.client.post(f"{self.base}/datasets/{budget.id}/refresh")
        self.assertEqual(response.status_code, 409)
        fetch.assert_not_called()
        tickets = Dataset.objects.get(org=self.org, name="Support tickets")
        body = self.client.post(f"{self.base}/ask", {"dataset_id": str(tickets.id), "question": "tickets by status"}, format="json").json()
        self.assertEqual(body["columns"], ["status", "tickets"])
        self.assertEqual(sum(r[1] for r in body["rows"]), 140)
        budget_body = self.client.post(f"{self.base}/ask", {"dataset_id": str(budget.id), "question": "budget left by category"}, format="json").json()
        self.assertEqual(budget_body["chart"]["x"], "category")

