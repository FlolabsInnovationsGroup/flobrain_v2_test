"""Automated checks. Each reads real data for one org and returns a result:

``{"key", "title", "status", "summary", "evidence": [{"label", "value", "link"?}]}``

``status`` is ``pass``, ``fail``, ``manual`` (FloBrain can't tell; a person attests) or ``not_applicable``.
Evidence never contains secrets: for keys it says only whether they are set. ``link`` is a path inside the
workspace (``/w/<org>/<link>``) where a person can see the underlying data.
"""

from __future__ import annotations

import os
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

PASS, FAIL, MANUAL, NA = "pass", "fail", "manual", "not_applicable"
STATUSES = (PASS, FAIL, MANUAL, NA)

TITLES = {
    "sso_enforced": "Single sign-on is enforced",
    "scim": "SCIM provisioning is on",
    "owner_mfa": "Owners and admins use MFA",
    "admin_count": "Few people hold admin rights",
    "dormant_members": "No dormant members",
    "pending_requests": "No old permission requests",
    "leavers_access": "People who left hold no extra access",
    "audit_log": "Audit log is on and exportable",
    "retention_policy": "Retention policy is set",
    "encryption": "Encryption keys are configured",
    "ai_approvals": "AI actions need a person's approval",
    "ai_data_policy": "AI and data policy is saved",
    "external_agents": "Outside AI agents are allowlisted",
    "incidents": "Incidents are recorded",
    "backup_export": "An org export ran recently",
    "data_region": "Data region is pinned",
    "access_review_recent": "Access review done in the last 90 days",
    "policies_acknowledged": "Members acknowledged the policies",
    "trust_center": "Trust page is published",
}


class Ctx:
    """Shared, lazily loaded facts for one run of every check."""

    def __init__(self, org, now=None):
        from compliance.models import ComplianceProfile

        self.org = org
        self.now = now or timezone.now()
        self.profile = ComplianceProfile.objects.filter(org=org).first() or ComplianceProfile(org=org)
        self._members = None

    @property
    def members(self):
        if self._members is None:
            from organizations.models import OrgMembership

            self._members = list(OrgMembership.objects.filter(org=self.org).select_related("user"))
        return self._members

    def active(self):
        return [m for m in self.members if m.employment_status == "active"]


def _result(key, status, summary, evidence=None):
    return {"key": key, "title": TITLES.get(key, key), "status": status, "summary": summary, "evidence": evidence or []}


def _ev(label, value, link=None):
    row = {"label": label, "value": value}
    if link:
        row["link"] = link
    return row


def _name(user):
    return user.username or user.email.split("@")[0]


# --- identity and access ---------------------------------------------------------------------------


def check_sso_enforced(ctx):
    from sso.models import SSOConnection

    conn = SSOConnection.objects.filter(org=ctx.org).first()
    if conn is None or not conn.enabled:
        return _result("sso_enforced", FAIL, "Single sign-on is not set up. People sign in with passwords.", [_ev("SSO", "off", "settings/sso")])
    evidence = [
        _ev("Protocol", conn.protocol.upper(), "settings/sso"),
        _ev("Verified domains", str(len(conn.verified_domains or []))),
        _ev("Enforced", "yes" if conn.enforced else "no"),
    ]
    if not conn.enforced or not conn.verified_domains:
        return _result("sso_enforced", FAIL, "SSO is on, but password sign-in still works for your domains.", evidence)
    return _result("sso_enforced", PASS, "SSO is on and enforced for your verified domains. The owner keeps a break-glass sign-in.", evidence)


def check_scim(ctx):
    from sso.models import SCIMToken

    tokens = SCIMToken.objects.filter(org=ctx.org, revoked_at__isnull=True)
    count = tokens.count()
    if count:
        last = tokens.order_by("-created_at").first()
        return _result("scim", PASS, "SCIM is on: your identity provider adds and removes people.", [
            _ev("Active SCIM tokens", str(count), "settings/sso"), _ev("Newest token ends in", f"…{last.last4}")])
    return _result("scim", MANUAL, "SCIM is off. Removing people who leave is a manual step; record it in access reviews.", [_ev("Active SCIM tokens", "0", "settings/sso")])


