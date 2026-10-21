"""Imports API (M6). Every endpoint: active member (403) -> flag ``imports`` (501) -> ``imports.run`` (403).

- ``GET  /orgs/{org}/imports/meta``: limits, rooms and teams to import into, Notion and Drive status
- ``GET  /orgs/{org}/imports``: history
- ``POST /orgs/{org}/imports/upload`` (multipart ``source`` = slack | notion_zip | files, ``file`` one
  or more): stores the upload privately and analyses it (preview)
- ``POST /orgs/{org}/imports/sample`` ``{source: slack|notion}``: the bundled demo export (demo org only)
- ``GET|DELETE /orgs/{org}/imports/{id}``; ``POST .../{id}/start`` ``{mapping}``; ``.../cancel``;
  ``.../resume``; ``.../undo``
- ``GET  /orgs/{org}/imports/notion/pages?connection_id=&q=``; ``POST /orgs/{org}/imports/notion``
  ``{connection_id, items: [{id, type}], room_id}``
- ``GET  /orgs/{org}/imports/drive/files?q=&page_token=``; ``POST /orgs/{org}/imports/drive``
  ``{file_ids, room_id}``
"""

import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core_v2.views import V2APIView
from imports import drive, notion, services, textract
from imports.jobs import ANALYZE_JOB, RUN_JOB, UNDO_JOB
from imports.models import ImportedObject, ImportRun
from imports.services import ImportFailure
from jobs.queue import enqueue
from organizations.models import Organization
from organizations.permissions import IsActiveOrgMember, can, is_org_owner_or_admin
from organizations.services.core import audit

UPLOAD_SOURCES = (ImportRun.SOURCE_SLACK, ImportRun.SOURCE_NOTION_ZIP, ImportRun.SOURCE_FILES)
NOTION_ID = re.compile(r"^[0-9a-fA-F-]{32,36}$")


def _err(code, details, status=400):
    return Response({"error": code, "details": details}, status=status)


def _failure(exc: ImportFailure):
    return _err(exc.code, exc.details, exc.status)


def _body(request):
    return request.data if hasattr(request.data, "get") else {}


def _impersonated(request) -> bool:
    from console.impersonation import is_impersonated

    return is_impersonated(request)


class ImportsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def gate(self, request, org_id, write=False):
        """Return (org, error). Flag off is 501; a missing permission is 403."""
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        if not services.flag_on(request.user, org):
            return org, _err("not_implemented", "Imports are not enabled", 501)
        if not can(request.user, services.PERM, org):
            raise PermissionDenied(f"Missing permission: {services.PERM}")
        if write and _impersonated(request):
            raise PermissionDenied("Support sessions can't run imports")
        return org, None

    def run(self, org, run_id):
        return ImportRun.objects.select_related("created_by").filter(org=org, pk=run_id).first()

    def busy(self, org):
        current = services.active_run(org)
        if current is not None:
            return _err("busy", "Another import is running. Wait for it to finish or cancel it", 409)
        return None


def _queue(job, payload, run, revert_status):
    """Enqueue a job. Without a worker (and outside eager mode) nothing would run it: say so."""
    result = enqueue(job, payload)
    if isinstance(result, dict) and result.get("reason") == "unavailable":
        ImportRun.objects.filter(pk=run.pk).update(status=revert_status)
        return _err("unavailable", "Background jobs are not running on this server", 503)
    return None


def _fresh(run):
    run.refresh_from_db()
    return services.run_payload(run, detail=True)


class MetaView(ImportsView):
    @extend_schema(summary="Import limits, places to import into, and Notion / Google Drive status")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        from connectors.models import Connection
        from organizations.models import Team
        from rooms.services import accessible_rooms

        rooms = accessible_rooms(request.user, org).filter(is_active=True).exclude(kind="direct").order_by("name")
        notion_conns = Connection.objects.filter(org=org, connector="notion", status=Connection.ACTIVE)
        conn, drive_status, drive_message = drive.connection(request.user, org)
        return Response({
            "max_upload_mb": services.max_upload_bytes() // (1024 * 1024),
            "max_files_per_upload": services.max_files_per_upload(),
            "max_file_mb": services.max_file_bytes() // (1024 * 1024),
            "drive_max_file_mb": drive.max_file_bytes() // (1024 * 1024),
            "pdf_supported": textract.pdf_supported(),
            "docx_supported": textract.docx_supported(),
            "file_types": sorted(textract.KINDS),
            "is_admin": is_org_owner_or_admin(request.user, org),
            "demo": services.is_demo_org(org),
            "rooms": [{"id": str(r.id), "name": r.name, "kind": r.kind} for r in rooms[:500]],
            "teams": [{"id": str(t.id), "name": t.name} for t in Team.objects.filter(org=org, is_active=True).order_by("name")[:500]],
            "notion": [
                {"id": str(c.id), "label": c.label or (c.config or {}).get("database_title") or "Notion", "simulated": (c.config or {}).get("demo") is True}
                for c in notion_conns
            ],
            "drive": {"status": drive_status, "message": drive_message, "simulated": bool(conn and conn.demo)},
            "active": services.run_payload(services.active_run(org)) if services.active_run(org) else None,
        })


