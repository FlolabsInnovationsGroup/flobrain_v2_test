from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core_v2.views import V2APIView
from docs_app.models import Document, DocumentRevision, StoredFile
from docs_app.serializers import DocumentWriteSerializer, FilePresignSerializer
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, is_org_owner_or_admin
from rooms.services import user_can_access_room
from rooms.views import _room_or_404


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _doc_payload(doc):
    return {
        "id": str(doc.id),
        "title": doc.title,
        "content_text": doc.content_text,
        "version": doc.version,
        "room": str(doc.room_id),
    }


class RoomDocListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        rows = Document.objects.filter(org=org, room=room).order_by("title")
        return Response([_doc_payload(row) for row in rows])

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
        )
        DocumentRevision.objects.create(
            document=doc, version=1, content_text=doc.content_text, created_by=request.user
        )
        return Response(_doc_payload(doc), status=201)


class DocumentDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        doc = get_object_or_404(Document, pk=doc_id, org=org)
        _room_or_404(request.user, org, doc.room_id)
        return Response(_doc_payload(doc))

    def patch(self, request, org_id, doc_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        doc = get_object_or_404(Document, pk=doc_id, org=org)
        _room_or_404(request.user, org, doc.room_id)
        serializer = DocumentWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        incoming = serializer.validated_data.get("version")
        if incoming is None or int(incoming) != doc.version:
            return Response({"error": "conflict", "details": "Document changed", "version": doc.version}, status=409)
        if "title" in serializer.validated_data:
            doc.title = serializer.validated_data["title"][:200]
        if "content_text" in serializer.validated_data:
            doc.content_text = serializer.validated_data["content_text"] or ""
        doc.version += 1
        doc.save()
        DocumentRevision.objects.create(
            document=doc, version=doc.version, content_text=doc.content_text, created_by=request.user
        )
        keep = getattr(settings, "FLOBRAIN_V2", {}).get("DOCUMENT_REVISIONS_KEPT", 50)
        extra = DocumentRevision.objects.filter(document=doc).order_by("-version")[keep:]
        DocumentRevision.objects.filter(pk__in=[row.pk for row in extra]).delete()
        return Response(_doc_payload(doc))


class DocumentSearchView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.view").has_permission(request, self)
        q = (request.query_params.get("q") or "").strip()
        qs = Document.objects.filter(org=org)
        if not is_org_owner_or_admin(request.user, org):
            qs = qs.filter(room__memberships__user=request.user)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content_text__icontains=q))
        return Response([_doc_payload(row) for row in qs.distinct()[:50]])


class FilePresignView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        serializer = FilePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = _room_or_404(request.user, org, serializer.validated_data["room"])
        stored = StoredFile.objects.create(
            org=org,
            room=room,
            name=serializer.validated_data["name"],
            content_type=serializer.validated_data.get("content_type") or "application/octet-stream",
            created_by=request.user,
        )
        return Response(
            {
                "id": str(stored.id),
                "upload_url": f"/local-uploads/{stored.id}",
                "method": "PUT",
            },
            status=201,
        )


class FileCompleteView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, file_id):
        org = _org(org_id)
        request.org = org
        HasPerm("docs.write").has_permission(request, self)
        stored = get_object_or_404(StoredFile, pk=file_id, org=org)
        if stored.room_id and not user_can_access_room(request.user, stored.room):
            raise NotFound()
        if stored.created_by_id != request.user.id and not is_org_owner_or_admin(request.user, org):
            raise NotFound()
        stored.status = StoredFile.STATUS_READY
        stored.local_path = f"local/{stored.id}/{stored.name}"
        stored.save(update_fields=["status", "local_path"])
        return Response({"id": str(stored.id), "status": stored.status, "url": f"/media/{stored.local_path}"})
