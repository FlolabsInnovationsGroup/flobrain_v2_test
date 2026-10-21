from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import Organization, Project, Team
from organizations.permissions import HasPerm, IsActiveOrgMember, get_scoped_or_404
from organizations.services import audit
from tasks.models import ProjectTemplate, Task, TaskAssignment
from tasks.selectors import mission_control, my_tasks, visible_tasks
from tasks.services import assign_task, can_edit_task, move_task
from users.models import User


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _task_scope(task: Task):
    return {"org": task.org, "team": task.team, "project": task.project}


def _task_payload(task: Task):
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "due_on": task.due_on.isoformat() if task.due_on else None,
        "is_blocked": task.is_blocked,
        "assignees": [str(a.user_id) for a in task.assignments.all()],
    }


class TaskListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.view").has_permission(request, self)
        qs = Task.objects.filter(org=org).prefetch_related("assignments").order_by("-created_at")
        if request.query_params.get("mine") == "1":
            qs = my_tasks(org, request.user).prefetch_related("assignments")
        qs = visible_tasks(qs, request.user, org)
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_task_payload(t) for t in page])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.write").has_permission(request, self)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"error": "invalid", "details": "title is required"}, status=400)
        team = None
        if request.data.get("team"):
            team = get_object_or_404(Team, pk=request.data["team"], org=org)
            get_scoped_or_404(request.user, "task.write", team)
        task = Task.objects.create(
            org=org,
            title=title[:200],
            description=request.data.get("description") or "",
            created_by=request.user,
            project_id=request.data.get("project"),
            team=team,
        )
        TaskAssignment.objects.get_or_create(task=task, user=request.user)
        return Response(_task_payload(task), status=201)


class TaskDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        return Response(_task_payload(task))

    def patch(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        if not can_edit_task(request.user, task):
            return Response({"error": "permission_denied", "details": "Cannot edit this task"}, status=403)
        if "title" in request.data:
            task.title = str(request.data["title"])[:200]
        if "description" in request.data:
            task.description = request.data["description"]
        if "due_on" in request.data:
            task.due_on = request.data["due_on"] or None
        if "is_blocked" in request.data:
            task.is_blocked = bool(request.data["is_blocked"])
            task.blocked_reason = request.data.get("blocked_reason") or ""
        task.save()
        return Response(_task_payload(task))

    def delete(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.write").has_permission(request, self)
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.write", _task_scope(task))
        if not can_edit_task(request.user, task):
            return Response({"error": "permission_denied", "details": "Cannot delete this task"}, status=403)
        task.delete()
        return Response(status=204)


class TaskMoveView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        ok, reason = move_task(task, request.user, request.data.get("status") or "")
        if not ok:
            return Response({"error": reason, "details": reason}, status=403 if reason == "permission" else 400)
        return Response(_task_payload(task))


class TaskAssignView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        assignee = get_object_or_404(User, pk=request.data.get("user_id"))
        ok, reason = assign_task(task, request.user, assignee)
        if not ok:
            code = 404 if reason in {"inactive", "out_of_team"} else 403
            return Response({"error": reason, "details": "Cannot assign"}, status=code)
        task = Task.objects.prefetch_related("assignments").get(pk=task.pk)
        return Response(_task_payload(task))


class ProjectTemplateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.view").has_permission(request, self)
        rows = ProjectTemplate.objects.filter(org=org).order_by("name")
        return Response([{"id": str(r.id), "name": r.name, "spec": r.spec} for r in rows])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        tpl = ProjectTemplate.objects.create(
            org=org,
            name=request.data.get("name") or "Template",
            spec=request.data.get("spec") or {},
            created_by=request.user,
        )
        return Response({"id": str(tpl.id), "name": tpl.name}, status=201)


class ProjectFromTemplateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        tpl = get_object_or_404(ProjectTemplate, pk=request.data.get("template_id"), org=org)
        project = Project.objects.create(org=org, name=tpl.name)
        for item in (tpl.spec or {}).get("tasks", []):
            Task.objects.create(
                org=org,
                project=project,
                title=str(item.get("title") or "Task")[:200],
                created_by=request.user,
            )
        audit(request.user, "project.from_template", target=project, org=org, request=request)
        return Response({"id": str(project.id), "name": project.name}, status=201)


class MissionControlView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("mission.view").has_permission(request, self)
        team = None
        team_id = request.query_params.get("team")
        if team_id:
            team = get_object_or_404(Team, pk=team_id, org=org)
            get_scoped_or_404(request.user, "mission.view", team)
        return Response(mission_control(org, request.user, team=team))
