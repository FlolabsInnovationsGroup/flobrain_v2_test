"""Evidence packages: one ZIP an auditor can read, for a period.

Contents (JSON and CSV, UTF-8):

- ``controls.json`` / ``controls.csv``: every control, its status and where the status came from
- ``checks.json``: the automated checks with their evidence pointers
- ``audit_log.csv``: the audit log for the period (secret-looking payload fields removed)
- ``access_reviews.json`` / ``access_review_items.csv``: reviews created or completed in the period
- ``policies.json`` / ``policy_acknowledgements.csv``: published versions with SHA-256 and who acknowledged
- ``config_snapshot.json``: security settings (SSO, SCIM, retention, AI policy, flags, key presence), no secrets
- ``README.txt``
- ``manifest.json``: every file above with its size and SHA-256 (the manifest itself is not listed)

The ZIP goes to private storage under ``compliance/<org>/<package>/``. It is downloadable for 7 days by people
with ``compliance.manage``, then deleted.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from datetime import timedelta

from django.utils import timezone

from compliance import checks, readiness
from compliance.models import AccessReview, AccessReviewItem, EvidencePackage, Policy, PolicyAck, PolicyVersion

VALID_DAYS = 7
MAX_AUDIT_ROWS = 50_000
SECRET_KEYS = re.compile(r"(secret|token|password|passwd|api[_-]?key|private[_-]?key|dsn|ciphertext|credential|authorization|cookie|signature)", re.I)
SECRET_VALUES = re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{16,}|\bxox[abpr]-[A-Za-z0-9-]{10,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b)")
GENERATOR = "FloBrain compliance evidence v1"


def scrub(value):
    """Remove fields whose name looks secret, and values that look like key material."""
    if isinstance(value, dict):
        return {k: ("[removed]" if SECRET_KEYS.search(str(k)) else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and SECRET_VALUES.search(value):
        return "[removed]"
    return value


def _csv(header, rows) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return out.getvalue().encode("utf-8")


def _cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text  # no formulas when opened in a spreadsheet


def _json(data) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _name(user):
    return (user.username or user.email) if user else ""


def config_snapshot(org):
    from organizations.models import OrgMembership, OrgPolicy
    from privacy.models import RetentionPolicy
    from sso.models import SCIMToken, SSOConnection

    sso = SSOConnection.objects.filter(org=org).first()
    retention = RetentionPolicy.objects.filter(org=org).first()
    policy = OrgPolicy.objects.filter(org=org).first()
    roles = {}
    for role, status in OrgMembership.objects.filter(org=org).values_list("org_role", "employment_status"):
        roles.setdefault(status, {}).setdefault(role, 0)
        roles[status][role] += 1
    from integrations import crypto

    enc = {"stored_data_encryption": "set" if crypto.is_configured() else "not set",
           "memory_archive_encryption": "set" if checks._aes_master_key_set() else "not set",
           "key_version": crypto.current_key_version()}
    try:
        from platform_api.models import ExternalAgentHost, ExternalAgentServer

        agents = {"allowed_hosts": sorted(ExternalAgentHost.objects.filter(org=org).values_list("host", flat=True)),
                  "connected": ExternalAgentServer.objects.filter(org=org, allowed=True).count()}
    except Exception:  # noqa: BLE001
        agents = {}
    from compliance.models import TrustCenter

    trust = TrustCenter.objects.filter(org=org).first()
    return scrub({
        "org": {"id": str(org.id), "name": org.name, "slug": org.slug},
        "flags": {k: bool(v) for k, v in ((org.settings or {}).get("flags") or {}).items()},
        "members_by_status_and_role": roles,
        "sso": None if sso is None else {
            "protocol": sso.protocol, "enabled": sso.enabled, "enforced": sso.enforced,
            "verified_domains": list(sso.verified_domains or []), "updated_at": sso.updated_at,
        },
        "scim": {"active": SCIMToken.objects.filter(org=org, revoked_at__isnull=True).count()},
        "retention_days": None if retention is None else {
            "messages": retention.messages_days, "recordings": retention.recordings_days,
            "transcripts": retention.transcripts_days, "time_entries": retention.time_entries_days,
            "last_run_at": retention.last_run_at,
        },
        "ai_policy": None if policy is None else {"inference_scope": policy.inference_scope, "pii_redaction": policy.pii_redaction, "data_region": policy.data_region},
        "encryption": enc,  # presence only, never the keys
        "external_agents": agents,
        "trust_center": None if trust is None else {"published": trust.published, "slug": trust.slug, "sections": trust.sections},
    })


def _audit_rows(org, start, end):
    from organizations.models import AuditEvent

    qs = AuditEvent.objects.filter(org=org, created_at__gte=start, created_at__lt=end).select_related("actor", "impersonator").order_by("created_at")
    for e in qs[:MAX_AUDIT_ROWS]:
        yield [e.created_at.isoformat(), _name(e.actor), e.actor.email if e.actor_id and e.actor else "", _name(e.impersonator),
               e.action, e.target_type, e.target_id, e.ip or "", json.dumps(scrub(e.payload or {}), sort_keys=True, default=str)]


def _reviews(org, start, end):
    from django.db.models import Q

    reviews = list(AccessReview.objects.filter(org=org).filter(Q(created_at__gte=start, created_at__lt=end) | Q(completed_at__gte=start, completed_at__lt=end)))
    from compliance import reviews as svc

    summary = [{**svc.review_payload(r), "report": svc.report(r)} for r in reviews]
    items = AccessReviewItem.objects.filter(review__in=reviews).select_related("review", "subject", "reviewer", "decided_by").order_by("review__created_at", "position")
    rows = [[i.review.name, i.subject.email, i.kind, i.label, _name(i.reviewer) or "admins", i.decision, json.dumps(i.change_to, sort_keys=True),
             _name(i.decided_by), i.decided_at.isoformat() if i.decided_at else "", i.applied_at.isoformat() if i.applied_at else "", i.note] for i in items]
    return summary, rows


def _policies(org):
    versions = PolicyVersion.objects.filter(policy__org=org).select_related("policy", "published_by").order_by("policy__title", "version")
    listing = [{"policy": v.policy.title, "template": v.policy.template, "version": v.version, "sha256": v.sha256,
                "published_at": v.published_at, "published_by": _name(v.published_by)} for v in versions]
    acks = PolicyAck.objects.filter(version__policy__org=org).select_related("version__policy", "user").order_by("version__policy__title", "version__version", "acknowledged_at")
    rows = [[a.version.policy.title, a.version.version, a.version.sha256, a.user.email, a.acknowledged_at.isoformat()] for a in acks]
    return listing, rows, Policy.objects.filter(org=org).count()


README = """FloBrain evidence package
=========================

