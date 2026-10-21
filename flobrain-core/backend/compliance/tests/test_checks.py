"""Every automated check against fixtures: the failing state, then the passing state."""

import os
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from compliance import checks, readiness
from compliance.models import AccessReview, ControlAttestation, Policy, PolicyAck, PolicyVersion, TrustCenter
from compliance.tests.base import MASTER_KEY, ComplianceBase
from organizations.models import OrgPolicy, PermissionGrant, PermissionRequest
from organizations.services.core import audit


def run(key, org):
    return checks.run_check(key, org)


class IdentityChecks(ComplianceBase):
    def test_sso_enforced(self):
        from sso.models import SSOConnection

        self.assertEqual(run("sso_enforced", self.org)["status"], "fail")
        conn = SSOConnection.objects.create(org=self.org, issuer="https://idp.example.com", client_id="c", secret_ciphertext=b"x", enabled=True, verified_domains=["example.com"])
        result = run("sso_enforced", self.org)
        self.assertEqual(result["status"], "fail")
        self.assertIn("password sign-in still works", result["summary"])
        conn.enforced = True
        conn.save()
        self.assertEqual(run("sso_enforced", self.org)["status"], "pass")

    def test_scim(self):
        from sso.models import SCIMToken

        self.assertEqual(run("scim", self.org)["status"], "manual")
        SCIMToken.objects.create(org=self.org, token_hash="h" * 64, last4="wxyz", created_by=self.users["owner"])
        result = run("scim", self.org)
        self.assertEqual(result["status"], "pass")
        self.assertNotIn("h" * 64, str(result))

    def test_owner_mfa_is_not_tracked(self):
        result = run("owner_mfa", self.org)
        self.assertEqual(result["status"], "manual")
        self.assertIn("Not tracked", result["summary"])

    def test_admin_count(self):
        self.assertEqual(run("admin_count", self.org)["status"], "pass")  # 2 of 5, limit 3
        for key in ("lead", "member"):
            m = self.membership(key)
            m.org_role = "admin"
            m.save()
        result = run("admin_count", self.org)
        self.assertEqual(result["status"], "fail")
        self.assertIn("4 people", result["summary"])

    def test_dormant_members(self):
        now = timezone.now()
        for user in self.users.values():
            user.last_active = now - timedelta(days=1)
            user.save()
        self.assertEqual(run("dormant_members", self.org)["status"], "pass")
        member = self.users["member"]
        member.last_active = now - timedelta(days=120)
        member.save()
        result = run("dormant_members", self.org)
        self.assertEqual(result["status"], "fail")
        self.assertIn("1 active members", result["summary"])
        # A paused member who is dormant does not count.
        m = self.membership("member")
        m.employment_status = "paused"
        m.save()
        self.assertEqual(run("dormant_members", self.org)["status"], "pass")

    def test_new_members_who_never_signed_in_are_not_dormant_yet(self):
        self.assertEqual(run("dormant_members", self.org)["status"], "pass")
        m = self.membership("teammate")
        m.created_at = timezone.now() - timedelta(days=200)
        m.save()
        self.assertEqual(run("dormant_members", self.org)["status"], "fail")

    def test_pending_requests(self):
        req = PermissionRequest.objects.create(org=self.org, requester=self.users["member"], perm_key="audit.view")
        self.assertEqual(run("pending_requests", self.org)["status"], "pass")
        PermissionRequest.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(days=20))
        self.assertEqual(run("pending_requests", self.org)["status"], "fail")
        PermissionRequest.objects.filter(pk=req.pk).update(status="approved")
        self.assertEqual(run("pending_requests", self.org)["status"], "pass")

    def test_leavers_access(self):
        PermissionGrant.objects.create(org=self.org, grantee=self.users["member"], perm_key="audit.view")
        self.assertEqual(run("leavers_access", self.org)["status"], "pass")
        m = self.membership("member")
        m.employment_status = "terminated"
        m.save()
        self.assertEqual(run("leavers_access", self.org)["status"], "fail")
        PermissionGrant.objects.filter(grantee=self.users["member"]).update(revoked_at=timezone.now())
        self.assertEqual(run("leavers_access", self.org)["status"], "pass")

    def test_access_review_recent(self):
        self.assertEqual(run("access_review_recent", self.org)["status"], "fail")
        review = AccessReview.objects.create(org=self.org, name="Q3", status=AccessReview.OPEN)
        self.assertIn("in progress", run("access_review_recent", self.org)["summary"])
        review.status, review.completed_at = AccessReview.COMPLETED, timezone.now() - timedelta(days=100)
        review.save()
        self.assertEqual(run("access_review_recent", self.org)["status"], "fail")
        review.completed_at = timezone.now() - timedelta(days=10)
        review.save()
        self.assertEqual(run("access_review_recent", self.org)["status"], "pass")


