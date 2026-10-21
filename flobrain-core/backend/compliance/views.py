"""Compliance API (M7): SOC 2 and ISO 27001 readiness. Every endpoint: active member (403) → flag
``compliance`` (501) → permission (403). ``compliance.view`` reads, ``compliance.manage`` changes.
Reviewers (team leads) and members use the ``me``, ``my-reviews``, ``my-policies`` endpoints without
``compliance.view``.

- ``GET  /orgs/{org}/compliance/me``: what this person can do here, their open review items and policies to read
- ``GET  /orgs/{org}/compliance/overview``: readiness by framework and group, check results, counts
- ``GET|PATCH /orgs/{org}/compliance/settings``
- ``GET  /orgs/{org}/compliance/controls?framework=&status=&group=&q=``
- ``PUT|DELETE /orgs/{org}/compliance/controls/{framework}/{control}/attestation``
- ``GET|POST /orgs/{org}/compliance/reviews``; ``GET .../reviews/{id}?mine=1``; ``GET .../reviews/{id}/report[?export=csv]``
- ``POST .../reviews/{id}/{remind|apply|complete|cancel}``; ``POST .../reviews/{id}/items/{item}/decision``
- ``GET  /orgs/{org}/compliance/my-reviews``
- ``GET|POST /orgs/{org}/compliance/evidence``; ``GET .../evidence/{id}/download``
- ``GET  /orgs/{org}/compliance/policy-templates``; ``GET|POST /orgs/{org}/compliance/policies``
- ``GET .../policies/{id}``; ``POST .../policies/{id}/publish``; ``POST .../policies/{id}/acknowledge``
- ``GET  /orgs/{org}/compliance/my-policies``
- ``GET|PUT /orgs/{org}/compliance/trust``; ``GET .../trust/requests``; ``PATCH .../trust/requests/{id}``
"""

import csv
import io
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from compliance import catalog, checks, evidence, policies, readiness, reviews, trust
from compliance.models import (
    AccessReview,
    AccessReviewItem,
    ComplianceProfile,
    ControlAttestation,
    EvidencePackage,
    Policy,
    TrustCenter,
    TrustRequest,
)
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember, can
from organizations.services.core import audit

FLAG = "compliance"
VIEW = "compliance.view"
MANAGE = "compliance.manage"


def _err(code, details, status=400):
    return Response({"error": code, "details": details}, status=status)


def _body(request):
    return request.data if hasattr(request.data, "get") else {}


def _from(exc: reviews.ReviewError):
    return _err(exc.code, exc.details, exc.status)


class ComplianceView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def gate(self, request, org_id, perm=VIEW):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if not effective_flag(org, membership, FLAG, default=False):
            return org, _err("not_implemented", "Compliance is not enabled", 501)
        if perm and not can(request.user, perm, org):
            raise PermissionDenied(f"Missing permission: {perm}")
        return org, None


# --- overview and controls -------------------------------------------------------------------------


class MeView(ComplianceView):
    @extend_schema(summary="What this person can do in compliance, their review items and policies to read")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id, perm=None)
        if error:
            return error
        open_items = AccessReviewItem.objects.filter(review__org=org, review__status=AccessReview.OPEN, decision=AccessReviewItem.PENDING)
        manager = can(request.user, MANAGE, org)
        mine = [i for i in open_items.select_related("review") if reviews.may_decide(request.user, i, manager)]
        to_read = [p for p in policies.my_policies(org, request.user) if not p["acknowledged_at"]]
        return Response({
            "can_view": can(request.user, VIEW, org), "can_manage": can(request.user, MANAGE, org),
            "review_items": len(mine), "policies_to_read": len(to_read),
        })


