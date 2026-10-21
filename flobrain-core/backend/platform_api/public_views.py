"""Public REST API v1 (Phase 14b): ``/api/public/v1/``, personal access tokens only.

Every view reuses the app's own selectors, so a token never sees more than
its owner can see in FloBrain right now.
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from core_v2.errors import v2_exception_handler
from platform_api.authentication import HasPAT, PATAuthentication, require_scope


class PATUserThrottle(SimpleRateThrottle):
    """Per user across all their tokens (20 tokens must not mean 20x the rate)."""

    scope = "pat_user"

    def get_rate(self):
        return getattr(settings, "PUBLIC_API_USER_RATE", "300/min")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": str(request.user.id) if request.auth else "anon"}


class PATThrottle(SimpleRateThrottle):
    scope = "pat"

    def get_rate(self):
        return getattr(settings, "PUBLIC_API_RATE", "120/min")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": str(request.auth.id) if request.auth else "anon"}


class PublicView(APIView):
    authentication_classes = [PATAuthentication]
    permission_classes = [HasPAT]
    throttle_classes = [PATThrottle, PATUserThrottle]

    def get_exception_handler(self):
        return v2_exception_handler

    @property
    def org(self):
        return self.request.auth.org


def _task(t):
    return {
        "id": str(t.id),
        "title": t.title,
        "status": t.status,
        "due_on": t.due_on.isoformat() if t.due_on else None,
        "team": str(t.team_id) if t.team_id else None,
        "project": str(t.project_id) if t.project_id else None,
        "assignees": [str(a.user_id) for a in t.assignments.all()],
    }


class MeView(PublicView):
    @extend_schema(summary="The token's owner and org", tags=["public"])
    def get(self, request):
        return Response({"user": str(request.user.id), "username": request.user.username, "org": str(self.org.id), "scopes": request.auth.scopes})


class TaskListView(PublicView):
    @extend_schema(summary="Tasks the owner can see", tags=["public"])
    def get(self, request):
        from tasks.models import Task
        from tasks.selectors import visible_tasks

        require_scope(request, "tasks:read")
        qs = visible_tasks(Task.objects.filter(org=self.org), request.user, self.org).prefetch_related("assignments")
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return Response({"results": [_task(t) for t in qs.order_by("-created_at")[:200]]})

    @extend_schema(summary="Create a task as the owner", tags=["public"])
    def post(self, request):
        import uuid

        from tasks.services import create_task

        require_scope(request, "tasks:write")

        def _id(v):
            try:
                return uuid.UUID(str(v)) if v else None
            except ValueError:
                return uuid.UUID(int=0)

        data = request.data if isinstance(request.data, dict) else {}
        if not isinstance(data.get("title"), str) or not isinstance(data.get("description", ""), str):
            return Response({"error": "invalid", "details": "title and description must be text"}, status=400)
        task, error = create_task(
            request.user, self.org, data.get("title"), description=data.get("description") or "",
            team_id=_id(data.get("team")), project_id=_id(data.get("project")),
        )
        if error == "invalid":
            return Response({"error": "invalid", "details": "title is required"}, status=400)
        if error == "not_found":
            return Response({"error": "not_found", "details": "Team or project not found"}, status=404)
        if error:
            return Response({"error": "permission_denied", "details": "Cannot create tasks"}, status=403)
        return Response(_task(task), status=201)


class TaskDetailView(PublicView):
    @extend_schema(summary="One task", tags=["public"])
    def get(self, request, task_id):
        from tasks.models import Task
        from tasks.selectors import visible_tasks

        require_scope(request, "tasks:read")
        task = visible_tasks(Task.objects.filter(org=self.org, pk=task_id), request.user, self.org).first()
        if task is None:
            return Response({"error": "not_found", "details": "Task not found"}, status=404)
        return Response(_task(task))


class RoomListView(PublicView):
    @extend_schema(summary="Rooms the owner can read now", tags=["public"])
    def get(self, request):
        from rooms.services import accessible_rooms

        require_scope(request, "rooms:read")
        rows = accessible_rooms(request.user, self.org).filter(is_active=True).order_by("name")[:200]
        return Response({"results": [{"id": str(r.id), "name": r.name, "kind": r.kind} for r in rows]})


class RoomMessagesView(PublicView):
    @extend_schema(summary="Recent messages of a room the owner can read", tags=["public"])
    def get(self, request, room_id):
        from rooms.models import Room, RoomMessage
        from rooms.services import user_can_access_room

        require_scope(request, "rooms:read")
        room = Room.objects.filter(org=self.org, pk=room_id).first()
        if room is None or not user_can_access_room(request.user, room):
            return Response({"error": "not_found", "details": "Room not found"}, status=404)
        rows = RoomMessage.objects.filter(room=room, deleted_at__isnull=True).order_by("-created_at")[:100]
        return Response(
            {"results": [{"id": str(m.id), "author": str(m.author_id) if m.author_id else None, "body": m.body, "created_at": m.created_at.isoformat()} for m in rows]}
        )


class TimeEntriesView(PublicView):
    @extend_schema(summary="The owner's own time entries", tags=["public"])
    def get(self, request):
        from timetracking.models import TimeEntry

        require_scope(request, "time:read")
        rows = TimeEntry.objects.filter(org=self.org, user=request.user).order_by("-started_at")[:500]
        return Response(
            {
                "results": [
                    {
                        "id": str(e.id),
                        "task": str(e.task_id) if e.task_id else None,
                        "started_at": e.started_at.isoformat(),
                        "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                    }
                    for e in rows
                ]
            }
        )
