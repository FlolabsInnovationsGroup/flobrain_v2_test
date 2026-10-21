"""Org memory export (Phase 17e): owner only (``exports.memory``).

``POST /orgs/{org}/exports/memory`` queues a zip built on the worker.
``GET /orgs/{org}/exports/memory`` lists exports; ``GET …/{id}`` returns a
5-minute download link while the export has not expired. All audited.
"""

from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from content_studio import storage
from core_v2.views import V2APIView
from exports import jobs
from exports.models import MemoryExport
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit


def _payload(e):
    return {
        "id": str(e.id),
        "status": e.status,
        "counts": e.counts,
        "size_bytes": e.size_bytes,
        "error": e.error,
        "created_at": e.created_at.isoformat(),
        "finished_at": e.finished_at.isoformat() if e.finished_at else None,
        "expires_at": e.expires_at.isoformat() if e.expires_at else None,
    }


def _gate(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("exports.memory").has_permission(request, view)
    return org


class MemoryExportListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Org memory exports (owner)")
    def get(self, request, org_id):
        org = _gate(request, self, org_id)
        return Response([_payload(e) for e in MemoryExport.objects.filter(org=org)[:50]])

    @extend_schema(summary="Export the org's team/project memory as a zip (owner)")
    def post(self, request, org_id):
        org = _gate(request, self, org_id)
        if not storage.is_configured():
            return Response({"error": "not_implemented", "details": "Export storage is not configured"}, status=501)
        busy = MemoryExport.objects.filter(org=org, status__in=[MemoryExport.STATUS_QUEUED, MemoryExport.STATUS_RUNNING]).exists()
        if busy:
            return Response({"error": "conflict", "details": "An export is already running"}, status=409)
        day = MemoryExport.objects.filter(org=org, created_at__gte=timezone.now() - timedelta(days=1)).count()
        if day >= int(getattr(settings, "EXPORT_MAX_PER_DAY", 3)):
            return Response({"error": "rate_limited", "details": "Too many exports today"}, status=429)
        export = MemoryExport.objects.create(org=org, requested_by=request.user)
        audit(request.user, "export.memory.request", target=export, request=request, org=org)
        jobs.request(export)
        export.refresh_from_db()
        return Response(_payload(export), status=202)


class MemoryExportDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Export status and a short-lived download link (owner)")
    def get(self, request, org_id, export_id):
        org = _gate(request, self, org_id)
        export = get_object_or_404(MemoryExport, pk=export_id, org=org)
        data = _payload(export)
        from console.impersonation import is_impersonated

        if is_impersonated(request):
            data["download_url"] = None  # support sessions never get the org's data out
        elif export.status == MemoryExport.STATUS_SUCCEEDED and export.expires_at and export.expires_at > timezone.now():
            data["download_url"] = storage.presign_get(export.storage_key, expires=300)
            audit(request.user, "export.memory.download", target=export, request=request, org=org)
        return Response(data)
