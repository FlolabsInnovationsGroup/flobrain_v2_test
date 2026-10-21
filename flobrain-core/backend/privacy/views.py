"""Privacy center (Phase 16, Decision 44).

A person sees what FloBrain holds about them and who can see it, sets what they share,
downloads their own data, and asks for deletion. Admins decide deletion requests; the owner
sets retention, which deletes old data together with its search vectors.
"""

from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from content_studio import storage
from core_v2.views import V2APIView
from notifications.models import Notification
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit
from privacy import jobs
from privacy.models import DataExportJob, DeletionRequest, PrivacySettings, RetentionPolicy
from privacy.services import erase_member_data, inventory, settings_for

RETENTION_FIELDS = ("messages_days", "recordings_days", "transcripts_days", "time_entries_days")


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _org(request, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    return org


def _impersonated(request):
    from console.impersonation import is_impersonated

    return is_impersonated(request)


def _settings_payload(s):
    return {
        "share_time_details_with_org": s.share_time_details_with_org,
        "analytics_personal_only": s.analytics_personal_only,
        "consents": s.consents or {},
    }


class MyPrivacyView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="What FloBrain holds about me in this org, who can see it, and my settings")
    def get(self, request, org_id):
        org = _org(request, org_id)
        return Response({"settings": _settings_payload(settings_for(request.user, org)), **inventory(request.user, org)})

    @extend_schema(summary="Change my privacy settings in this org")
    def put(self, request, org_id):
        org = _org(request, org_id)
        body = _body(request)
        s = settings_for(request.user, org, create=True)
        for field in ("share_time_details_with_org", "analytics_personal_only"):
            if field in body:
                if not isinstance(body[field], bool):
                    return _bad({field: "true or false"})
                setattr(s, field, body[field])
        if "consents" in body:
            consents = body["consents"]
            if not isinstance(consents, dict) or len(consents) > 20 or not all(isinstance(k, str) and len(k) <= 40 and isinstance(v, bool) for k, v in consents.items()):
                return _bad({"consents": "a map of up to 20 names to true or false"})
            s.consents = consents
        s.updated_at = timezone.now()
        s.save()
        audit(request.user, "privacy.settings.update", target=s, payload=_settings_payload(s), request=request, org=org)
        return Response(_settings_payload(s))


def _export_payload(job):
    data = {
        "id": str(job.id),
        "status": job.status,
        "size_bytes": job.size_bytes,
        "created_at": job.created_at.isoformat(),
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
    }
    return data


