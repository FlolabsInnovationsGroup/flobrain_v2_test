"""Member skills and assignment suggestions (Phase 8e).

Skills: anyone in the org can read a member's skills; a member adds their own
(unconfirmed); a lead of one of their teams or an admin adds confirmed ones and
can remove any. Suggestions rank only people the requester may assign
(``assign_eligibility``). They are suggestions: the lead still assigns.
Flag ``assign_suggestions`` (501 when off).
"""

import re

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import MemberSkill, OrgMembership, Organization, SkillTag, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit

FLAG = "assign_suggestions"
WORD = re.compile(r"[\w+#.-]{2,}", re.UNICODE)


def _org(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("org.members.view").has_permission(request, view)
    return org


def _active_member(org, user_id):
    membership = OrgMembership.objects.filter(org=org, user_id=user_id).select_related("user").first()
    return membership if membership is not None and membership.is_active_member else None


def _can_confirm(actor, org, user_id) -> bool:
    membership = OrgMembership.objects.filter(org=org, user=actor).first()
    if membership and membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}:
        return True
    led = TeamMembership.objects.filter(team__org=org, user=actor, team_role=TeamMembership.ROLE_LEAD).values("team_id")
    return TeamMembership.objects.filter(team_id__in=led, user_id=user_id).exists()


def _skill_payload(row):
    return {"id": row.skill_id, "name": row.skill.name, "confirmed": row.confirmed_by_id is not None}


class MemberSkillListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="A member's skills")
    def get(self, request, org_id, user_id):
        org = _org(request, self, org_id)
        if _active_member(org, user_id) is None:
            return Response({"error": "not_found", "details": "Member not found"}, status=404)
        rows = MemberSkill.objects.filter(org=org, user_id=user_id).select_related("skill").order_by("skill__name")
        return Response([_skill_payload(r) for r in rows])

    @extend_schema(summary="Add a skill (your own, or confirmed by a lead or admin)")
    def post(self, request, org_id, user_id):
        org = _org(request, self, org_id)
        if _active_member(org, user_id) is None:
            return Response({"error": "not_found", "details": "Member not found"}, status=404)
        is_self = str(user_id) == str(request.user.id)
        confirm = _can_confirm(request.user, org, user_id)
        if not is_self and not confirm:
            return Response({"error": "permission_denied", "details": "Leads and admins add skills for others"}, status=403)
        name = " ".join(str((request.data or {}).get("name") or "").split())[:60]
        if not name:
            return Response({"error": "invalid", "details": "name is required"}, status=400)
        skill = SkillTag.objects.filter(org=org, name__iexact=name).order_by("id").first()
        if skill is None:
            try:
                with transaction.atomic():
                    skill = SkillTag.objects.create(org=org, name=name)
            except IntegrityError:
                skill = SkillTag.objects.filter(org=org, name__iexact=name).order_by("id").first()
        row, _ = MemberSkill.objects.get_or_create(org=org, user_id=user_id, skill=skill)
        if confirm and not is_self and row.confirmed_by_id is None:
            row.confirmed_by = request.user
            row.save(update_fields=["confirmed_by"])
        audit(request.user, "skill.add", target=row, payload={"skill": skill.name, "user": str(user_id)}, request=request, org=org)
        return Response(_skill_payload(row), status=201)


class MemberSkillDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Remove a skill")
    def delete(self, request, org_id, user_id, skill_id):
        org = _org(request, self, org_id)
        row = MemberSkill.objects.filter(org=org, user_id=user_id, skill_id=skill_id).first()
        if row is None:
            return Response({"error": "not_found", "details": "Skill not found"}, status=404)
        if str(user_id) != str(request.user.id) and not _can_confirm(request.user, org, user_id):
            return Response({"error": "permission_denied", "details": "Cannot remove this skill"}, status=403)
        audit(request.user, "skill.remove", target=row, payload={"user": str(user_id)}, request=request, org=org)
        row.delete()
        return Response(status=204)


def suggest(requester, org, task, limit=5) -> list[dict]:
    """Deterministic ranking: skill match, past done work in the team, minus open workload."""
    from tasks.models import Task, TaskAssignment
    from tasks.services import assign_eligibility

    words = {w.lower() for w in WORD.findall(f"{task.title} {task.description or ''}")}
    if task.team_id:
        candidate_ids = TeamMembership.objects.filter(team_id=task.team_id).values_list("user_id", flat=True)
    else:
        candidate_ids = OrgMembership.objects.filter(org=org).values_list("user_id", flat=True)
    memberships = OrgMembership.objects.filter(org=org, user_id__in=list(candidate_ids)).select_related("user")
    already = set(TaskAssignment.objects.filter(task=task).values_list("user_id", flat=True))
    open_load = dict(
        TaskAssignment.objects.filter(task__org=org)
        .exclude(task__status=Task.STATUS_DONE)
        .values_list("user_id")
        .annotate(n=Count("id"))
    )
    done_q = Q(task__status=Task.STATUS_DONE, task__org=org)
    if task.team_id:
        done_q &= Q(task__team_id=task.team_id)
    past_done = dict(TaskAssignment.objects.filter(done_q).values_list("user_id").annotate(n=Count("id")))
    skills = {}
    for row in MemberSkill.objects.filter(org=org, user_id__in=[m.user_id for m in memberships]).select_related("skill"):
        skills.setdefault(row.user_id, []).append(row)

    from organizations.permissions import can

    show_contact = can(requester, "org.members.view_contact", org)
    out = []
    for membership in memberships:
        user = membership.user
        if user.id in already or not membership.is_active_member:
            continue
        ok, _ = assign_eligibility(requester, org, user, task)
        if not ok:
            continue
        matched = []
        for row in skills.get(user.id, []):
            name = row.skill.name.lower()
            if name in words or any(part in words for part in WORD.findall(name)):
                matched.append((row.skill.name, row.confirmed_by_id is not None))
        skill_score = sum(3 if confirmed else 2 for _, confirmed in matched)
        history = min(past_done.get(user.id, 0), 5)
        load = open_load.get(user.id, 0)
        score = skill_score + history - load
        row = {"user_id": str(user.id), "username": user.username}
        if show_contact:
            row["email"] = user.email  # same rule as the member directory
        out.append(
            {
                **row,
                "score": score,
                "reasons": {
                    "matched_skills": [name for name, _ in matched],
                    "done_in_team": past_done.get(user.id, 0),
                    "open_tasks": load,
                },
            }
        )
    out.sort(key=lambda row: (-row["score"], row["reasons"]["open_tasks"], row["user_id"]))
    return out[:limit]


class TaskSuggestAssigneeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Suggest assignees for a task (the lead still decides)")
    def get(self, request, org_id, task_id):
        from organizations.permissions import get_scoped_or_404
        from tasks.models import Task

        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("task.write").has_permission(request, self)
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if not effective_flag(org, membership, FLAG, default=False):
            return Response({"error": "not_implemented", "details": "Assignment suggestions are not enabled"}, status=501)
        task = get_object_or_404(Task, pk=task_id, org=org)
        get_scoped_or_404(request.user, "task.view", {"org": org, "team": task.team, "project": task.project})
        return Response({"task": str(task.id), "suggestions": suggest(request.user, org, task)})
