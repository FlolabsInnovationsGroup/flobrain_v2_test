from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from core_v2.views import V2APIView
from docs_app.models import Document
from meetings.models import Meeting
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, is_org_owner_or_admin
from rooms.models import Room
from tasks.models import Task
from tasks.selectors import visible_tasks


def _search_fields(qs, q, *fields):
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchVector

        return qs.annotate(_fts=SearchVector(*fields)).filter(_fts=q)
    query = Q()
    for field in fields:
        query |= Q(**{f"{field}__icontains": q})
    return qs.filter(query)


class GlobalSearchView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("search.use").has_permission(request, self)
        q = (request.query_params.get("q") or "").strip()
        types = {part.strip() for part in (request.query_params.get("types") or "rooms,tasks,docs,meetings").split(",") if part.strip()}
        results = []
        if not q:
            return Response({"results": []})
        scoped = not is_org_owner_or_admin(request.user, org)
        if "rooms" in types:
            rooms = Room.objects.filter(org=org)
            if scoped:
                rooms = rooms.filter(memberships__user=request.user)
            if connection.vendor == "postgresql":
                from django.contrib.postgres.search import SearchVector

                rooms = rooms.annotate(_fts=SearchVector("name")).filter(
                    Q(_fts=q) | Q(name__icontains=q) | Q(messages__body__icontains=q)
                )
            else:
                rooms = rooms.filter(Q(name__icontains=q) | Q(messages__body__icontains=q))
            rooms = rooms.distinct()[:10]
            results.extend({"type": "room", "id": str(row.id), "title": row.name} for row in rooms)
        if "tasks" in types:
            tasks = visible_tasks(_search_fields(Task.objects.filter(org=org), q, "title"), request.user, org)[:10]
            results.extend({"type": "task", "id": str(row.id), "title": row.title} for row in tasks)
        if "docs" in types:
            docs = Document.objects.filter(org=org)
            if scoped:
                docs = docs.filter(room__memberships__user=request.user)
            docs = _search_fields(docs, q, "title", "content_text").distinct()[:10]
            results.extend({"type": "doc", "id": str(row.id), "title": row.title} for row in docs)
        if "meetings" in types:
            meetings = _search_fields(Meeting.objects.filter(org=org), q, "title")
            if scoped:
                meetings = meetings.filter(room__memberships__user=request.user)
            results.extend({"type": "meeting", "id": str(row.id), "title": row.title} for row in meetings[:10])
        return Response({"results": results})