class MyDataExportView(V2APIView):
    """Signed-in user only; not org-scoped, so support sessions can't reach it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="My data exports")
    def get(self, request):
        rows = DataExportJob.objects.filter(user=request.user).order_by("-created_at")[:10]
        return Response({"results": [_export_payload(j) for j in rows]})

    @extend_schema(summary="Download a copy of my data (zip)")
    def post(self, request):
        if not storage.is_configured():
            return Response({"error": "not_implemented", "details": "Export storage is not configured"}, status=501)
        hour_ago = timezone.now() - timedelta(hours=1)
        if DataExportJob.objects.filter(user=request.user, created_at__gte=hour_ago).exclude(status="failed").exists():
            return Response({"error": "too_many_requests", "details": "One export an hour"}, status=429)
        job = DataExportJob.objects.create(user=request.user)
        result = jobs.request_export(job)
        if isinstance(result, dict) and result.get("ok") is False:
            job.status, job.error = "failed", "queue_unavailable"
            job.save(update_fields=["status", "error"])
            return Response({"error": "not_implemented", "details": "The job queue is not running"}, status=501)
        job.refresh_from_db()
        return Response(_export_payload(job), status=202)


class MyDataExportDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Export status and a short-lived download link")
    def get(self, request, export_id):
        job = get_object_or_404(DataExportJob, pk=export_id, user=request.user)
        data = _export_payload(job)
        if job.status == "succeeded" and job.expires_at and job.expires_at > timezone.now():
            data["download_url"] = storage.presign_get(job.storage_key, expires=300)
        return Response(data)


def _request_payload(r, with_person=True):
    data = {
        "id": str(r.id),
        "status": r.status,
        "reason": r.reason,
        "created_at": r.created_at.isoformat(),
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "summary": r.summary or {},
    }
    if with_person:
        data["user"] = {"id": str(r.user_id), "username": r.user.username}
    return data


class DeletionRequestListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Deletion requests: mine, or all of them for admins")
    def get(self, request, org_id):
        org = _org(request, org_id)
        qs = DeletionRequest.objects.filter(org=org).select_related("user").order_by("-created_at")
        if request.query_params.get("scope") == "all" and can(request.user, "org.members.manage", org):
            return Response({"results": [_request_payload(r) for r in qs[:200]]})
        return Response({"results": [_request_payload(r) for r in qs.filter(user=request.user)[:20]]})

    @extend_schema(summary="Ask the org to delete my data")
    def post(self, request, org_id):
        org = _org(request, org_id)
        if _impersonated(request):
            return Response({"error": "forbidden"}, status=403)
        membership = OrgMembership.objects.filter(org=org, user=request.user, employment_status=OrgMembership.STATUS_ACTIVE).first()
        if membership is None:  # platform staff and former members can't file here
            return Response({"error": "forbidden", "details": "Only members of this organization can ask"}, status=403)
        if membership.org_role == OrgMembership.ORG_ROLE_OWNER:
            return Response({"error": "conflict", "details": "Hand ownership to someone else first"}, status=409)
        if DeletionRequest.objects.filter(org=org, user=request.user, status="pending").exists():
            return Response({"error": "conflict", "details": "You already have a pending request"}, status=409)
        reason = _body(request).get("reason", "")
        if not isinstance(reason, str) or len(reason) > 1000:
            return _bad({"reason": "up to 1000 characters"})
        r = DeletionRequest.objects.create(org=org, user=request.user, reason=reason.strip())
        admins = OrgMembership.objects.filter(org=org, employment_status="active", org_role__in=["owner", "admin"]).exclude(user=request.user)
        Notification.objects.bulk_create(
            [Notification(org=org, user_id=m.user_id, kind="deletion_request", payload={"text": f"{request.user.username} asked to delete their data", "by": request.user.username, "link": "settings/retention"}) for m in admins]
        )
        audit(request.user, "privacy.deletion.request", target=r, request=request, org=org)
        return Response(_request_payload(r), status=201)


class DeletionRequestDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Approve (erases the person's data in this org) or reject a deletion request")
    def post(self, request, org_id, request_id):
        org = _org(request, org_id)
        decider = OrgMembership.objects.filter(org=org, user=request.user, employment_status=OrgMembership.STATUS_ACTIVE).exists()
        if not decider or not can(request.user, "org.members.manage", org) or _impersonated(request):
            return Response({"error": "forbidden"}, status=403)  # a real admin of this org, never platform staff from outside
        decision = _body(request).get("decision")
        if decision not in ("approve", "reject"):
            return _bad({"decision": "approve or reject"})
        with transaction.atomic():
            r = get_object_or_404(DeletionRequest.objects.select_for_update(), pk=request_id, org=org)
            if r.status != "pending":
                return Response({"error": "conflict", "details": "Already decided"}, status=409)
            if r.user_id == request.user.id:
                return Response({"error": "forbidden", "details": "Someone else decides your own request"}, status=403)
            if decision == "approve" and OrgMembership.objects.filter(org=org, user_id=r.user_id, org_role=OrgMembership.ORG_ROLE_OWNER).exists():
                return Response({"error": "conflict", "details": "They own the organization now. Ownership must move first"}, status=409)
            r.decided_by, r.decided_at = request.user, timezone.now()
            if decision == "reject":
                r.status = "rejected"
            else:
                r.summary = erase_member_data(org, r.user)
                r.status = "done"
            r.save()
        Notification.objects.create(org=org, user=r.user, kind="deletion_request_decided", payload={"text": f"Your deletion request was {'completed' if r.status == 'done' else 'rejected'}", "outcome": r.status})
        audit(request.user, f"privacy.deletion.{decision}", target=r, payload=r.summary, request=request, org=org)
        return Response(_request_payload(r))


class RetentionPolicyView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _policy(self, org):
        return RetentionPolicy.objects.filter(org=org).first() or RetentionPolicy(org=org)

    @extend_schema(summary="How long the org keeps messages, recordings, transcripts and time entries")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not can(request.user, "org.members.manage", org):
            return Response({"error": "forbidden"}, status=403)
        p = self._policy(org)
        return Response(
            {
                **{f: getattr(p, f) for f in RETENTION_FIELDS},
                "can_edit": can(request.user, "policy.manage", org),
                "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
                "last_run_summary": p.last_run_summary or {},
            }
        )

    @extend_schema(summary="Set retention (owner). Empty keeps data forever")
    def put(self, request, org_id):
        org = _org(request, org_id)
        if not can(request.user, "policy.manage", org) or _impersonated(request):
            return Response({"error": "forbidden"}, status=403)
        body, p = _body(request), self._policy(org)
        before = {f: getattr(p, f) for f in RETENTION_FIELDS}
        for f in RETENTION_FIELDS:
            if f in body:
                v = body[f]
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 7 <= v <= 3650):
                    return _bad({f: "empty, or 7 to 3650 days"})
                setattr(p, f, v)
        p.updated_by, p.updated_at = request.user, timezone.now()
        p.save()
        after = {f: getattr(p, f) for f in RETENTION_FIELDS}
        audit(request.user, "privacy.retention.update", target=org, payload={"before": before, "after": after}, request=request, org=org)
        return Response(after)
