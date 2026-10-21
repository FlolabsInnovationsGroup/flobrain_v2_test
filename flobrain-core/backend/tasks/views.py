from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import Organization, Project, Team
from organizations.permissions import HasPerm, IsActiveOrgMember, get_scoped_or_404
from organizations.permissions.engine import can
from organizations.services import audit
from tasks.models import ProjectTemplate, Task, TaskAssignment
from tasks.selectors import filter_tasks, mission_control, room_q, visible_tasks
from tasks.services import (
    EditContext,
    assign_task,
    can_delete_task,
    can_edit_task,
    can_set_due_date,
    can_use_project,
    create_task,
    display_name,
    log_activity,
    move_task,
    parse_due,
    resolve_room,
    set_blocked,
    unassign_task,
)
from users.models import User


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _uuid_or_none(value):
    """A bad id becomes a sentinel that matches nothing (404), never a 500."""
    import uuid

    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.UUID(int=0)


def _bad(details, code="validation_error"):
    return Response({"error": code, "details": details}, status=400)


def _task_scope(task: Task):
    return {"org": task.org, "team": task.team, "project": task.project}


def _task_payload(task: Task, ctx: EditContext | None = None, names: dict | None = None):
    assignments = list(task.assignments.all())
    if names is None:
        names = {a.user_id: display_name(a.user) for a in TaskAssignment.objects.filter(task=task).select_related("user")}
    data = {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "position": task.position,
        "due_on": task.due_on.isoformat() if task.due_on else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "is_blocked": task.is_blocked,
        "blocked_reason": task.blocked_reason,
        "blocked_since": task.blocked_since.isoformat() if task.blocked_since else None,
        "team": str(task.team_id) if task.team_id else None,
        "project": str(task.project_id) if task.project_id else None,
        "room": str(task.room_id) if task.room_id else None,
        "created_by": str(task.created_by_id) if task.created_by_id else None,
        "created_at": task.created_at.isoformat(),
        "assignees": [str(a.user_id) for a in assignments],
        "people": [{"id": str(a.user_id), "name": names.get(a.user_id, "")} for a in assignments],
    }
    if ctx is not None:
        data["can_edit"] = ctx.can_edit(task)
        data["can_delete"] = bool(ctx.can_delete(task))
    return data


def _payloads(tasks, user, org):
    tasks = list(tasks)
    ctx = EditContext(user, org)
    ids = {a.user_id for t in tasks for a in t.assignments.all()}
    names = {u.id: display_name(u) for u in User.objects.filter(pk__in=ids)}
    return [_task_payload(t, ctx, names) for t in tasks]


def _reload(task):
    return Task.objects.prefetch_related("assignments").select_related("org").get(pk=task.pk)


CREATE_ERRORS = {
    "invalid": (400, "validation_error", "Give the task a name."),
    "invalid_priority": (400, "validation_error", "Priority must be low, normal, high or urgent."),
    "due_required": (400, "validation_error", "Set a due date when you assign someone else."),
    "not_found": (404, "not_found", "Team, project or room not found"),
    "inactive": (404, "not_found", "That person is not an active member"),
    "out_of_team": (404, "not_found", "That person is not on the task's team"),
    "assign_others": (403, "permission_denied", "You can only assign tasks to yourself."),
    "permission": (403, "permission_denied", "Cannot create tasks"),
}


class TaskListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.view").has_permission(request, self)
        qs = Task.objects.filter(org=org)
        room_id = request.query_params.get("room")
        if room_id:
            room = resolve_room(request.user, org, _uuid_or_none(room_id))
            if room is None:
                return Response({"error": "not_found", "details": "Room not found"}, status=404)
            qs = qs.filter(room_q(room))
        qs, bad = filter_tasks(qs, request.user, request.query_params)
        if bad:
            return _bad(f"Unknown value for {bad}")
        qs = visible_tasks(qs, request.user, org).prefetch_related("assignments").order_by(
            "status", "position", "-created_at"
        )
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(_payloads(page, request.user, org))

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.write").has_permission(request, self)
        data = request.data if isinstance(request.data, dict) else None
        if data is None:
            return _bad("Send a JSON object")
        due = parse_due(data.get("due_on"))
        if due is False:
            return _bad("due_on must be a date (YYYY-MM-DD)")
        assignees = data.get("assignees")
        if assignees is not None and (not isinstance(assignees, list) or len(assignees) > 20):
            return _bad("assignees must be a list of up to 20 user ids")
        task, error = create_task(
            request.user,
            org,
            data.get("title"),
            description=data.get("description") or "",
            team_id=_uuid_or_none(data.get("team")),
            project_id=_uuid_or_none(data.get("project")),
            room_id=_uuid_or_none(data.get("room")),
            due_on=due,
            priority=data.get("priority") or None,
            assignee_ids=[_uuid_or_none(a) for a in assignees] if assignees else None,
        )
        if error:
            status, code, details = CREATE_ERRORS.get(error, CREATE_ERRORS["permission"])
            return Response({"error": code, "details": details}, status=status)
        return Response(_payloads([_reload(task)], request.user, org)[0], status=201)


class TaskDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task.objects.prefetch_related("assignments"), pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        payload = _payloads([task], request.user, org)[0]
        payload["activity"] = [
            {"verb": a.verb, "actor": str(a.actor_id) if a.actor_id else None, "payload": a.payload, "at": a.created_at.isoformat()}
            for a in task.activities.order_by("-created_at")[:30]
        ]
        return Response(payload)

    def patch(self, request, org_id, task_id):
        from organizations.models import Team as TeamModel

        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        if not can_edit_task(request.user, task):
            return Response({"error": "permission_denied", "details": "Cannot edit this task"}, status=403)
        data = request.data if isinstance(request.data, dict) else None
        if data is None:
            return _bad("Send a JSON object")
        changed = []
        if "title" in data:
            title = data["title"].strip() if isinstance(data["title"], str) else ""
            if not title:
                return _bad("Give the task a name.")
            task.title = title[:200]
            changed.append("title")
        if "description" in data:
            if not isinstance(data["description"], str):
                return _bad("description must be text")
            task.description = data["description"][:4000]
            changed.append("description")
        if "priority" in data:
            if data["priority"] not in Task.PRIORITIES:
                return _bad("Priority must be low, normal, high or urgent.")
            task.priority = data["priority"]
            changed.append("priority")
        if "due_on" in data:
            due = parse_due(data["due_on"])
            if due is False:
                return _bad("due_on must be a date (YYYY-MM-DD)")
            if due != task.due_on and not can_set_due_date(request.user, task):
                return Response(
                    {"error": "permission_denied", "details": "Only the team lead or an admin can change the due date of someone else's task."},
                    status=403,
                )
            task.due_on = due
            changed.append("due_on")
        if "team" in data:
            team_id = _uuid_or_none(data["team"])
            team = None
            if team_id:
                team = TeamModel.objects.filter(pk=team_id, org=org).first()
                if team is None or not can(request.user, "task.write", team):
                    return Response({"error": "not_found", "details": "Team not found"}, status=404)
            task.team = team
            changed.append("team")
        if "project" in data:
            project_id = _uuid_or_none(data["project"])
            project = None
            if project_id:
                project = Project.objects.filter(pk=project_id, org=org).first()
                if project is None or not can_use_project(request.user, project):
                    return Response({"error": "not_found", "details": "Project not found"}, status=404)
            task.project = project
            changed.append("project")
        if "is_blocked" in data:
            if not isinstance(data["is_blocked"], bool):
                return _bad("is_blocked must be true or false")
            reason = data.get("blocked_reason") or ""
            if not isinstance(reason, str):
                return _bad("blocked_reason must be text")
            if data["is_blocked"] and not reason.strip():
                return _bad("Say why the task is blocked.")
        elif "blocked_reason" in data and task.is_blocked:
            if not isinstance(data["blocked_reason"], str) or not data["blocked_reason"].strip():
                return _bad("Say why the task is blocked.")
            task.blocked_reason = data["blocked_reason"].strip()[:1000]
            changed.append("blocked_reason")
        if changed:
            task.save()
            log_activity(task, request.user, "edit", {"fields": changed})
        if "is_blocked" in data:
            set_blocked(task, request.user, data["is_blocked"], (data.get("blocked_reason") or "").strip())
        return Response(_payloads([_reload(task)], request.user, org)[0])

    def delete(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.write").has_permission(request, self)
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.write", _task_scope(task))
        if not can_delete_task(request.user, task):
            return Response({"error": "permission_denied", "details": "Only the creator, the team lead or an admin can delete this task."}, status=403)
        audit(request.user, "task.delete", target=task, payload={"title": task.title}, org=org, request=request)
        task.delete()
        return Response(status=204)


class TaskMoveView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        data = request.data if isinstance(request.data, dict) else {}
        status = data.get("status") or task.status
        before = data.get("before")
        if before is not None and before != "":
            before = _uuid_or_none(before)
        ok, reason = move_task(task, request.user, status, before=before or None, position=data.get("position"))
        if not ok:
            return Response({"error": reason, "details": reason}, status=403 if reason == "permission" else 400)
        return Response(_payloads([_reload(task)], request.user, org)[0])


class TaskAssignView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        assignee = get_object_or_404(User, pk=_uuid_or_none(request.data.get("user_id")))
        ok, reason = assign_task(task, request.user, assignee)
        if not ok:
            code = 404 if reason in {"inactive", "out_of_team"} else 403
            return Response({"error": reason, "details": "Cannot assign"}, status=code)
        return Response(_payloads([_reload(task)], request.user, org)[0])


class TaskUnassignView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, task_id):
        org = _org(org_id)
        request.org = org
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", _task_scope(task))
        HasPerm("task.write").has_permission(request, self)
        assignee = get_object_or_404(User, pk=_uuid_or_none(request.data.get("user_id")))
        ok, reason = unassign_task(task, request.user, assignee)
        if not ok:
            if reason == "not_assigned":
                return Response({"error": "not_found", "details": "That person is not on this task"}, status=404)
            return Response({"error": "permission_denied", "details": "Only the team lead or an admin can remove someone else"}, status=403)
        return Response(_payloads([_reload(task)], request.user, org)[0])