class RunListView(ImportsView):
    @extend_schema(summary="Import history")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        runs = ImportRun.objects.filter(org=org).select_related("created_by")[:100]
        return Response({"results": [services.run_payload(r) for r in runs]})


class UploadView(ImportsView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(summary="Upload a Slack export, a Notion export, a Google Takeout ZIP or files")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        limit = services.max_upload_bytes()
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > limit + 1024 * 1024:  # refuse before reading the body
            return _err("too_large", f"Uploads can be at most {limit // (1024 * 1024)} MB", 413)
        busy = self.busy(org)
        if busy:
            return busy
        if ImportRun.objects.filter(org=org, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= int(getattr(settings, "IMPORTS_UPLOADS_PER_HOUR", 20)):
            return _err("rate_limited", "Too many imports this hour. Try again later", 429)
        source = str(_body(request).get("source") or "")
        if source not in UPLOAD_SOURCES:
            return _err("invalid", "source must be slack, notion_zip or files")
        uploads = request.FILES.getlist("file")
        if not uploads:
            return _err("invalid", "Attach a file")
        if source != ImportRun.SOURCE_FILES and len(uploads) != 1:
            return _err("invalid", "Upload one ZIP file")
        if len(uploads) > services.max_files_per_upload():
            return _err("invalid", f"Upload at most {services.max_files_per_upload()} files at once")
        if sum(u.size for u in uploads) > limit:
            return _err("too_large", f"Uploads can be at most {limit // (1024 * 1024)} MB", 413)
        for upload in uploads:
            name = upload.name or ""
            if source != ImportRun.SOURCE_FILES and not services.is_zip_name(name):
                return _err("invalid", "Upload the export as a .zip file")
            if source == ImportRun.SOURCE_FILES and not (services.is_zip_name(name) or textract.kind_of(name)):
                return _err("invalid", "Upload .zip, .docx, .pdf, .txt, .md, .csv or .html files")
        run = ImportRun.objects.create(org=org, source=source, created_by=request.user, label=(uploads[0].name or "")[:200])
        try:
            files = [services.store_upload(run, n, u) for n, u in enumerate(uploads)]
        except ImportFailure as exc:
            run.delete()
            return _failure(exc)
        ImportRun.objects.filter(pk=run.pk).update(files=files)
        audit(request.user, "imports.uploaded", target=run, request=request, org=org, payload={"source": source, "files": len(files), "bytes": sum(f["size"] for f in files)})
        queued = _queue(ANALYZE_JOB, {"run_id": str(run.id)}, run, ImportRun.FAILED)
        if queued:
            return queued
        return Response(_fresh(run), status=201)


class SampleView(ImportsView):
    @extend_schema(summary="Load the bundled demo export (demo workspace only, no network)")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        if not services.is_demo_org(org):
            return _err("demo_only", "Sample imports are only in the demo workspace", 403)
        kind = str(_body(request).get("source") or "")
        if kind not in services.SAMPLES:
            return _err("invalid", "source must be slack or notion")
        busy = self.busy(org)
        if busy:
            return busy
        folder, name = services.SAMPLES[kind]
        source = ImportRun.SOURCE_SLACK if kind == "slack" else ImportRun.SOURCE_NOTION_ZIP
        run = ImportRun.objects.create(
            org=org, source=source, created_by=request.user, label=name, is_demo=True,
            files=[{"key": services.FIXTURE_PREFIX + folder, "name": name, "size": len(services.fixture_zip(folder).getvalue())}],
        )
        audit(request.user, "imports.uploaded", target=run, request=request, org=org, payload={"source": source, "sample": True})
        queued = _queue(ANALYZE_JOB, {"run_id": str(run.id)}, run, ImportRun.FAILED)
        if queued:
            return queued
        return Response(_fresh(run), status=201)


class RunDetailView(ImportsView):
    @extend_schema(summary="One import: preview, mapping, progress and result")
    def get(self, request, org_id, run_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        run = self.run(org, run_id)
        if run is None:
            return _err("not_found", "Import not found", 404)
        return Response(services.run_payload(run, detail=True))

    @extend_schema(summary="Discard an import that has not added anything")
    def delete(self, request, org_id, run_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        run = self.run(org, run_id)
        if run is None:
            return _err("not_found", "Import not found", 404)
        if run.status in ImportRun.ACTIVE or ImportedObject.objects.filter(run=run).exists():
            return _err("conflict", "This import added things. Undo it instead", 409)
        services.delete_stored(run)
        audit(request.user, "imports.discarded", target=run, request=request, org=org, payload={"source": run.source})
        run.delete()
        return Response(status=204)


class StartView(ImportsView):
    @extend_schema(summary="Start an analysed import with the admin's choices")
    def post(self, request, org_id, run_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        run = self.run(org, run_id)
        if run is None:
            return _err("not_found", "Import not found", 404)
        if run.status != ImportRun.READY:
            return _err("conflict", "This import can't be started now", 409)
        data = _body(request).get("mapping")
        if not isinstance(data, dict):
            return _err("invalid", "mapping is required")
        try:
            if run.source == ImportRun.SOURCE_SLACK:
                mapping = services.clean_slack_mapping(request.user, org, run, data)
            else:
                mapping = services.clean_document_mapping(request.user, org, run, data)
        except ImportFailure as exc:
            return _failure(exc)
        with transaction.atomic():
            updated = ImportRun.objects.filter(pk=run.pk, status=ImportRun.READY).update(
                mapping=mapping, status=ImportRun.QUEUED, cancel_requested=False, error="", progress={"done": 0}
            )
        if not updated:
            return _err("conflict", "This import can't be started now", 409)
        n = len(mapping.get("channels") or mapping.get("refs") or [])
        audit(request.user, "imports.started", target=run, request=request, org=org, payload={"source": run.source, "selected": n})
        queued = _queue(RUN_JOB, {"run_id": str(run.id)}, run, ImportRun.READY)
        if queued:
            return queued
        return Response(_fresh(run), status=202)


class CancelView(ImportsView):
    @extend_schema(summary="Stop a running import (what is already in stays until you undo)")
    def post(self, request, org_id, run_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        run = self.run(org, run_id)
        if run is None:
            return _err("not_found", "Import not found", 404)
        if run.status not in (ImportRun.QUEUED, ImportRun.RUNNING, ImportRun.ANALYZING):
            return _err("conflict", "This import is not running", 409)
        ImportRun.objects.filter(pk=run.pk).update(cancel_requested=True)
        # Nothing has picked it up yet (or analysis): stop it right away.
        ImportRun.objects.filter(pk=run.pk, status__in=(ImportRun.QUEUED, ImportRun.ANALYZING), lease_until__isnull=True).update(
            status=ImportRun.CANCELLED, finished_at=timezone.now()
        )
        audit(request.user, "imports.cancel_requested", target=run, request=request, org=org, payload={"source": run.source})
        return Response(_fresh(run))


class ResumeView(ImportsView):
    @extend_schema(summary="Continue a failed or stopped import; what is already in is skipped")
    def post(self, request, org_id, run_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        run = self.run(org, run_id)
        if run is None:
            return _err("not_found", "Import not found", 404)
        if run.status not in (ImportRun.FAILED, ImportRun.CANCELLED) or not run.mapping:
            return _err("conflict", "Only a failed or stopped import can be resumed", 409)
        busy = self.busy(org)
        if busy:
            return busy
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.QUEUED, cancel_requested=False, error="", lease_until=None, finished_at=None)
        audit(request.user, "imports.resumed", target=run, request=request, org=org, payload={"source": run.source})
        queued = _queue(RUN_JOB, {"run_id": str(run.id)}, run, run.status)
        if queued:
            return queued
        return Response(_fresh(run), status=202)


class UndoView(ImportsView):
    @extend_schema(summary="Delete everything this import created")
    def post(self, request, org_id, run_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        run = self.run(org, run_id)
        if run is None:
            return _err("not_found", "Import not found", 404)
        if run.status not in (ImportRun.DONE, ImportRun.FAILED, ImportRun.CANCELLED):
            return _err("conflict", "Stop the import before undoing it", 409)
        busy = self.busy(org)
        if busy:
            return busy
        before = run.status
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.UNDOING)
        audit(request.user, "imports.undo_requested", target=run, request=request, org=org, payload={"source": run.source})
        queued = _queue(UNDO_JOB, {"run_id": str(run.id), "user_id": str(request.user.id)}, run, before)
        if queued:
            return queued
        return Response(_fresh(run), status=202)


def _notion_connection(org, connection_id):
    from connectors.models import Connection

    if not connection_id:
        return None
    try:
        return Connection.objects.filter(org=org, pk=connection_id, connector="notion", status=Connection.ACTIVE).first()
    except Exception:  # noqa: BLE001 - a malformed id is just "not found"
        return None


class NotionPagesView(ImportsView):
    @extend_schema(summary="Pages and databases the Notion integration can see")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        conn = _notion_connection(org, request.query_params.get("connection_id"))
        if conn is None:
            return _err("not_connected", "Connect Notion in Integrations first", 404)
        try:
            client = services.notion_client(conn)
            pages = client.search(str(request.query_params.get("q") or "")[:100])
        except ImportFailure as exc:
            return _failure(exc)
        except notion.NotionError as exc:
            return _err(exc.code, exc.details, 502 if exc.code in ("unreachable", "provider_error") else 400)
        return Response({"results": pages})


class NotionImportView(ImportsView):
    @extend_schema(summary="Import picked Notion pages and databases into a room as documents")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        data = _body(request)
        conn = _notion_connection(org, data.get("connection_id"))
        if conn is None:
            return _err("not_connected", "Connect Notion in Integrations first", 404)
        raw = data.get("items")
        if not isinstance(raw, list) or not raw or len(raw) > 200:
            return _err("invalid", "Pick between 1 and 200 pages")
        items = []
        for item in raw:
            if not isinstance(item, dict) or item.get("type") not in ("page", "database") or not NOTION_ID.match(str(item.get("id") or "")):
                return _err("invalid", "Each item needs a Notion id and a type (page or database)")
            items.append({"id": str(item["id"]).replace("-", "").lower(), "type": item["type"]})
        return self._start(request, org, ImportRun.SOURCE_NOTION_API, data, {"connection_id": str(conn.id), "items": items}, len(items), conn.label or "Notion")

    def _start(self, request, org, source, data, mapping, n, label):
        try:
            room = services.target_room(request.user, org, data.get("room_id"))
        except ImportFailure as exc:
            return _failure(exc)
        busy = self.busy(org)
        if busy:
            return busy
        run = ImportRun.objects.create(
            org=org, source=source, created_by=request.user, status=ImportRun.QUEUED, label=label[:200],
            mapping={**mapping, "room_id": str(room.id)}, preview={"totals": {"items": n}}, progress={"done": 0, "total": n},
        )
        audit(request.user, "imports.started", target=run, request=request, org=org, payload={"source": source, "selected": n})
        queued = _queue(RUN_JOB, {"run_id": str(run.id)}, run, ImportRun.FAILED)
        if queued:
            return queued
        return Response(_fresh(run), status=202)


class DriveFilesView(ImportsView):
    @extend_schema(summary="Google Docs, PDFs and Word files in the connected Google Drive")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        conn, status, message = drive.connection(request.user, org)
        if conn is None:
            return _err(status, message, 409)
        if conn.demo and not getattr(settings, "DEMO_MODE", False):
            return _err("demo_only", "Demo connection: imports are off outside demo mode", 409)
        try:
            listing = drive.list_files(conn, str(request.query_params.get("q") or "")[:100], str(request.query_params.get("page_token") or ""))
        except drive.DriveError as exc:
            return _err(exc.code, exc.details, 502 if exc.code in ("unreachable", "provider_error") else 400)
        return Response(listing)


class DriveImportView(NotionImportView):
    @extend_schema(summary="Import picked Google Drive files into a room as documents")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, write=True)
        if error:
            return error
        data = _body(request)
        conn, status, message = drive.connection(request.user, org)
        if conn is None:
            return _err(status, message, 409)
        ids = data.get("file_ids")
        if not isinstance(ids, list) or not ids or len(ids) > 200 or not all(isinstance(i, str) and drive.FILE_ID.match(i) for i in ids):
            return _err("invalid", "Pick between 1 and 200 files")
        ids = list(dict.fromkeys(ids))
        return self._start(request, org, ImportRun.SOURCE_DRIVE_API, data, {"file_ids": ids}, len(ids), "Google Drive")
