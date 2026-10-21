"""SOC 2 and ISO 27001 readiness (M7). Nothing here claims certification: the app shows readiness and
the evidence behind it.

- ``ComplianceProfile``: per-org settings (frameworks shown, thresholds).
- ``ControlAttestation``: a person's statement on a control (manual evidence, a note, or "not applicable").
  It can never turn a failing automated check into a pass.
- ``AccessReview`` and ``AccessReviewItem``: quarterly access reviews; decisions keep, revoke or change are
  applied through the existing services and audited.
- ``EvidencePackage``: a ZIP built for a period (JSON + CSV + manifest with SHA-256), private, 7 days.
- ``Policy``, ``PolicyVersion``, ``PolicyAck``: policies installed from templates as Documents; members
  acknowledge a version.
- ``TrustCenter`` and ``TrustRequest``: the public trust page (off until published) and its request form.
"""

import uuid

from django.db import models
from django.utils import timezone


class ComplianceProfile(models.Model):
    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="compliance_profile")
    frameworks = models.JSONField(default=list, blank=True)  # ["soc2", "iso27001"]; empty = both
    dormant_days = models.PositiveSmallIntegerField(default=90)
    request_age_days = models.PositiveSmallIntegerField(default=14)
    review_interval_days = models.PositiveSmallIntegerField(default=90)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "compliance_profiles"


class ControlAttestation(models.Model):
    """A person's statement on one control: manual evidence ("pass"), a known gap ("fail") or "not applicable"."""

    PASS, FAIL, NOT_APPLICABLE = "pass", "fail", "not_applicable"
    STATUSES = (PASS, FAIL, NOT_APPLICABLE)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="control_attestations")
    framework = models.CharField(max_length=16)
    control_id = models.CharField(max_length=16)
    status = models.CharField(max_length=16)
    note = models.CharField(max_length=1000, blank=True, default="")
    evidence_url = models.CharField(max_length=500, blank=True, default="")
    owner = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    attested_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    attested_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "compliance_attestations"
        constraints = [models.UniqueConstraint(fields=["org", "framework", "control_id"], name="unique_control_attestation")]


class AccessReview(models.Model):
    DRAFT, OPEN, COMPLETED, CANCELLED = "draft", "open", "completed", "cancelled"
    STATUSES = (DRAFT, OPEN, COMPLETED, CANCELLED)
    REVIEWERS_LEADS, REVIEWERS_ADMINS = "team_leads", "admins"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="access_reviews")
    name = models.CharField(max_length=120)
    period = models.CharField(max_length=20, blank=True, default="")  # e.g. "2026-Q4"
    reviewer_mode = models.CharField(max_length=12, default=REVIEWERS_LEADS)
    status = models.CharField(max_length=10, default=OPEN, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "compliance_access_reviews"
        ordering = ["-created_at"]


class AccessReviewItem(models.Model):
    MEMBERSHIP, GRANT, INTEGRATION, BUDDY = "membership", "grant", "integration", "buddy"
    KINDS = (MEMBERSHIP, GRANT, INTEGRATION, BUDDY)
    PENDING, KEEP, REVOKE, CHANGE = "pending", "keep", "revoke", "change"
    DECISIONS = (KEEP, REVOKE, CHANGE)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(AccessReview, on_delete=models.CASCADE, related_name="items")
    subject = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=12)
    ref_id = models.CharField(max_length=64, blank=True, default="")
    label = models.CharField(max_length=200)
    details = models.JSONField(default=dict, blank=True)
    reviewer = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decision = models.CharField(max_length=8, default=PENDING, db_index=True)
    change_to = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=500, blank=True, default="")
    decided_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    apply_error = models.CharField(max_length=200, blank=True, default="")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "compliance_access_review_items"
        ordering = ["position"]


class EvidencePackage(models.Model):
    BUILDING, READY, FAILED, EXPIRED = "building", "ready", "failed", "expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="evidence_packages")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=10, default=BUILDING)
    storage_key = models.CharField(max_length=300, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    manifest = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "compliance_evidence_packages"
        ordering = ["-created_at"]


class Policy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="compliance_policies")
    template = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    document = models.ForeignKey("docs.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    requires_ack = models.BooleanField(default=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "compliance_policies"
        constraints = [models.UniqueConstraint(fields=["org", "template"], name="unique_org_policy_template")]


class PolicyVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    body = models.TextField()
    sha256 = models.CharField(max_length=64)
    published_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    published_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "compliance_policy_versions"
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["policy", "version"], name="unique_policy_version")]


class PolicyAck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(PolicyVersion, on_delete=models.CASCADE, related_name="acks")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    acknowledged_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "compliance_policy_acks"
        constraints = [models.UniqueConstraint(fields=["version", "user"], name="unique_policy_ack")]


class TrustCenter(models.Model):
    SECTIONS = ("overview", "controls", "subprocessors", "data_location", "documents")

    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="trust_center")
    slug = models.SlugField(max_length=80, unique=True)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    sections = models.JSONField(default=list, blank=True)  # which of SECTIONS are shown
    headline = models.CharField(max_length=160, blank=True, default="")
    overview = models.TextField(blank=True, default="")
    subprocessors = models.JSONField(default=list, blank=True)  # [{name, purpose, location, website}]
    data_location = models.CharField(max_length=300, blank=True, default="")
    documents = models.JSONField(default=list, blank=True)  # [{key, title, description}]
    contact_email = models.EmailField(blank=True, default="")
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "compliance_trust_centers"


class TrustRequest(models.Model):
    NEW, SENT, DECLINED = "new", "sent", "declined"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="trust_requests")
    name = models.CharField(max_length=120)
    email = models.EmailField()
    company = models.CharField(max_length=160, blank=True, default="")
    documents = models.JSONField(default=list, blank=True)
    message = models.CharField(max_length=1000, blank=True, default="")
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=10, default=NEW)
    handled_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "compliance_trust_requests"
        ordering = ["-created_at"]