Organization: {org}
Period: {start} to {end} (UTC)
Generated: {generated} by {by}

This package shows readiness for SOC 2 and ISO/IEC 27001:2022. It is not a certification or an audit opinion.
Control statuses come from automated checks on FloBrain data and from attestations people made in FloBrain.

Check integrity: manifest.json lists the SHA-256 of every other file. On a computer:
  sha256sum controls.json     (Linux)
  shasum -a 256 controls.json (macOS)

No secrets are included: the configuration snapshot says only whether keys are set.
"""


def build(org, actor, start, end, now=None):
    """Return (zip bytes, manifest dict)."""
    now = now or timezone.now()
    results = checks.run_all(org, now)
    rows = readiness.evaluate(org, results)
    summary = readiness.summarize(rows)
    reviews_json, review_rows = _reviews(org, start, end)
    policies_json, ack_rows, policy_count = _policies(org)
    files = {
        "controls.json": _json({"summary": summary, "controls": [{k: r[k] for k in ("framework", "id", "group_name", "name", "status", "source", "check_results", "attestation")} for r in rows]}),
        "controls.csv": _csv(["framework", "control", "group", "name", "status", "source", "checks", "attestation_note", "attested_by", "attested_at"], [
            [r["framework"], r["id"], r["group_name"], r["name"], r["status"], r["source"],
             "; ".join(f"{c['key']}={c['status']}" for c in r["check_results"]),
             (r["attestation"] or {}).get("note", ""), (r["attestation"] or {}).get("by", ""), (r["attestation"] or {}).get("at", "")] for r in rows]),
        "checks.json": _json(scrub(results)),
        "audit_log.csv": _csv(["at", "actor", "actor_email", "impersonator", "action", "target_type", "target_id", "ip", "payload"], _audit_rows(org, start, end)),
        "access_reviews.json": _json(reviews_json),
        "access_review_items.csv": _csv(["review", "person", "kind", "access", "reviewer", "decision", "change_to", "decided_by", "decided_at", "applied_at", "note"], review_rows),
        "policies.json": _json({"installed": policy_count, "versions": policies_json}),
        "policy_acknowledgements.csv": _csv(["policy", "version", "sha256", "person", "acknowledged_at"], ack_rows),
        "config_snapshot.json": _json(config_snapshot(org)),
        "README.txt": README.format(org=org.name, start=start.isoformat(), end=end.isoformat(), generated=now.isoformat(), by=_name(actor)).encode("utf-8"),
    }
    manifest = {
        "generator": GENERATOR, "org": {"id": str(org.id), "name": org.name},
        "period": {"start": start.isoformat(), "end": end.isoformat()}, "generated_at": now.isoformat(),
        "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", _json(manifest))
    return buffer.getvalue(), manifest


def storage_key(package) -> str:
    return f"compliance/{package.org_id}/{package.id}/evidence.zip"


def generate(org, actor, start, end, request=None):
    from content_studio import storage
    from organizations.services.core import audit

    package = EvidencePackage.objects.create(org=org, period_start=start, period_end=end, created_by=actor)
    try:
        data, manifest = build(org, actor, start, end)
        key = storage_key(package)
        with tempfile.SpooledTemporaryFile(max_size=64 << 20) as tmp:
            tmp.write(data)
            tmp.seek(0)
            if not storage.put_file(key, tmp, "application/zip"):
                raise RuntimeError("storage_not_configured")
    except Exception as exc:  # noqa: BLE001 - record only the failure class
        package.status, package.error = EvidencePackage.FAILED, type(exc).__name__[:200]
        package.save(update_fields=["status", "error"])
        return package
    package.status, package.storage_key, package.size_bytes = EvidencePackage.READY, key, len(data)
    package.sha256, package.manifest = hashlib.sha256(data).hexdigest(), manifest
    package.expires_at = timezone.now() + timedelta(days=VALID_DAYS)
    package.save(update_fields=["status", "storage_key", "size_bytes", "sha256", "manifest", "expires_at"])
    audit(actor, "compliance.evidence.create", target=package, org=org, request=request,
          payload={"period_start": start.isoformat(), "period_end": end.isoformat(), "sha256": package.sha256, "files": len(manifest["files"])})
    return package


def expire(now=None):
    """Delete stored packages past their 7 days. Returns how many were removed."""
    from content_studio import storage

    now = now or timezone.now()
    n = 0
    for package in EvidencePackage.objects.filter(status=EvidencePackage.READY, expires_at__lt=now):
        storage.delete(package.storage_key)
        package.status, package.storage_key = EvidencePackage.EXPIRED, ""
        package.save(update_fields=["status", "storage_key"])
        n += 1
    return n


def package_payload(package):
    return {
        "id": str(package.id), "status": package.status,
        "period_start": package.period_start.isoformat(), "period_end": package.period_end.isoformat(),
        "size_bytes": package.size_bytes, "sha256": package.sha256, "files": (package.manifest or {}).get("files", []),
        "created_at": package.created_at.isoformat(), "expires_at": package.expires_at.isoformat() if package.expires_at else None,
        "created_by": _name(package.created_by) if package.created_by_id else "", "error": package.error,
    }