class DataChecks(ComplianceBase):
    def test_audit_log(self):
        self.assertEqual(run("audit_log", self.org)["status"], "fail")
        audit(self.users["admin"], "member.role", org=self.org)
        self.assertEqual(run("audit_log", self.org)["status"], "pass")

    def test_retention_policy(self):
        from privacy.models import RetentionPolicy

        self.assertEqual(run("retention_policy", self.org)["status"], "fail")
        RetentionPolicy.objects.create(org=self.org)
        self.assertEqual(run("retention_policy", self.org)["status"], "fail")  # a row with nothing set keeps data forever
        RetentionPolicy.objects.filter(org=self.org).update(messages_days=365)
        self.assertEqual(run("retention_policy", self.org)["status"], "pass")

    def test_encryption_reports_presence_only(self):
        with patch.dict(os.environ, {"AES_MASTER_KEY": "0" * 64}):
            result = run("encryption", self.org)
        self.assertEqual(result["status"], "fail")
        with patch.dict(os.environ, {"AES_MASTER_KEY": MASTER_KEY}):
            result = run("encryption", self.org)
        self.assertEqual(result["status"], "pass")
        self.assertNotIn(MASTER_KEY, str(result))
        self.assertNotIn("ab" * 32, str(result))
        with override_settings(CREDENTIALS_ENCRYPTION_KEY=""), patch.dict(os.environ, {"AES_MASTER_KEY": MASTER_KEY}):
            self.assertEqual(run("encryption", self.org)["status"], "fail")

    def test_backup_export(self):
        from exports.models import MemoryExport

        self.assertEqual(run("backup_export", self.org)["status"], "fail")
        export = MemoryExport.objects.create(org=self.org, status="succeeded", finished_at=timezone.now() - timedelta(days=40))
        self.assertEqual(run("backup_export", self.org)["status"], "fail")
        MemoryExport.objects.filter(pk=export.pk).update(finished_at=timezone.now() - timedelta(days=2))
        self.assertEqual(run("backup_export", self.org)["status"], "pass")

    def test_data_region(self):
        self.assertEqual(run("data_region", self.org)["status"], "fail")
        OrgPolicy.objects.create(org=self.org, data_region="eu-central-1")
        result = run("data_region", self.org)
        self.assertEqual(result["status"], "pass")
        self.assertIn("eu-central-1", result["summary"])

    def test_incidents(self):
        from platform_api.models import Incident

        self.assertEqual(run("incidents", self.org)["status"], "manual")
        Incident.objects.create(title="Platform-wide", org=None)  # not this org's
        self.assertEqual(run("incidents", self.org)["status"], "manual")
        inc = Incident.objects.create(org=self.org, title="Leaked link", status="investigating")
        self.assertEqual(run("incidents", self.org)["status"], "pass")
        Incident.objects.filter(pk=inc.pk).update(created_at=timezone.now() - timedelta(days=45))
        self.assertEqual(run("incidents", self.org)["status"], "fail")
        Incident.objects.filter(pk=inc.pk).update(status="resolved", resolved_at=timezone.now())
        self.assertEqual(run("incidents", self.org)["status"], "pass")


class AIChecks(ComplianceBase):
    def test_ai_approvals(self):
        from actions.models import ToolDefinition
        from channels.models import CustomerSettings

        self.assertEqual(run("ai_approvals", self.org)["status"], "pass")
        settings_row = CustomerSettings.objects.create(org=self.org, auto_reply=True)
        self.assertEqual(run("ai_approvals", self.org)["status"], "manual")
        settings_row.delete()
        ToolDefinition.objects.update_or_create(key="tasks.create", defaults={"perm_key": "task.write", "risk": "write", "requires_approval": False})
        self.assertEqual(run("ai_approvals", self.org)["status"], "fail")

    def test_ai_data_policy(self):
        self.assertEqual(run("ai_data_policy", self.org)["status"], "fail")
        OrgPolicy.objects.create(org=self.org, inference_scope=OrgPolicy.SCOPE_PRIVATE)
        result = run("ai_data_policy", self.org)
        self.assertEqual(result["status"], "pass")
        self.assertIn("self-hosted only", str(result["evidence"]))

    @override_settings(EXTERNAL_AGENT_ALLOWED_HOSTS="agents.example.com")
    def test_external_agents(self):
        from platform_api.models import ExternalAgentHost, ExternalAgentServer

        self.assertEqual(run("external_agents", self.org)["status"], "not_applicable")
        server = ExternalAgentServer.objects.create(org=self.org, name="Agent", url="https://agents.example.com/mcp", allowed=True, tools_hash="a" * 64, tools_approved_hash="a" * 64)
        self.assertEqual(run("external_agents", self.org)["status"], "fail")  # host not on the org allowlist
        ExternalAgentHost.objects.create(org=self.org, host="agents.example.com", added_by=self.users["owner"])
        self.assertEqual(run("external_agents", self.org)["status"], "pass")
        server.tools_hash = "b" * 64  # the server changed its tools
        server.save()
        self.assertEqual(run("external_agents", self.org)["status"], "fail")


