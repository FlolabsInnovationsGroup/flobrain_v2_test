"""Room docs (Phase 6): list, create, edit with optimistic locking, rename, delete, revisions with
restore, and file attachments.

- ``docs.view`` reads, ``docs.write`` creates and edits, in rooms the person can open (404 otherwise).
- Delete: ``docs.write`` and one of: owner/admin, the doc's author, the lead of the room's team,
  or the lead of the room's project (permission matrix: leads T, members S = own docs).
- Every save sends the ``version`` it started from. A stale version gets ``409`` with the
  current document, so the editor can show both and let the person choose. The update is a
  compare-and-set, so two saves racing on the same version cannot both win.
- Files: presign (room or document) → upload → complete. Only local storage exists (dev, tests,
  demo); without it presign answers 501 because S3 is not set up. Downloads are always
  ``attachment`` with ``nosniff`` so an uploaded file never runs as a page.
"""

import hashlib
import mimetypes
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core_v2.views import V2APIView
from docs_app.models import Document, DocumentRevision, StoredFile
from docs_app.serializers import DocumentWriteSerializer, FilePresignSerializer, RestoreSerializer
from organizations.models import Organization, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember, is_org_owner_or_admin
from organizations.permissions.engine import can
from organizations.services.core import audit
from rooms.services import user_can_access_room
from rooms.views import _room_or_404

ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _person(user):
    if user is None:
        return None
    return {"id": str(user.id), "name": user.username or user.email.split("@")[0]}


def _room_delete_rights(user, org, room) -> tuple[bool, bool]:
    """(may write docs here, may delete anyone's doc here). Worked out once per room."""
    if not can(user, "docs.write", room.team or org):
        return False, False
    if is_org_owner_or_admin(user, org):
        return True, True
    if room.team_id and TeamMembership.objects.filter(team_id=room.team_id, user=user, team_role=TeamMembership.ROLE_LEAD).exists():
        return True, True
    return True, bool(room.project_id and room.project.lead_id == user.id)


def _can_delete(user, org, doc, rights=None) -> bool:
    write, anyone = rights if rights is not None else _room_delete_rights(user, org, doc.room)
    return write and (anyone or doc.created_by_id == user.id)


