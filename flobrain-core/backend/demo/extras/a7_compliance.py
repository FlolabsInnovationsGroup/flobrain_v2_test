"""Compliance (M7) demo: a realistic readiness mix (about 70% of controls passing), one access review in
progress with a few decisions made, a completed review from last quarter, two published policies everyone
acknowledged plus one draft, an evidence package, and a published trust page at /trust/demo that uses
FloBrain's own example content (subprocessors and all). Attestation notes start with "Demo:"."""

from datetime import timedelta

TARGET = 0.70

NOTES = {
    ("soc2", "CC1"): "Demo: leadership reviewed the code of conduct and org chart in September.",
    ("soc2", "CC2"): "Demo: security updates go out in the monthly all-hands notes.",
    ("soc2", "CC3"): "Demo: risk list reviewed by Nadia and Omar in the Q3 planning meeting.",
    ("soc2", "CC4"): "Demo: quarterly control check-in; minutes in the Security policies room.",
    ("soc2", "CC5"): "Demo: procedures live next to each policy in the Security policies room.",
    ("soc2", "CC6"): "Demo: office access by badge; laptops use full-disk encryption (MDM report on file).",
    ("soc2", "CC7"): "Demo: hosting alerts go to the on-call channel; runbook in the docs.",
    ("soc2", "CC8"): "Demo: code changes need a reviewed pull request and passing CI.",
    ("soc2", "CC9"): "Demo: vendor list reviewed yearly; AWS SOC 2 report on file.",
    ("soc2", "A1"): "Demo: capacity dashboards reviewed weekly by Engineering.",
    ("soc2", "C1"): "Demo: confidential data is labelled in the data map.",
    ("soc2", "PI1"): "Demo: inputs validated by the API; failed jobs alert the team.",
    ("soc2", "P"): "Demo: privacy notice published; requests handled from the Privacy page.",
    ("iso27001", "5"): "Demo: documented in the information security policy; owner Nadia.",
    ("iso27001", "6"): "Demo: HR onboarding checklist covers this; signed copies kept by People.",
    ("iso27001", "7"): "Demo: shared office with badge access; landlord security report on file.",
    ("iso27001", "8"): "Demo: covered by our engineering standards and the hosting provider's controls.",
}
NOT_APPLICABLE = {
    ("iso27001", "7.11"): "Demo: no server room; production runs on AWS.",
    ("iso27001", "7.12"): "Demo: no cabling we own; office network is the landlord's.",
    ("iso27001", "8.30"): "Demo: we do not outsource development.",
}


def seed(org, users, now):
    from compliance.models import ComplianceProfile

    ComplianceProfile.objects.update_or_create(org=org, defaults={"updated_by": users["owner"]})
    _org_facts(org, users, now)
    _reviews(org, users, now)
    _policies(org, users, now)
    _trust(org, users, now)
    _attest(org, users, now)
    _evidence(org, users, now)


def _org_facts(org, users, now):
    """Facts some automated checks read: a recent org export, a pinned data region."""
    from exports.models import MemoryExport
    from organizations.models import OrgPolicy

    done = now - timedelta(days=6)
    MemoryExport.objects.create(org=org, requested_by=users["owner"], status=MemoryExport.STATUS_SUCCEEDED, size_bytes=4_812_331,
                                counts={"demo": True}, created_at=done - timedelta(minutes=4), finished_at=done, expires_at=done)
    OrgPolicy.objects.update_or_create(org=org, defaults={"pii_redaction": "external_only", "data_region": "eu-central-1", "updated_by": users["owner"]})


def _reviews(org, users, now):
    from compliance import reviews
    from compliance.models import AccessReview, AccessReviewItem

    old = AccessReview.objects.create(
        org=org, name="Access review 2026-Q2", period="2026-Q2", status=AccessReview.COMPLETED, created_by=users["admin"],
        created_at=now - timedelta(days=125), due_at=now - timedelta(days=111), completed_at=now - timedelta(days=110), completed_by=users["admin"],
    )
    old.summary = {"progress": {"total": 9, "decided": 9, "pending": 0, "waiting_apply": 0, "errors": 0},
                   "by_kind": {"membership": {"keep": 6, "revoke": 0, "change": 0, "pending": 0}, "grant": {"keep": 2, "revoke": 1, "change": 0, "pending": 0}},
                   "changes": [{"subject": "Sara Nabil", "kind": "grant", "label": "Extra permission: hr.view", "decision": "revoke", "decided_by": "Omar Khaled"}],
                   "reviewers": ["Layla Mansour", "Omar Khaled"], "demo": True}
    old.save(update_fields=["summary"])

    review = reviews.create_review(org, users["admin"], "Access review 2026-Q4", "2026-Q4", AccessReview.REVIEWERS_LEADS, due_days=14)
    AccessReview.objects.filter(pk=review.pk).update(created_at=now - timedelta(days=5), due_at=now + timedelta(days=9))
    review.refresh_from_db()
    items = list(review.items.select_related("subject", "reviewer"))
    admin = users["admin"]
    keep_by_admin = {users["owner"].id, users["lead"].id}
    for item in items:
        if item.kind == AccessReviewItem.MEMBERSHIP and item.subject_id in keep_by_admin:
            reviews.decide(item, admin, "keep", note="Demo: still needs this access.")
        elif item.kind == AccessReviewItem.MEMBERSHIP and item.subject_id == users["member"].id and item.reviewer_id:
            reviews.decide(item, item.reviewer, "keep", note="Demo: active on the mobile launch.")
    # A lead's revoke waits for an admin to apply it.
    grants = [i for i in items if i.kind == AccessReviewItem.GRANT and i.reviewer_id]
    grants.sort(key=lambda i: i.details.get("perm_key") != "team.manage")
    if grants:
        reviews.decide(grants[0], grants[0].reviewer, "revoke", note="Demo: the onboarding project ended.")