def check_owner_mfa(ctx):
    from sso.models import SSOConnection

    privileged = [m for m in ctx.active() if m.org_role in ("owner", "admin")]
    conn = SSOConnection.objects.filter(org=ctx.org, enabled=True, enforced=True).first()
    evidence = [_ev("Owners and admins", str(len(privileged)), "directory")]
    if conn is not None:
        evidence.append(_ev("MFA", "delegated to your identity provider"))
        return _result("owner_mfa", MANUAL, "Not tracked in FloBrain. SSO is enforced, so attach your identity provider's MFA report.", evidence)
    evidence.append(_ev("MFA", "not tracked"))
    return _result("owner_mfa", MANUAL, "Not tracked: FloBrain accounts have no MFA setting. Enforce SSO with MFA at your identity provider.", evidence)


def check_admin_count(ctx):
    active = ctx.active()
    privileged = [m for m in active if m.org_role in ("owner", "admin")]
    limit = max(3, -(-len(active) // 5))  # at most 20% of members, never fewer than 3
    evidence = [
        _ev("Owners", str(sum(1 for m in privileged if m.org_role == "owner")), "directory"),
        _ev("Admins", str(sum(1 for m in privileged if m.org_role == "admin"))),
        _ev("Active members", str(len(active))),
        _ev("Limit used", str(limit)),
    ]
    if len(privileged) > limit:
        return _result("admin_count", FAIL, f"{len(privileged)} people hold owner or admin rights. Keep it to {limit} or fewer.", evidence)
    return _result("admin_count", PASS, f"{len(privileged)} people hold owner or admin rights.", evidence)


def check_dormant_members(ctx):
    days = int(ctx.profile.dormant_days or 90)
    cutoff = ctx.now - timedelta(days=days)
    dormant = []
    for m in ctx.active():
        last = m.user.last_active
        if (last is None and m.created_at < cutoff) or (last is not None and last < cutoff):
            dormant.append(m)
    evidence = [_ev("Window", f"{days} days")]
    evidence += [_ev(_name(m.user), (m.user.last_active.date().isoformat() if m.user.last_active else "never signed in"), f"directory/{m.user_id}") for m in dormant[:20]]
    if dormant:
        return _result("dormant_members", FAIL, f"{len(dormant)} active members have not signed in for {days} days.", evidence)
    return _result("dormant_members", PASS, f"Every active member signed in within {days} days.", evidence)


def check_pending_requests(ctx):
    from organizations.models import PermissionRequest

    days = int(ctx.profile.request_age_days or 14)
    old = PermissionRequest.objects.filter(org=ctx.org, status=PermissionRequest.STATUS_PENDING, created_at__lt=ctx.now - timedelta(days=days))
    count = old.count()
    evidence = [_ev("Older than", f"{days} days"), _ev("Waiting", str(count), "settings/access")]
    if count:
        return _result("pending_requests", FAIL, f"{count} permission requests have waited more than {days} days for a decision.", evidence)
    return _result("pending_requests", PASS, f"No permission request has waited more than {days} days.", evidence)


def check_leavers_access(ctx):
    from organizations.models import PermissionGrant

    gone = [m.user_id for m in ctx.members if m.employment_status in ("paused", "terminated", "offboarding", "graduated")]
    grants = PermissionGrant.objects.filter(org=ctx.org, grantee_id__in=gone, revoked_at__isnull=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=ctx.now))
    count = grants.count()
    evidence = [_ev("People not active", str(len(gone)), "directory"), _ev("Grants still open", str(count), "settings/access")]
    if count:
        return _result("leavers_access", FAIL, f"{count} permission grants still belong to people who are no longer active.", evidence)
    return _result("leavers_access", PASS, "People who left or are paused hold no open permission grants.", evidence)


def check_access_review_recent(ctx):
    from compliance.models import AccessReview

    days = int(ctx.profile.review_interval_days or 90)
    done = AccessReview.objects.filter(org=ctx.org, status=AccessReview.COMPLETED, completed_at__gte=ctx.now - timedelta(days=days)).order_by("-completed_at").first()
    if done:
        return _result("access_review_recent", PASS, f"\"{done.name}\" was completed on {done.completed_at.date().isoformat()}.", [
            _ev("Last completed", done.completed_at.date().isoformat(), f"settings/compliance?tab=reviews&review={done.id}")])
    running = AccessReview.objects.filter(org=ctx.org, status=AccessReview.OPEN).first()
    if running:
        open_items = running.items.filter(decision="pending").count()
        return _result("access_review_recent", FAIL, f"\"{running.name}\" is in progress with {open_items} items left.", [
            _ev("In progress", running.name, f"settings/compliance?tab=reviews&review={running.id}")])
    return _result("access_review_recent", FAIL, f"No access review was completed in the last {days} days.", [_ev("Last completed", "never", "settings/compliance?tab=reviews")])


# --- logging, data and keys ------------------------------------------------------------------------


def check_audit_log(ctx):
    from organizations.models import AuditEvent

    recent = AuditEvent.objects.filter(org=ctx.org, created_at__gte=ctx.now - timedelta(days=30))
    count = recent.count()
    evidence = [_ev("Events in 30 days", str(count), "settings/audit"), _ev("Export", "evidence package (CSV) and the audit API")]
    if not count:
        return _result("audit_log", FAIL, "No audit events in the last 30 days.", evidence)
    first = AuditEvent.objects.filter(org=ctx.org).order_by("created_at").values_list("created_at", flat=True).first()
    evidence.append(_ev("Kept since", first.date().isoformat() if first else ""))
    return _result("audit_log", PASS, "Admin and access changes are recorded and can be exported.", evidence)


def check_retention_policy(ctx):
    from privacy.models import RetentionPolicy

    policy = RetentionPolicy.objects.filter(org=ctx.org).first()
    fields = ("messages_days", "recordings_days", "transcripts_days", "time_entries_days")
    set_fields = {f: getattr(policy, f) for f in fields if policy is not None and getattr(policy, f)}
    if not set_fields:
        return _result("retention_policy", FAIL, "No retention period is set, so data is kept forever.", [_ev("Retention", "not set", "settings/retention")])
    evidence = [_ev(f.replace("_days", "").replace("_", " ").capitalize(), f"{v} days", "settings/retention") for f, v in set_fields.items()]
    if policy.last_run_at:
        evidence.append(_ev("Last run", policy.last_run_at.date().isoformat()))
    return _result("retention_policy", PASS, "Retention periods are set and applied daily.", evidence)


def _aes_master_key_set() -> bool:
    raw = (os.environ.get("AES_MASTER_KEY") or "").strip()
    if len(raw) != 64:
        return False
    try:
        return bytes.fromhex(raw) != b"\x00" * 32
    except ValueError:
        return False


def check_encryption(ctx):
    from integrations import crypto

    creds = crypto.is_configured()
    master = _aes_master_key_set()
    evidence = [
        _ev("CREDENTIALS_ENCRYPTION_KEY", "set (AES-256-GCM)" if creds else "not set"),
        _ev("AES_MASTER_KEY", "set" if master else "not set"),
        _ev("Key version", str(crypto.current_key_version())),
    ]
    if creds and master:
        return _result("encryption", PASS, "Stored secrets and memory archives are encrypted with configured keys.", evidence)
    return _result("encryption", FAIL, "An encryption key is missing on this server. Ask whoever runs FloBrain to set it.", evidence)


# --- AI governance ---------------------------------------------------------------------------------


def check_ai_approvals(ctx):
    from actions.models import ToolDefinition
    from actions.registry import TOOLS

    unsafe = [k for k, t in TOOLS.items() if t.get("risk") != "read" and t.get("requires_approval") is False]
    unsafe += list(ToolDefinition.objects.filter(requires_approval=False).exclude(risk="read").values_list("key", flat=True))
    writes = sum(1 for t in TOOLS.values() if t.get("risk") != "read")
    evidence = [_ev("Write actions", str(writes), "approvals"), _ev("Without approval", str(len(set(unsafe))))]
    auto_reply = False
    try:
        from channels.models import CustomerSettings

        auto_reply = CustomerSettings.objects.filter(org=ctx.org, auto_reply=True).exists()
    except Exception:  # noqa: BLE001 - the channels app is optional for this check
        auto_reply = False
    if unsafe:
        return _result("ai_approvals", FAIL, "Some AI actions run without a person's approval.", evidence)
    if auto_reply:
        evidence.append(_ev("Customer buddy", "answers without approval (an admin allowed it)", "settings/channels"))
        return _result("ai_approvals", MANUAL, "AI actions need approval, but an admin let the customer buddy reply on its own. Record why.", evidence)
    return _result("ai_approvals", PASS, "Every AI action that writes or sends waits for a person's approval.", evidence)


def check_ai_data_policy(ctx):
    from organizations.models import OrgPolicy

    policy = OrgPolicy.objects.filter(org=ctx.org).first()
    if policy is None:
        return _result("ai_data_policy", FAIL, "No AI and data policy is saved. The default lets external AI models see data.", [_ev("Policy", "not saved", "settings/ai-policy")])
    evidence = [
        _ev("AI models", "self-hosted only" if policy.inference_scope == OrgPolicy.SCOPE_PRIVATE else "external allowed", "settings/ai-policy"),
        _ev("PII redaction", policy.pii_redaction),
    ]
    return _result("ai_data_policy", PASS, "The owner saved an AI and data policy.", evidence)


def check_external_agents(ctx):
    from platform_api import external_agents
    from platform_api.models import ExternalAgentServer

    servers = list(ExternalAgentServer.objects.filter(org=ctx.org, allowed=True))
    hosts = external_agents.org_hosts(ctx.org)
    evidence = [_ev("Allowed hosts", str(len(hosts)), "settings/external-agents"), _ev("Connected agents", str(len(servers)))]
    if not servers:
        return _result("external_agents", NA, "No outside AI agents are connected.", evidence)
    from urllib.parse import urlparse

    off_list = [s for s in servers if not external_agents.host_allowed(ctx.org, urlparse(s.url).hostname or "")]
    unapproved = [s for s in servers if not s.tools_approved]
    for s in (off_list + unapproved)[:10]:
        evidence.append(_ev(s.name, "host not on the allowlist" if s in off_list else "tool list changed, not approved"))
    if off_list or unapproved:
        return _result("external_agents", FAIL, "An outside agent is off the allowlist or has tools the owner did not approve.", evidence)
    return _result("external_agents", PASS, "Every outside agent is on the owner's allowlist with an approved tool list.", evidence)


# --- operations ------------------------------------------------------------------------------------


def check_incidents(ctx):
    from platform_api.models import Incident

    rows = Incident.objects.filter(org=ctx.org)
    total = rows.count()
    stale = rows.exclude(status="resolved").filter(created_at__lt=ctx.now - timedelta(days=30)).count()
    evidence = [_ev("Incidents recorded", str(total), "settings/incidents"), _ev("Open for over 30 days", str(stale))]
    if not total:
        return _result("incidents", MANUAL, "No incidents recorded. If you had none, attest that here.", evidence)
    if stale:
        return _result("incidents", FAIL, f"{stale} incidents have been open for more than 30 days.", evidence)
    last = rows.order_by("-created_at").first()
    evidence.append(_ev("Latest", last.created_at.date().isoformat()))
    return _result("incidents", PASS, "Incidents are recorded and followed to resolution.", evidence)


def check_backup_export(ctx):
    from exports.models import MemoryExport

    last = MemoryExport.objects.filter(org=ctx.org, status=MemoryExport.STATUS_SUCCEEDED).order_by("-finished_at", "-created_at").first()
    if last is None:
        return _result("backup_export", FAIL, "No org export has run. Database backups are run by whoever hosts FloBrain.", [_ev("Last export", "never", "settings/export")])
    when = last.finished_at or last.created_at
    evidence = [_ev("Last export", when.date().isoformat(), "settings/export")]
    if when < ctx.now - timedelta(days=30):
        return _result("backup_export", FAIL, "The last org export is more than 30 days old.", evidence)
    return _result("backup_export", PASS, "An org export ran in the last 30 days.", evidence)


def _einvoice_region(org) -> str:
    """Read an e-invoicing data residency setting softly, if that app has one."""
    try:
        from django.apps import apps

        for model in apps.get_app_config("einvoice").get_models():
            names = {f.name for f in model._meta.get_fields()}
            field = next((n for n in ("residency", "data_region", "residency_region") if n in names), None)
            if field and "org" in names:
                row = model.objects.filter(org=org).first()
                value = getattr(row, field, "") if row is not None else ""
                if value:
                    return str(value)[:40]
    except Exception:  # noqa: BLE001 - optional source
        return ""
    return ""


def check_data_region(ctx):
    from organizations.models import OrgPolicy

    policy = OrgPolicy.objects.filter(org=ctx.org).first()
    region = (policy.data_region if policy else "") or ""
    einvoice = _einvoice_region(ctx.org)
    evidence = [_ev("Data region", region or "not pinned", "settings/ai-policy")]
    if einvoice:
        evidence.append(_ev("E-invoice residency", einvoice, "einvoices"))
    if region or einvoice:
        return _result("data_region", PASS, f"Data region is pinned to {region or einvoice}.", evidence)
    return _result("data_region", FAIL, "No data region is pinned.", evidence)


ACK_GRACE_DAYS = 14


def check_policies_acknowledged(ctx):
    """Each active member acknowledges each current version within 14 days of its publication or of joining."""
    from compliance.models import Policy, PolicyAck

    policies = list(Policy.objects.filter(org=ctx.org, requires_ack=True).prefetch_related("versions"))
    current = [p.versions.all()[0] for p in policies if p.versions.all()]
    if not current:
        return _result("policies_acknowledged", FAIL, "No policy is published for members to acknowledge.", [_ev("Published policies", "0", "settings/compliance?tab=policies")])
    active = {m.user_id: m.created_at for m in ctx.active()}
    acked = set(PolicyAck.objects.filter(version__in=current, user_id__in=list(active)).values_list("version_id", "user_id"))
    grace = timedelta(days=ACK_GRACE_DAYS)
    due = [(v.id, uid) for v in current for uid, joined in active.items() if max(v.published_at, joined) + grace <= ctx.now]
    due_done = sum(1 for pair in due if pair in acked)
    total = len(current) * len(active)
    share = (due_done / len(due)) if due else 1.0
    evidence = [
        _ev("Published policies", str(len(current)), "settings/compliance?tab=policies"),
        _ev("Acknowledged", f"{len(acked)} of {total}"),
        _ev("Overdue", str(len(due) - due_done)),
        _ev("Time to acknowledge", f"{ACK_GRACE_DAYS} days"),
    ]
    if share >= 0.9:
        return _result("policies_acknowledged", PASS, f"{len(acked)} of {total} acknowledgements are in; {len(due) - due_done} are overdue.", evidence)
    return _result("policies_acknowledged", FAIL, f"{len(due) - due_done} acknowledgements are more than {ACK_GRACE_DAYS} days overdue.", evidence)


def check_trust_center(ctx):
    from compliance.models import TrustCenter

    trust = TrustCenter.objects.filter(org=ctx.org).first()
    if trust and trust.published:
        return _result("trust_center", PASS, "Your trust page is public.", [_ev("Trust page", f"/trust/{trust.slug}", "settings/compliance?tab=trust")])
    return _result("trust_center", MANUAL, "Your trust page is not published. Share security information another way, or publish it.", [_ev("Trust page", "not published", "settings/compliance?tab=trust")])


CHECKS = {
    "sso_enforced": check_sso_enforced,
    "scim": check_scim,
    "owner_mfa": check_owner_mfa,
    "admin_count": check_admin_count,
    "dormant_members": check_dormant_members,
    "pending_requests": check_pending_requests,
    "leavers_access": check_leavers_access,
    "audit_log": check_audit_log,
    "retention_policy": check_retention_policy,
    "encryption": check_encryption,
    "ai_approvals": check_ai_approvals,
    "ai_data_policy": check_ai_data_policy,
    "external_agents": check_external_agents,
    "incidents": check_incidents,
    "backup_export": check_backup_export,
    "data_region": check_data_region,
    "access_review_recent": check_access_review_recent,
    "policies_acknowledged": check_policies_acknowledged,
    "trust_center": check_trust_center,
}


def run_check(key, org, ctx=None):
    ctx = ctx or Ctx(org)
    try:
        return CHECKS[key](ctx)
    except Exception as exc:  # noqa: BLE001 - one broken source must not hide the others
        import logging

        logging.getLogger(__name__).warning("compliance check %s failed: %s", key, type(exc).__name__)
        return _result(key, MANUAL, "This check could not run. Check it by hand.", [_ev("Error", type(exc).__name__)])


def run_all(org, now=None) -> dict:
    ctx = Ctx(org, now)
    return {key: run_check(key, org, ctx) for key in CHECKS}