def _doc_payload(doc, user=None, rights=None):
    data = {
        "id": str(doc.id),
        "title": doc.title,
        "content_text": doc.content_text,
        "version": doc.version,
        "room": str(doc.room_id),
        "created_by": _person(doc.created_by),
        "updated_by": _person(doc.updated_by or doc.created_by),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
    if user is not None:
        data["can_delete"] = _can_delete(user, doc.org, doc, rights)
    return data


def _docs():
    return Document.objects.select_related("created_by", "updated_by", "room", "room__project", "org")


def _visible_doc(request, org, doc_id):
    doc = get_object_or_404(_docs(), pk=doc_id, org=org)
    _room_or_404(request.user, org, doc.room_id)
    return doc


def _trim_revisions(doc):
    keep = getattr(settings, "FLOBRAIN_V2", {}).get("DOCUMENT_REVISIONS_KEPT", 50)
    extra = DocumentRevision.objects.filter(document=doc).order_by("-version")[keep:]
    DocumentRevision.objects.filter(pk__in=[row.pk for row in extra]).delete()


def _conflict(doc, user):
    doc = _docs().get(pk=doc.pk)
    return Response(
        {
            "error": "conflict",
            "details": "Someone saved a newer version of this document",
            "version": doc.version,
            "current": _doc_payload(doc, user),
        },
        status=409,
    )


def _save(doc, user, base_version, title, content_text):
    """Compare-and-set on ``version`` under a row lock. Returns the saved doc, or None when the
    version moved. ``save()`` (not ``update()``) so the knowledge index hears about the change."""
    with transaction.atomic():
        locked = Document.objects.select_for_update().get(pk=doc.pk)
        if locked.version != base_version:
            return None
        locked.title, locked.content_text = title, content_text
        locked.version, locked.updated_by = base_version + 1, user
        locked.save()
        DocumentRevision.objects.create(document=doc, version=locked.version, content_text=content_text, created_by=user)
        _trim_revisions(doc)
    return _docs().get(pk=doc.pk)


class RoomDocListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        rows = _docs().filter(org=org, room=room).order_by("title")
        rights = _room_delete_rights(request.user, org, room)
        return Response([_doc_payload(row, request.user, rights) for row in rows])

    def post(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        serializer = DocumentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = (serializer.validated_data.get("title") or "").strip() or "Untitled"
        doc = Document.objects.create(
            org=org,
            room=room,
            title=title[:200],
            content_text=serializer.validated_data.get("content_text") or "",
            created_by=request.user,
            updated_by=request.user,
        )
        DocumentRevision.objects.create(document=doc, version=1, content_text=doc.content_text, created_by=request.user)
        audit(request.user, "doc.create", target=doc, payload={"room": str(room.id)}, request=request, org=org)
        return Response(_doc_payload(_docs().get(pk=doc.pk), request.user), status=201)


class DocumentDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        return Response(_doc_payload(_visible_doc(request, org, doc_id), request.user))

    def patch(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        doc = _visible_doc(request, org, doc_id)
        serializer = DocumentWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        incoming = data.get("version")
        if incoming is None:
            return Response({"error": "invalid", "details": {"version": ["version is required"]}}, status=400)
        if int(incoming) != doc.version:
            return _conflict(doc, request.user)
        title = doc.title
        if "title" in data:
            title = (data["title"] or "").strip()[:200]
            if not title:
                return Response({"error": "invalid", "details": {"title": ["A document needs a title"]}}, status=400)
        content = data["content_text"] if "content_text" in data else doc.content_text
        content = content or ""
        if title == doc.title and content == doc.content_text:
            return Response(_doc_payload(doc, request.user))  # nothing changed: no new version
        saved = _save(doc, request.user, doc.version, title, content)
        if saved is None:
            return _conflict(doc, request.user)
        if title != doc.title:
            audit(request.user, "doc.rename", target=saved, request=request, org=org)
        return Response(_doc_payload(saved, request.user))

    def delete(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        doc = _visible_doc(request, org, doc_id)
        if not _can_delete(request.user, org, doc):
            return Response(
                {"error": "permission_denied", "details": "Only the author, a lead of this room or an admin can delete this document"},
                status=403,
            )
        files = list(StoredFile.objects.filter(document=doc))
        audit(request.user, "doc.delete", target=doc, payload={"title": doc.title, "room": str(doc.room_id)}, request=request, org=org)
        doc.delete()
        for stored in files:
            _remove_blob(stored)
        return Response(status=204)


class DocumentRevisionListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        doc = _visible_doc(request, org, doc_id)
        rows = DocumentRevision.objects.filter(document=doc).select_related("created_by").order_by("-version")
        return Response(
            [
                {
                    "version": row.version,
                    "created_by": _person(row.created_by),
                    "created_at": row.created_at.isoformat(),
                    "chars": len(row.content_text),
                    "current": row.version == doc.version,
                }
                for row in rows
            ]
        )


class DocumentRevisionDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, doc_id, version):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        doc = _visible_doc(request, org, doc_id)
        row = get_object_or_404(DocumentRevision.objects.select_related("created_by"), document=doc, version=version)
        return Response(
            {
                "version": row.version,
                "content_text": row.content_text,
                "created_by": _person(row.created_by),
                "created_at": row.created_at.isoformat(),
            }
        )


class DocumentRestoreView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, doc_id, version):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        doc = _visible_doc(request, org, doc_id)
        serializer = RestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = get_object_or_404(DocumentRevision, document=doc, version=version)
        if serializer.validated_data["version"] != doc.version:
            return _conflict(doc, request.user)
        saved = _save(doc, request.user, doc.version, doc.title, row.content_text)
        if saved is None:
            return _conflict(doc, request.user)
        audit(request.user, "doc.restore", target=saved, payload={"from_version": version, "version": saved.version}, request=request, org=org)
        return Response(_doc_payload(saved, request.user))


class DocumentSearchView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        q = (request.query_params.get("q") or "").strip()
        from rooms.services import accessible_rooms

        qs = _docs().filter(org=org, room__in=accessible_rooms(request.user, org))
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content_text__icontains=q))
        return Response([_doc_payload(row) for row in qs.distinct()[:50]])