def _policies(org, users, now):
    from compliance import policies
    from compliance.models import PolicyAck
    from organizations.models import OrgMembership

    owner = users["owner"]
    published = policies.install(org, owner, ["information-security", "acceptable-use"], publish=True)
    policies.install(org, owner, ["access-control"], publish=False)  # a draft the owner is still editing
    active = OrgMembership.objects.filter(org=org, employment_status="active").select_related("user")
    for n, policy in enumerate(published):
        version = policies.current_version(policy)
        type(version).objects.filter(pk=version.pk).update(published_at=now - timedelta(days=20 - n))
        for i, m in enumerate(active):
            PolicyAck.objects.create(version=version, user=m.user, acknowledged_at=now - timedelta(days=18 - n, hours=i))


def _trust(org, users, now):
    from compliance import trust
    from compliance.models import TrustCenter, TrustRequest

    example = trust.FLOBRAIN_EXAMPLE
    TrustCenter.objects.update_or_create(org=org, defaults={
        "slug": trust.default_slug(org), "published": True, "published_at": now - timedelta(days=12),
        "sections": list(example["sections"]), "headline": example["headline"] + " (demo)",
        "overview": example["overview"] + " This demo page uses FloBrain's own trust content as the example.",
        "subprocessors": list(example["subprocessors"]), "data_location": example["data_location"],
        "documents": list(example["documents"]), "contact_email": "security@demo.flobrain.example",
        "updated_by": users["owner"], "updated_at": now - timedelta(days=2),
    })
    TrustRequest.objects.create(org=org, name="Mona Fathy", email="mona@delta-clinics.example.com", company="Delta Clinics (demo)",
                                documents=["soc2-readiness", "dpa"], message="Demo: our procurement team needs these before renewal.",
                                ip_hash="demo", created_at=now - timedelta(hours=7))
    TrustRequest.objects.create(org=org, name="Karim Saad", email="karim@cairo-bikes.example.com", company="Cairo Bikes (demo)",
                                documents=["policies"], status=TrustRequest.SENT, handled_by=users["admin"], handled_at=now - timedelta(days=3),
                                ip_hash="demo", created_at=now - timedelta(days=4))


def _attest(org, users, now):
    """Attest manual controls in catalog order until about 70% of applicable controls pass."""
    from compliance import checks, readiness
    from compliance.models import ControlAttestation

    for (framework, cid), note in NOT_APPLICABLE.items():
        ControlAttestation.objects.create(org=org, framework=framework, control_id=cid, status="not_applicable", note=note,
                                          attested_by=users["owner"], attested_at=now - timedelta(days=30))
    results = checks.run_all(org)
    rows = readiness.evaluate(org, results)
    owners = [users["owner"], users["admin"], users["lead"]]
    for framework in ("soc2", "iso27001"):
        mine = [r for r in rows if r["framework"] == framework]
        applicable = sum(1 for r in mine if r["status"] != "not_applicable")
        passing = sum(1 for r in mine if r["status"] == "pass")
        for n, row in enumerate(r for r in mine if r["status"] == "manual"):
            if passing >= TARGET * applicable:
                break
            ControlAttestation.objects.create(
                org=org, framework=framework, control_id=row["id"], status="pass", note=NOTES[(framework, row["group"])],
                owner=owners[n % len(owners)], attested_by=users["owner"] if n % 2 == 0 else users["admin"],
                attested_at=now - timedelta(days=3 + n % 40),
            )
            passing += 1


def _evidence(org, users, now):
    from compliance import evidence
    from compliance.models import EvidencePackage
    from content_studio import storage

    if not storage.is_configured():
        return
    package = evidence.generate(org, users["admin"], now - timedelta(days=90), now)
    if package.status != EvidencePackage.READY:
        package.delete()
