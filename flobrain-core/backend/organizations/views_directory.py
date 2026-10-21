from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import (
    OrgMembership,
    Organization,
    Project,
    Team,
    TeamMembership,
)
from organizations.permissions import (
    HasPerm,
    IsActiveOrgMember,
    can,
    get_scoped_or_404,
    is_org_owner_or_admin,
    visible_team_ids,
)
from organizations.services import audit
from organizations.services.members import change_member_status, register_member
from users.models import User


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _member_payload(viewer, membership):
    user = membership.user
    data = {
        "id": str(user.id),
        "username": user.username,
        "avatar_url": user.avatar_url,
        "user_type": user.user_type,
        "org_role": membership.org_role,
        "employment_status": membership.employment_status,
        "presence": membership.presence,
        "discord_handle": user.discord_handle,
        "linkedin_url": user.linkedin_url,
        "teams": list(
            TeamMembership.objects.filter(user=user, team__org=membership.org).values_list(
                "team__name", flat=True
            )
        ),
    }
    if can(viewer, "org.members.view_contact", membership.org):
        data["email"] = user.email
        data["phone"] = user.phone
    return data


class MemberListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        qs = (
            OrgMembership.objects.filter(org=org)
            .exclude(employment_status=OrgMembership.STATUS_PENDING)
            .select_related("user")
            .order_by("user__email")
        )
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_member_payload(request.user, m) for m in page])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.members.manage").has_permission(request, self)
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"error": "invalid", "details": "email is required"}, status=400)
        membership, user, _temp = register_member(
            org,
            request.user,
            email,
            org_role=request.data.get("org_role") or OrgMembership.ORG_ROLE_MEMBER,
            username=request.data.get("username") or "",
        )
        return Response(_member_payload(request.user, membership), status=status.HTTP_201_CREATED)


class MemberDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, user_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        membership = get_object_or_404(OrgMembership, org=org, user_id=user_id)
        if membership.employment_status == OrgMembership.STATUS_PENDING and not can(
            request.user, "org.members.manage", org
        ):
            return Response({"error": "not_found", "details": "Member not found"}, status=404)
        return Response(_member_payload(request.user, membership))

    def patch(self, request, org_id, user_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.members.manage").has_permission(request, self)
        user = get_object_or_404(User, pk=user_id)
        status_value = request.data.get("employment_status")
        if status_value:
            membership = change_member_status(
                org, request.user, user, status_value, reason=request.data.get("reason") or ""
            )
        else:
            membership = get_object_or_404(OrgMembership, org=org, user=user)
            if "org_role" in request.data:
                membership.org_role = request.data["org_role"]
                membership.save(update_fields=["org_role", "updated_at"])
        return Response(_member_payload(request.user, membership))


class TeamListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("team.view").has_permission(request, self)
        teams = Team.objects.filter(org=org).order_by("name")
        team_ids = visible_team_ids(request.user, org)
        if team_ids is not None:
            teams = teams.filter(id__in=team_ids)
        return Response([{"id": str(t.id), "name": t.name, "is_active": t.is_active} for t in teams])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("team.manage").has_permission(request, self)
        team = Team.objects.create(org=org, name=request.data.get("name") or "Untitled")
        audit(request.user, "team.create", target=team, org=org, request=request)
        return Response({"id": str(team.id), "name": team.name}, status=201)


class TeamDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        team = get_object_or_404(Team, pk=team_id, org=org)
        get_scoped_or_404(request.user, "team.view", team)
        return Response({"id": str(team.id), "name": team.name, "description": team.description})

    def patch(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        HasPerm("team.manage").has_permission(request, self)
        team = get_object_or_404(Team, pk=team_id, org=org)
        if "name" in request.data:
            team.name = request.data["name"]
        if "description" in request.data:
            team.description = request.data["description"]
        team.save()
        return Response({"id": str(team.id), "name": team.name})


class TeamMemberListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        team = get_object_or_404(Team, pk=team_id, org=org)
        get_scoped_or_404(request.user, "team.view", team)
        rows = TeamMembership.objects.filter(team=team).select_related("user")
        return Response(
            [{"user_id": str(r.user_id), "team_role": r.team_role, "username": r.user.username} for r in rows]
        )


class ProjectListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.view").has_permission(request, self)
        projects = Project.objects.filter(org=org).order_by("name")
        if not is_org_owner_or_admin(request.user, org):
            projects = projects.filter(
                Q(memberships__user=request.user) | Q(teams__memberships__user=request.user)
            ).distinct()
        return Response([{"id": str(p.id), "name": p.name, "status": p.status} for p in projects])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        project = Project.objects.create(org=org, name=request.data.get("name") or "Untitled")
        if request.data.get("lead"):
            project.lead_id = request.data["lead"]
            project.save(update_fields=["lead"])
        from rooms.services import ensure_project_room

        ensure_project_room(project)
        audit(request.user, "project.create", target=project, org=org, request=request)
        return Response({"id": str(project.id), "name": project.name}, status=201)


class ProjectDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, project_id):
        org = _org(org_id)
        request.org = org
        project = get_object_or_404(Project, pk=project_id, org=org)
        get_scoped_or_404(request.user, "project.view", project)
        return Response(
            {
                "id": str(project.id),
                "name": project.name,
                "status": project.status,
                "lead": str(project.lead_id) if project.lead_id else None,
            }
        )

    def patch(self, request, org_id, project_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        project = get_object_or_404(Project, pk=project_id, org=org)
        for field in ("name", "description", "status"):
            if field in request.data:
                setattr(project, field, request.data[field])
        project.save()
        return Response({"id": str(project.id), "name": project.name, "status": project.status})