# --- files ---------------------------------------------------------------------------------------


def storage_mode() -> str:
    """``local`` when files can be stored on this server's disk (dev, tests, demo), else ``""``."""
    explicit = (getattr(settings, "DOCS_FILE_STORAGE", "") or "").strip()
    if explicit:
        return explicit if explicit == "local" else ""
    if getattr(settings, "DEBUG", False) or getattr(settings, "TESTING", False) or getattr(settings, "DEMO_MODE", False):
        return "local"
    return ""


def _root() -> Path:
    configured = getattr(settings, "DOCS_LOCAL_STORAGE_DIR", "") or ""
    return Path(configured) if configured else Path(settings.BASE_DIR) / "media" / "docs"  # git-ignored


def max_upload_bytes() -> int:
    return int(getattr(settings, "DOCS_MAX_UPLOAD_MB", 25)) * 1024 * 1024


def _blob_path(stored) -> Path:
    # Only server-made ids in the path: the uploaded name lives in the database.
    return _root() / str(stored.org_id) / str(stored.id)


def _remove_blob(stored):
    try:
        _blob_path(stored).unlink(missing_ok=True)
    except OSError:
        pass


def _content_type(name, given):
    ctype = (given or "").split(";")[0].strip().lower()
    if not ctype or ctype == "application/octet-stream":
        ctype = (mimetypes.guess_type(name)[0] or "").lower()
        if name.lower().endswith(".md"):
            ctype = "text/markdown"
    return ctype


def _file_payload(stored, org_id):
    return {
        "id": str(stored.id),
        "name": stored.name,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "status": stored.status,
        "document": str(stored.document_id) if stored.document_id else None,
        "created_by": _person(stored.created_by),
        "created_at": stored.created_at.isoformat(),
        "download_url": f"/api/v2/orgs/{org_id}/files/{stored.id}/download" if stored.status == StoredFile.STATUS_READY else None,
    }


def _own_file(request, org, file_id):
    stored = get_object_or_404(StoredFile.objects.select_related("room", "created_by"), pk=file_id, org=org)
    if stored.room_id and not user_can_access_room(request.user, stored.room):
        raise NotFound()
    if stored.created_by_id != request.user.id and not is_org_owner_or_admin(request.user, org):
        raise NotFound()
    return stored


class FilePresignView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        serializer = FilePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        doc = None
        if data.get("document"):
            doc = _visible_doc(request, org, data["document"])
            room = doc.room
        else:
            room = _room_or_404(request.user, org, data["room"])
        if storage_mode() != "local":
            return Response({"error": "not_configured", "details": "File storage (S3) is not set up on this server"}, status=501)
        ctype = _content_type(data["name"], data.get("content_type"))
        if ctype not in ALLOWED_TYPES:
            return Response({"error": "invalid", "details": {"content_type": ["This file type is not allowed"]}}, status=400)
        if data.get("size") is not None and data["size"] > max_upload_bytes():
            return Response({"error": "invalid", "details": {"size": [f"Files can be at most {max_upload_bytes() // (1024 * 1024)} MB"]}}, status=400)
        stored = StoredFile.objects.create(org=org, room=room, document=doc, name=data["name"], content_type=ctype, created_by=request.user)
        return Response(
            {
                "id": str(stored.id),
                "upload_url": f"/api/v2/orgs/{org.id}/files/{stored.id}/upload",
                "method": "POST",
                "field": "file",
                "max_bytes": max_upload_bytes(),
            },
            status=201,
        )