class GovernanceChecks(ComplianceBase):
    def test_policies_acknowledged(self):
        from organizations.models import OrgMembership

        self.assertEqual(run("policies_acknowledged", self.org)["status"], "fail")
        month_ago = timezone.now() - timedelta(days=30)
        OrgMembership.objects.filter(org=self.org).update(created_at=month_ago)
        policy = Policy.objects.create(org=self.org, template="access-control", title="Access control")
        version = PolicyVersion.objects.create(policy=policy, version=1, body="x", sha256="0" * 64, published_at=month_ago)
        PolicyAck.objects.create(version=version, user=self.users["owner"])
        self.assertEqual(run("policies_acknowledged", self.org)["status"], "fail")
        for user in self.users.values():
            PolicyAck.objects.get_or_create(version=version, user=user)
        self.assertEqual(run("policies_acknowledged", self.org)["status"], "pass")
        # A new member has 14 days to acknowledge.
        from django.contrib.auth.hashers import make_password
        from users.models import User

        newcomer = User.objects.create(email="c-new@example.com", password_hash=make_password("x"))
        joined = OrgMembership.objects.create(org=self.org, user=newcomer, employment_status="active")
        self.assertEqual(run("policies_acknowledged", self.org)["status"], "pass")
        OrgMembership.objects.filter(pk=joined.pk).update(created_at=month_ago)
        self.assertEqual(run("policies_acknowledged", self.org)["status"], "fail")  # 5 of 6 overdue pairs done < 90%
        PolicyAck.objects.create(version=version, user=newcomer)
        # A new version needs new acknowledgements once it is 14 days old.
        v2 = PolicyVersion.objects.create(policy=policy, version=2, body="y", sha256="1" * 64)
        self.assertEqual(run("policies_acknowledged", self.org)["status"], "pass")
        PolicyVersion.objects.filter(pk=v2.pk).update(published_at=timezone.now() - timedelta(days=15))
        self.assertEqual(run("policies_acknowledged", self.org)["status"], "fail")

    def test_trust_center(self):
        self.assertEqual(run("trust_center", self.org)["status"], "manual")
        TrustCenter.objects.create(org=self.org, slug="acme", published=True)
        self.assertEqual(run("trust_center", self.org)["status"], "pass")

    def test_a_broken_check_becomes_manual(self):
        with patch.dict(checks.CHECKS, {"audit_log": lambda ctx: 1 / 0}), self.assertLogs("compliance.checks", "WARNING"):
            result = checks.run_check("audit_log", self.org)
        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["evidence"][0]["value"], "ZeroDivisionError")


class ReadinessRules(ComplianceBase):
    def control(self, framework, cid):
        return next(r for r in readiness.evaluate(self.org, framework=framework) if r["id"] == cid)

    def test_catalog_counts(self):
        from compliance import catalog

        iso = catalog.controls(catalog.ISO)
        self.assertEqual(len(iso), 93)
        themes = {t: sum(1 for c in iso if c["group"] == t) for t in "5678"}
        self.assertEqual(themes, {"5": 37, "6": 8, "7": 14, "8": 34})
        common = [c for c in catalog.controls(catalog.SOC2) if c["id"].startswith("CC")]
        self.assertEqual(len(common), 33)
        for c in catalog.CONTROLS:
            for key in c["checks"]:
                self.assertIn(key, checks.CHECKS, c["id"])

    def test_attestation_cannot_hide_a_failing_check(self):
        ControlAttestation.objects.create(org=self.org, framework="iso27001", control_id="8.15", status="pass", note="We look at logs")
        self.assertEqual(self.control("iso27001", "8.15")["status"], "fail")  # no audit events yet
        audit(self.users["admin"], "x", org=self.org)
        self.assertEqual(self.control("iso27001", "8.15")["status"], "pass")

    def test_manual_controls_need_an_attestation(self):
        self.assertEqual(self.control("iso27001", "7.1")["status"], "manual")
        ControlAttestation.objects.create(org=self.org, framework="iso27001", control_id="7.1", status="not_applicable", note="Fully remote, no office")
        self.assertEqual(self.control("iso27001", "7.1")["status"], "not_applicable")
        ControlAttestation.objects.filter(org=self.org).update(status="pass")
        self.assertEqual(self.control("iso27001", "7.1")["status"], "pass")

    def test_summary_percent_ignores_not_applicable(self):
        rows = [{"framework": "iso27001", "group": "7", "group_name": "Physical", "status": s} for s in ("pass", "fail", "not_applicable", "manual")]
        summary = readiness.summarize(rows)[0]
        self.assertEqual(summary["readiness"], 33)
        self.assertEqual(summary["counts"]["total"], 4)