def _template_payload(tpl):
    tasks = (tpl.spec or {}).get("tasks", [])
    return {"id": str(tpl.id), "name": tpl.name, "spec": tpl.spec, "task_count": len(tasks) if isinstance(tasks, list) else 0}


def _clean_spec(spec):
    """Template spec: {"description": str, "tasks": [{"title", "priority"?, "due_in_days"?, "description"?}]}"""
    if spec is None:
        return {}, None
    if not isinstance(spec, dict):
        return None, "spec must be an object"
    tasks = spec.get("tasks", [])
    if not isinstance(tasks, list) or len(tasks) > 100:
        return None, "spec.tasks must be a list of up to 100 tasks"
    clean = []
    for item in tasks:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
            return None, "every template task needs a title"
        row = {"title": item["title"].strip()[:200]}
        if item.get("priority") is not None:
            if item["priority"] not in Task.PRIORITIES:
                return None, "template task priority must be low, normal, high or urgent"
            row["priority"] = item["priority"]
        if item.get("due_in_days") is not None:
            days = item["due_in_days"]
            if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 365:
                return None, "due_in_days must be a whole number from 0 to 365"
            row["due_in_days"] = days
        if isinstance(item.get("description"), str):
            row["description"] = item["description"][:4000]
        clean.append(row)
    out = {"tasks": clean}
    if isinstance(spec.get("description"), str):
        out["description"] = spec["description"][:2000]
    return out, None


class ProjectTemplateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.view").has_permission(request, self)
        rows = ProjectTemplate.objects.filter(org=org).order_by("name")
        return Response([_template_payload(r) for r in rows])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        name = request.data.get("name")
        if not isinstance(name, str) or not name.strip():
            return _bad("Give the template a name.")
        spec, error = _clean_spec(request.data.get("spec"))
        if error:
            return _bad(error)
        tpl = ProjectTemplate.objects.create(org=org, name=name.strip()[:200], spec=spec, created_by=request.user)
        audit(request.user, "project_template.create", target=tpl, org=org, request=request)
        return Response(_template_payload(tpl), status=201)


class ProjectFromTemplateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        from datetime import timedelta

        from django.utils import timezone

        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        tpl = get_object_or_404(ProjectTemplate, pk=_uuid_or_none(request.data.get("template_id")), org=org)
        name = request.data.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            return _bad("name must be text")
        team = None
        if request.data.get("team"):
            team = Team.objects.filter(pk=_uuid_or_none(request.data.get("team")), org=org).first()
            if team is None:
                return Response({"error": "not_found", "details": "Team not found"}, status=404)
        spec = tpl.spec or {}
        project = Project.objects.create(
            org=org,
            name=(name or tpl.name).strip()[:200],
            description=str(spec.get("description") or "")[:2000],
            lead=request.user,
        )
        if team is not None:
            project.teams.add(team)
        today = timezone.localdate()
        items = spec.get("tasks", []) if isinstance(spec.get("tasks", []), list) else []
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            days = item.get("due_in_days")
            task = Task.objects.create(
                org=org,
                project=project,
                team=team,
                title=str(item.get("title") or "Task")[:200],
                description=str(item.get("description") or "")[:4000],
                priority=item.get("priority") if item.get("priority") in Task.PRIORITIES else Task.PRIORITY_NORMAL,
                due_on=today + timedelta(days=days) if isinstance(days, int) and not isinstance(days, bool) else None,
                position=position,
                created_by=request.user,
            )
            log_activity(task, request.user, "create", {"template": str(tpl.id)})
        audit(request.user, "project.from_template", target=project, org=org, request=request)
        return Response({"id": str(project.id), "name": project.name, "tasks": len(items)}, status=201)


class MissionControlView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("mission.view").has_permission(request, self)
        team = None
        team_id = request.query_params.get("team")
        if team_id:
            team = get_object_or_404(Team, pk=_uuid_or_none(team_id), org=org)
            get_scoped_or_404(request.user, "mission.view", team)
        return Response(mission_control(org, request.user, team=team))