class OverviewView(ComplianceView):
    @extend_schema(summary="Readiness by framework, automated check results and counts")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        results = checks.run_all(org)
        rows = readiness.evaluate(org, results)
        open_review = AccessReview.objects.filter(org=org, status=AccessReview.OPEN).first()
        last_package = EvidencePackage.objects.filter(org=org, status=EvidencePackage.READY).first()
        trust_row = TrustCenter.objects.filter(org=org).first()
        return Response({
            "frameworks": readiness.summarize(rows),
            "checks": list(results.values()),
            "open_review": reviews.review_payload(open_review) if open_review else None,
            "last_evidence": evidence.package_payload(last_package) if last_package else None,
            "policies": Policy.objects.filter(org=org).count(),
            "trust_published": bool(trust_row and trust_row.published),
            "disclaimer": trust.DISCLAIMER,
        })


def _profile_payload(profile, org):
    return {
        "frameworks": readiness.frameworks_for(org), "dormant_days": profile.dormant_days,
        "request_age_days": profile.request_age_days, "review_interval_days": profile.review_interval_days,
        "all_frameworks": [{"key": k, **v} for k, v in catalog.FRAMEWORKS.items()],
    }


class SettingsView(ComplianceView):
    @extend_schema(summary="Compliance settings (frameworks, thresholds)")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        profile = ComplianceProfile.objects.filter(org=org).first() or ComplianceProfile(org=org)
        return Response(_profile_payload(profile, org))

    @extend_schema(summary="Change compliance settings (compliance.manage)")
    def patch(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        data = _body(request)
        profile = ComplianceProfile.objects.filter(org=org).first() or ComplianceProfile(org=org)
        if "frameworks" in data:
            chosen = data.get("frameworks")
            if not isinstance(chosen, list) or not chosen or any(f not in catalog.FRAMEWORKS for f in chosen):
                return _err("invalid", "frameworks must list soc2 and/or iso27001")
            profile.frameworks = sorted(set(chosen))
        for field, low, high in (("dormant_days", 30, 365), ("request_age_days", 1, 90), ("review_interval_days", 30, 365)):
            if field in data:
                try:
                    value = int(data.get(field))
                except (TypeError, ValueError):
                    return _err("invalid", f"{field} must be a number")
                if not low <= value <= high:
                    return _err("invalid", f"{field} must be between {low} and {high}")
                setattr(profile, field, value)
        profile.updated_by, profile.updated_at = request.user, timezone.now()
        profile.save()
        trust.flush_cache(org)
        audit(request.user, "compliance.settings", org=org, request=request, payload={k: v for k, v in _profile_payload(profile, org).items() if k != "all_frameworks"})
        return Response(_profile_payload(profile, org))


class ControlListView(ComplianceView):
    @extend_schema(summary="Controls with status, mapped checks and attestations")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        framework = request.query_params.get("framework") or None
        if framework and framework not in catalog.FRAMEWORKS:
            return _err("invalid", "framework must be soc2 or iso27001")
        results = checks.run_all(org)
        rows = readiness.evaluate(org, results, framework)
        status = request.query_params.get("status")
        if status:
            rows = [r for r in rows if r["status"] == status]
        group = request.query_params.get("group")
        if group:
            rows = [r for r in rows if r["group"] == group]
        q = (request.query_params.get("q") or "").strip().lower()[:80]
        if q:
            rows = [r for r in rows if q in r["id"].lower() or q in r["name"].lower() or q in r["summary"].lower()]
        return Response({"controls": rows, "checks": results})


class AttestationView(ComplianceView):
    @extend_schema(summary="Attest a control: manual evidence, a known gap, or not applicable (compliance.manage)")
    def put(self, request, org_id, framework, control_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        if catalog.control(framework, control_id) is None:
            return _err("not_found", "Control not found", 404)
        data = _body(request)
        status = data.get("status")
        if status not in ControlAttestation.STATUSES:
            return _err("invalid", "status must be pass, fail or not_applicable")
        note = trust.clean_text(data.get("note"), 1000)
        if status in (ControlAttestation.PASS, ControlAttestation.NOT_APPLICABLE) and len(note) < 10:
            return _err("invalid", "Say what the evidence is, or why it does not apply (at least 10 characters)")
        url = trust.clean_text(data.get("evidence_url"), 500)
        if url and not (url.startswith("https://") or url.startswith("/")):
            return _err("invalid", "The evidence link must start with https:// or be a path inside FloBrain")
        owner = None
        if data.get("owner"):
            owner_m = OrgMembership.objects.filter(org=org, user_id=data.get("owner"), employment_status="active").select_related("user").first()
            if owner_m is None:
                return _err("invalid", "The owner must be an active member")
            owner = owner_m.user
        att, _ = ControlAttestation.objects.update_or_create(
            org=org, framework=framework, control_id=control_id,
            defaults={"status": status, "note": note, "evidence_url": url, "owner": owner, "attested_by": request.user, "attested_at": timezone.now()},
        )
        trust.flush_cache(org)
        audit(request.user, "compliance.attest", target=att, org=org, request=request, payload={"framework": framework, "control": control_id, "status": status})
        row = next(r for r in readiness.evaluate(org, framework=framework) if r["id"] == control_id)
        return Response(row)

    @extend_schema(summary="Remove an attestation (compliance.manage)")
    def delete(self, request, org_id, framework, control_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        deleted, _ = ControlAttestation.objects.filter(org=org, framework=framework, control_id=control_id).delete()
        if deleted:
            trust.flush_cache(org)
            audit(request.user, "compliance.attest.remove", org=org, request=request, payload={"framework": framework, "control": control_id})
        return Response(status=204)


# --- access reviews --------------------------------------------------------------------------------


def _quarter(now):
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


class ReviewListView(ComplianceView):
    @extend_schema(summary="Access reviews")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        return Response([reviews.review_payload(r) for r in AccessReview.objects.filter(org=org)[:50]])

    @extend_schema(summary="Start an access review (compliance.manage): {name?, period?, reviewer_mode, due_days}")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        data = _body(request)
        now = timezone.now()
        period = trust.clean_text(data.get("period"), 20) or _quarter(now)
        name = trust.clean_text(data.get("name"), 120) or f"Access review {period}"
        mode = data.get("reviewer_mode") or AccessReview.REVIEWERS_LEADS
        if mode not in (AccessReview.REVIEWERS_LEADS, AccessReview.REVIEWERS_ADMINS):
            return _err("invalid", "reviewer_mode must be team_leads or admins")
        try:
            due_days = int(data.get("due_days") or 14)
        except (TypeError, ValueError):
            return _err("invalid", "due_days must be a number")
        if not 1 <= due_days <= 60:
            return _err("invalid", "due_days must be between 1 and 60")
        try:
            review = reviews.create_review(org, request.user, name, period, mode, due_days, request=request)
        except reviews.ReviewError as exc:
            return _from(exc)
        return Response(reviews.review_payload(review), status=201)


class ReviewDetailView(ComplianceView):
    @extend_schema(summary="A review with its items. Reviewers without compliance.view see only their items (?mine=1).")
    def get(self, request, org_id, review_id):
        org, error = self.gate(request, org_id, perm=None)
        if error:
            return error
        review = get_object_or_404(AccessReview, org=org, pk=review_id)
        items = review.items.select_related("subject", "reviewer", "decided_by", "review")
        viewer = can(request.user, VIEW, org)
        manager = can(request.user, MANAGE, org)
        if not viewer or request.query_params.get("mine") in ("1", "true"):
            items = [i for i in items if reviews.may_decide(request.user, i, manager) or (i.decided_by_id == request.user.id)]
            if not viewer and not items:
                raise PermissionDenied(f"Missing permission: {VIEW}")
        return Response({**reviews.review_payload(review), "items": [reviews.item_payload(i, request.user, manager) for i in items],
                         "grant_days": list(reviews.GRANT_DAYS)})


class ReviewActionView(ComplianceView):
    @extend_schema(summary="remind | apply | complete | cancel (compliance.manage)")
    def post(self, request, org_id, review_id, action):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        review = get_object_or_404(AccessReview, org=org, pk=review_id)
        try:
            if action == "remind":
                sent = reviews.remind(review, request.user, request=request)
                return Response({"sent": sent})
            if action == "apply":
                done = reviews.apply_pending(review, request.user, request=request)
                return Response({"applied": done, **reviews.review_payload(review)})
            if action == "complete":
                reviews.complete(review, request.user, request=request)
                trust.flush_cache(org)
                return Response(reviews.review_payload(review))
            if action == "cancel":
                reviews.cancel(review, request.user, request=request)
                return Response(reviews.review_payload(review))
        except reviews.ReviewError as exc:
            return _from(exc)
        return _err("not_found", "Unknown action", 404)


class ReviewDecisionView(ComplianceView):
    @extend_schema(summary="Decide one item: {decision: keep|revoke|change, change_to?, note?}")
    def post(self, request, org_id, review_id, item_id):
        org, error = self.gate(request, org_id, perm=None)
        if error:
            return error
        item = get_object_or_404(AccessReviewItem.objects.select_related("review", "subject"), review__org=org, review_id=review_id, pk=item_id)
        data = _body(request)
        try:
            item = reviews.decide(item, request.user, data.get("decision"), data.get("change_to"), data.get("note") or "", request=request)
        except reviews.ReviewError as exc:
            return _from(exc)
        trust.flush_cache(org)
        return Response(reviews.item_payload(item, request.user))


class ReviewReportView(ComplianceView):
    @extend_schema(summary="Completion report (JSON, or CSV with ?export=csv)")
    def get(self, request, org_id, review_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        review = get_object_or_404(AccessReview, org=org, pk=review_id)
        data = reviews.report(review)
        if request.query_params.get("export") != "csv":
            return Response(data)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["person", "email", "kind", "access", "reviewer", "decision", "change_to", "decided_by", "decided_at", "applied_at", "note"])
        for i in review.items.select_related("subject", "reviewer", "decided_by"):
            writer.writerow([evidence._cell(v) for v in (
                reviews._name(i.subject), i.subject.email, i.kind, i.label, reviews._name(i.reviewer) if i.reviewer else "admins",
                i.decision, i.change_to or "", reviews._name(i.decided_by) if i.decided_by else "",
                i.decided_at.isoformat() if i.decided_at else "", i.applied_at.isoformat() if i.applied_at else "", i.note)])
        response = HttpResponse(out.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="access-review-{review.period or review.id}.csv"'
        return response


class MyReviewsView(ComplianceView):
    @extend_schema(summary="Open review items this person may decide")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id, perm=None)
        if error:
            return error
        out = []
        manager = can(request.user, MANAGE, org)
        for review in AccessReview.objects.filter(org=org, status=AccessReview.OPEN):
            items = [i for i in review.items.select_related("subject", "reviewer", "decided_by", "review") if reviews.may_decide(request.user, i, manager)]
            if items:
                out.append({**reviews.review_payload(review), "items": [reviews.item_payload(i, request.user, manager) for i in items]})
        return Response(out)


# --- evidence --------------------------------------------------------------------------------------


def _parse_day(value, end=False):
    try:
        day = datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=dt_timezone.utc)
    except (TypeError, ValueError):
        return None
    return day + timedelta(days=1) if end else day


class EvidenceListView(ComplianceView):
    @extend_schema(summary="Evidence packages")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        evidence.expire()
        return Response([evidence.package_payload(p) for p in EvidencePackage.objects.filter(org=org).select_related("created_by")[:30]])

    @extend_schema(summary="Build an evidence package: {start: YYYY-MM-DD, end: YYYY-MM-DD} (compliance.manage)")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        from content_studio import storage

        if not storage.is_configured():
            return _err("not_implemented", "Private file storage is not configured", 501)
        data = _body(request)
        now = timezone.now()
        end = _parse_day(data.get("end"), end=True) if data.get("end") else now
        start = _parse_day(data.get("start")) if data.get("start") else end - timedelta(days=90)
        if start is None or end is None or start >= end:
            return _err("invalid", "Pick a start date before the end date (YYYY-MM-DD)")
        if end - start > timedelta(days=400):
            return _err("invalid", "A package covers at most 400 days")
        if EvidencePackage.objects.filter(org=org, created_at__gte=now - timedelta(days=1)).count() >= 10:
            return _err("too_many_requests", "10 packages a day at most", 429)
        package = evidence.generate(org, request.user, start, min(end, now), request=request)
        if package.status != EvidencePackage.READY:
            return Response(evidence.package_payload(package), status=500)
        return Response(evidence.package_payload(package), status=201)


class EvidenceDownloadView(ComplianceView):
    @extend_schema(summary="Download an evidence package ZIP (compliance.manage, 7 days)")
    def get(self, request, org_id, package_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        from content_studio import storage

        package = get_object_or_404(EvidencePackage, org=org, pk=package_id)
        if package.status != EvidencePackage.READY or not package.expires_at or package.expires_at <= timezone.now():
            return _err("gone", "This package has expired. Build a new one.", 410)
        data = storage.read_bytes(package.storage_key, max_bytes=256 << 20)
        if data is None:
            return _err("not_found", "The file is not in storage", 404)
        audit(request.user, "compliance.evidence.download", target=package, org=org, request=request, payload={"sha256": package.sha256})
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="evidence-{package.period_end.date().isoformat()}.zip"'
        response["Cache-Control"] = "no-store"
        return response


# --- policies --------------------------------------------------------------------------------------


class PolicyTemplatesView(ComplianceView):
    @extend_schema(summary="Policy templates that can be installed")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        installed = set(Policy.objects.filter(org=org).values_list("template", flat=True))
        return Response([{**t, "installed": t["key"] in installed} for t in policies.TEMPLATES])


class PolicyListView(ComplianceView):
    @extend_schema(summary="Installed policies with versions and acknowledgement counts")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        active = set(OrgMembership.objects.filter(org=org, employment_status="active").values_list("user_id", flat=True))
        rows = Policy.objects.filter(org=org).select_related("document").order_by("title")
        return Response([policies.policy_payload(p, active) for p in rows])

    @extend_schema(summary="Install templates as Documents: {templates: [...], publish?: bool} (compliance.manage)")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        data = _body(request)
        keys = data.get("templates")
        if not isinstance(keys, list) or not keys or any(k not in policies.BY_KEY for k in keys):
            return _err("invalid", "templates must list template keys")
        try:
            created = policies.install(org, request.user, keys, publish=bool(data.get("publish")), request=request)
        except IntegrityError:
            return _err("conflict", "That policy is already installed", 409)
        return Response([policies.policy_payload(p) for p in created], status=201)


class PolicyDetailView(ComplianceView):
    @extend_schema(summary="A policy with its current text and who has not acknowledged it")
    def get(self, request, org_id, policy_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        policy = get_object_or_404(Policy.objects.select_related("document"), org=org, pk=policy_id)
        data = policies.policy_payload(policy, with_body=True)
        missing = data["stats"].pop("missing_ids")
        members = OrgMembership.objects.filter(org=org, user_id__in=missing).select_related("user")
        data["missing"] = [{"id": str(m.user_id), "name": m.user.username or m.user.email} for m in members]
        data["versions"] = [{"version": v.version, "sha256": v.sha256, "published_at": v.published_at.isoformat(), "acks": v.acks.count()} for v in policy.versions.all()]
        return Response(data)


class PolicyPublishView(ComplianceView):
    @extend_schema(summary="Publish the Document's current text as a new version (compliance.manage)")
    def post(self, request, org_id, policy_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        policy = get_object_or_404(Policy.objects.select_related("document"), org=org, pk=policy_id)
        if policy.document is None:
            return _err("invalid", "The policy's document was deleted. Install the template again.", 409)
        with transaction.atomic():
            version, changed = policies.publish_version(policy, request.user, request=request)
        if version is None:
            return _err("invalid", "The document is empty")
        trust.flush_cache(org)
        return Response({**policies.policy_payload(policy), "changed": changed}, status=201 if changed else 200)


class PolicyAckView(ComplianceView):
    @extend_schema(summary="Acknowledge the current version: {version}")
    def post(self, request, org_id, policy_id):
        org, error = self.gate(request, org_id, perm=None)
        if error:
            return error
        policy = get_object_or_404(Policy, org=org, pk=policy_id)
        ack, _ = policies.acknowledge(policy, request.user, _body(request).get("version"), request=request)
        if ack is None:
            return _err("conflict", "A newer version was published. Read it, then acknowledge.", 409)
        trust.flush_cache(org)
        return Response({"acknowledged_at": ack.acknowledged_at.isoformat(), "version": ack.version.version})


class MyPoliciesView(ComplianceView):
    @extend_schema(summary="Published policies for this member, with acknowledgement state")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id, perm=None)
        if error:
            return error
        return Response(policies.my_policies(org, request.user))


# --- trust center ----------------------------------------------------------------------------------


class TrustSettingsView(ComplianceView):
    @extend_schema(summary="Trust center settings and FloBrain's example content")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        row = trust.get_or_new(org)
        return Response({**trust.payload(row), "example": trust.FLOBRAIN_EXAMPLE, "preview": trust.public_projection(row)})

    @extend_schema(summary="Save the trust center; {published: true} makes /trust/<slug> public (compliance.manage)")
    def put(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        data = _body(request)
        row = trust.get_or_new(org)
        if "slug" in data:
            slug = str(data.get("slug") or "").strip().lower()
            if not trust.SLUG_RE.match(slug):
                return _err("invalid", "Use 3 to 80 lowercase letters, numbers and hyphens")
            if TrustCenter.objects.filter(slug=slug).exclude(org=org).exists():
                return _err("conflict", "That address is taken", 409)
            row.slug = slug
        if "sections" in data:
            sections = data.get("sections")
            if not isinstance(sections, list) or any(s not in TrustCenter.SECTIONS for s in sections):
                return _err("invalid", f"sections can include: {', '.join(TrustCenter.SECTIONS)}")
            row.sections = [s for s in TrustCenter.SECTIONS if s in sections]
        if "headline" in data:
            row.headline = trust.clean_text(data.get("headline"), 160)
        if "overview" in data:
            row.overview = trust.clean_text(data.get("overview"), 4000)
        if "data_location" in data:
            row.data_location = trust.clean_text(data.get("data_location"), 300)
        if "contact_email" in data:
            email = str(data.get("contact_email") or "").strip()
            if email and not trust.EMAIL_RE.match(email):
                return _err("invalid", "Enter a valid contact email")
            row.contact_email = email
        try:
            if "subprocessors" in data:
                row.subprocessors = trust.clean_subprocessors(data.get("subprocessors"))
            if "documents" in data:
                row.documents = trust.clean_documents(data.get("documents"))
        except ValueError as exc:
            return _err("invalid", str(exc))
        was = row.published
        if "published" in data:
            row.published = bool(data.get("published"))
            if row.published and not was:
                row.published_at = timezone.now()
        row.updated_by, row.updated_at = request.user, timezone.now()
        try:
            row.save()
        except IntegrityError:
            return _err("conflict", "That address is taken", 409)
        trust.flush_cache(org)
        action = "compliance.trust.publish" if row.published and not was else "compliance.trust.unpublish" if was and not row.published else "compliance.trust.update"
        audit(request.user, action, org=org, request=request, payload={"slug": row.slug, "sections": row.sections})
        return Response({**trust.payload(row), "preview": trust.public_projection(row)})


class TrustRequestListView(ComplianceView):
    @extend_schema(summary="Document requests from the trust page")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        return Response([trust.request_payload(r) for r in TrustRequest.objects.filter(org=org).select_related("handled_by")[:100]])


class TrustRequestDetailView(ComplianceView):
    @extend_schema(summary="Mark a request sent or declined (compliance.manage)")
    def patch(self, request, org_id, request_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        req = get_object_or_404(TrustRequest, org=org, pk=request_id)
        status = _body(request).get("status")
        if status not in (TrustRequest.SENT, TrustRequest.DECLINED, TrustRequest.NEW):
            return _err("invalid", "status must be new, sent or declined")
        trust.mark(req, request.user, status)
        audit(request.user, "compliance.trust.request", target=req, org=org, request=request, payload={"status": status})
        return Response(trust.request_payload(req))