class FileUploadView(V2APIView):
    """Local storage stand-in for the presigned S3 PUT. Only the uploader, only while pending."""

    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, file_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        if storage_mode() != "local":
            return Response({"error": "not_configured", "details": "File storage (S3) is not set up on this server"}, status=501)
        stored = _own_file(request, org, file_id)
        if stored.created_by_id != request.user.id:
            raise NotFound()
        if stored.status != StoredFile.STATUS_PENDING:
            return Response({"error": "conflict", "details": "This file is already uploaded"}, status=409)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"error": "invalid", "details": {"file": ["Attach the file as 'file'"]}}, status=400)
        if upload.size > max_upload_bytes():
            return Response({"error": "invalid", "details": {"file": [f"Files can be at most {max_upload_bytes() // (1024 * 1024)} MB"]}}, status=400)
        path = _blob_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with open(path, "wb") as out:
            for chunk in upload.chunks():
                size += len(chunk)
                if size > max_upload_bytes():
                    out.close()
                    path.unlink(missing_ok=True)
                    return Response({"error": "invalid", "details": {"file": ["The file is too large"]}}, status=400)
                digest.update(chunk)
                out.write(chunk)
        StoredFile.objects.filter(pk=stored.pk).update(local_path=f"{stored.org_id}/{stored.id}", size_bytes=size, sha256=digest.hexdigest())
        return Response({"id": str(stored.id), "size_bytes": size, "status": stored.status})


class FileCompleteView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, file_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        stored = _own_file(request, org, file_id)
        if stored.status != StoredFile.STATUS_READY:
            if not stored.local_path or not _blob_path(stored).is_file():
                return Response({"error": "not_uploaded", "details": "Upload the file before completing it"}, status=409)
            stored.status = StoredFile.STATUS_READY
            stored.save(update_fields=["status"])
            if stored.document_id:
                audit(request.user, "doc.attach", target=stored, payload={"document": str(stored.document_id)}, request=request, org=org)
        return Response({**_file_payload(stored, org.id), "url": _file_payload(stored, org.id)["download_url"]})


class DocumentFileListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        doc = _visible_doc(request, org, doc_id)
        rows = StoredFile.objects.filter(document=doc, status=StoredFile.STATUS_READY).select_related("created_by").order_by("created_at")
        return Response({"storage": storage_mode() or "not_configured", "max_bytes": max_upload_bytes(), "results": [_file_payload(f, org.id) for f in rows]})


class FileDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _visible(self, request, org, file_id):
        stored = get_object_or_404(StoredFile.objects.select_related("room", "document", "created_by"), pk=file_id, org=org)
        if not stored.room_id or not user_can_access_room(request.user, stored.room):
            raise NotFound()
        if stored.status != StoredFile.STATUS_READY and stored.created_by_id != request.user.id:
            raise NotFound()
        return stored

    def delete(self, request, org_id, file_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        stored = self._visible(request, org, file_id)
        allowed = stored.created_by_id == request.user.id or is_org_owner_or_admin(request.user, org)
        if not allowed and stored.document_id:
            allowed = _can_delete(request.user, org, _docs().get(pk=stored.document_id))
        if not allowed:
            return Response({"error": "permission_denied", "details": "Only the uploader, a lead of this room or an admin can remove this file"}, status=403)
        audit(request.user, "doc.detach", target=stored, payload={"document": str(stored.document_id) if stored.document_id else None}, request=request, org=org)
        _remove_blob(stored)
        stored.delete()
        return Response(status=204)


class FileDownloadView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, file_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        stored = FileDetailView()._visible(request, org, file_id)
        path = _blob_path(stored)
        if stored.status != StoredFile.STATUS_READY or not path.is_file():
            raise NotFound()
        response = FileResponse(open(path, "rb"), as_attachment=True, filename=stored.name, content_type=stored.content_type or "application/octet-stream")
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-store"
        return response
