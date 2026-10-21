"""Directory, members, teams and projects (Phase 1).

Rules (spec 5.2, Decisions 6 to 8):
- Everyone in the org sees the directory (name, avatar, teams, presence, skills). Contact details
  need ``org.members.view_contact``. Pending members are hidden unless you manage members.
- Registering and changing status: ``org.members.manage`` for anyone, or a team lead for members
  of a team they lead (registering only into that team, only as ``member``).
- Promoting to admin, or to lead of a team: owner/admin only. Nobody but the owner touches the owner,
  and nobody changes their own role or status here.
- Teams and projects: ``team.manage`` / ``project.manage`` create, archive and set leads; the lead of
  a team or project edits its details and its plain members.
"""

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import CharField, Count, Q, Value
from django.db.models.functions import Coalesce, Lower
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import (
    MemberSkill,
    OrgMembership,
    Organization,
    Project,
    ProjectMembership,
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

ADMIN_ROLES = {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}
STATUS_VALUES = {choice for choice, _ in OrgMembership.STATUS_CHOICES}
PRESENCE_VALUES = {choice for choice, _ in OrgMembership.PRESENCE_CHOICES}
# Directory filter values (Decision 6) plus every employment status.
STATUS_FILTERS = {"all", "active", "inactive"} | PRESENCE_VALUES | STATUS_VALUES
ROLE_FILTERS = {"owner", "admin", "member", "lead"}


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _bad(details, code="invalid", status_code=400):
    return Response({"error": code, "details": details}, status=status_code)


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def led_team_ids(user, org) -> set:
    return set(
        TeamMembership.objects.filter(user=user, team__org=org, team_role=TeamMembership.ROLE_LEAD).values_list(
            "team_id", flat=True
        )
    )


def lead_of_member(actor, org, target_user_id) -> bool:
    """The actor leads a team the target is on."""
    led = led_team_ids(actor, org)
    return bool(led) and TeamMembership.objects.filter(team_id__in=led, user_id=target_user_id).exists()


def _brief(user):
    if user is None:
        return None
    return {"id": str(user.id), "username": user.username or ""}


def _member_rows(viewer, org, memberships):
    """Payload for a page of memberships with three extra queries (teams, skills, contact check)."""
    memberships = list(memberships)
    user_ids = [m.user_id for m in memberships]
    teams = {}
    for row in (
        TeamMembership.objects.filter(user_id__in=user_ids, team__org=org)
        .select_related("team")
        .order_by("team__name")
    ):
        teams.setdefault(row.user_id, []).append(row)
    skills = {}
    for row in MemberSkill.objects.filter(org=org, user_id__in=user_ids).select_related("skill").order_by("skill__name"):
        skills.setdefault(row.user_id, []).append(row)
    show_contact = can(viewer, "org.members.view_contact", org)
    manager = can(viewer, "org.members.manage", org)
    out = []
    for membership in memberships:
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
            "about_me": user.about_me,
            "timezone": user.timezone,
            "teams": [row.team.name for row in teams.get(user.id, [])],
            "team_roles": [
                {"id": str(row.team_id), "name": row.team.name, "role": row.team_role, "is_active": row.team.is_active}
                for row in teams.get(user.id, [])
            ],
            "is_lead": any(row.team_role == TeamMembership.ROLE_LEAD for row in teams.get(user.id, [])),
            "skills": [{"id": row.skill_id, "name": row.skill.name, "confirmed": row.confirmed_by_id is not None} for row in skills.get(user.id, [])],
        }
        if show_contact:
            data["email"] = user.email
            data["phone"] = user.phone
        if manager:
            data["status_reason"] = membership.status_reason
            data["status_changed_at"] = membership.status_changed_at.isoformat() if membership.status_changed_at else None
            data["internship_tier"] = membership.internship_tier
        out.append(data)
    return out


def _member_payload(viewer, membership):
    return _member_rows(viewer, membership.org, [membership])[0]


def _visible_projects_q(viewer, org):
    if is_org_owner_or_admin(viewer, org):
        return Q()
    return Q(memberships__user=viewer) | Q(teams__memberships__user=viewer) | Q(lead=viewer)


class MemberListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        params = request.query_params
        qs = OrgMembership.objects.filter(org=org).select_related("user")
        status_filter = (params.get("status") or "all").strip().lower()
        if status_filter not in STATUS_FILTERS:
            return _bad(f"status must be one of {', '.join(sorted(STATUS_FILTERS))}")
        if status_filter == OrgMembership.STATUS_PENDING:
            if not can(request.user, "org.members.manage", org):
                return _bad("Only people who manage members can list pending members", "permission_denied", 403)
            qs = qs.filter(employment_status=OrgMembership.STATUS_PENDING)
        else:
            qs = qs.exclude(employment_status=OrgMembership.STATUS_PENDING)
            if status_filter == "active":
                qs = qs.filter(employment_status=OrgMembership.STATUS_ACTIVE)
            elif status_filter == "inactive":
                qs = qs.exclude(employment_status=OrgMembership.STATUS_ACTIVE)
            elif status_filter in PRESENCE_VALUES:
                qs = qs.filter(presence=status_filter)
            elif status_filter in STATUS_VALUES:
                qs = qs.filter(employment_status=status_filter)
        team = params.get("team")
        if team:
            team_id = _uuid_or_none(team)
            if team_id is None:
                return _bad("team must be a team id")
            qs = qs.filter(user__team_memberships__team_id=team_id, user__team_memberships__team__org=org)
        role = (params.get("role") or "").strip().lower()
        if role:
            if role not in ROLE_FILTERS:
                return _bad("role must be owner, admin, member or lead")
            if role == "lead":
                qs = qs.filter(
                    user__team_memberships__team__org=org,
                    user__team_memberships__team_role=TeamMembership.ROLE_LEAD,
                )
            else:
                qs = qs.filter(org_role=role)
        skill = (params.get("skill") or "").strip()
        if skill:
            skill_q = Q(user__member_skills__skill__name__iexact=skill)
            if skill.isdigit():
                skill_q |= Q(user__member_skills__skill_id=int(skill))
            qs = qs.filter(skill_q, user__member_skills__org=org)
        q = " ".join((params.get("q") or "").split())[:100]
        if q:
            match = Q(user__username__icontains=q)
            if can(request.user, "org.members.view_contact", org):
                match |= Q(user__email__icontains=q)  # only people who can see emails search by them
            qs = qs.filter(match)
        ordering = (params.get("ordering") or "name").strip()
        if ordering not in {"name", "-name"}:
            return _bad("ordering must be name or -name")
        qs = qs.annotate(sort_name=Lower(Coalesce("user__username", "user__email", Value(""), output_field=CharField()))).distinct()
        qs = qs.order_by("-sort_name" if ordering == "-name" else "sort_name", "user_id")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(_member_rows(request.user, org, page))

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        body = _body(request)
        manager = can(request.user, "org.members.manage", org)
        team = None
        if body.get("team_id"):
            team_id = _uuid_or_none(body.get("team_id"))
            team = Team.objects.filter(pk=team_id, org=org).first() if team_id else None
            if team is None:
                return _bad({"team_id": "Pick a team in this organization"})
            if not team.is_active:
                return _bad({"team_id": "That team is archived"})
        is_lead_here = team is not None and team.id in led_team_ids(request.user, org)
        if not manager and not is_lead_here:
            # Same denial as before for people who manage nobody.
            HasPerm("org.members.manage").has_permission(request, self)
            return _bad("You can register people only into a team you lead", "permission_denied", 403)
        email = str(body.get("email") or "").strip().lower()
        if not email:
            return _bad("email is required")
        try:
            validate_email(email)
        except DjangoValidationError:
            return _bad({"email": "Enter a valid email address"})
        org_role = body.get("org_role") or OrgMembership.ORG_ROLE_MEMBER
        if org_role not in {OrgMembership.ORG_ROLE_MEMBER, OrgMembership.ORG_ROLE_ADMIN}:
            return _bad({"org_role": "org_role must be member or admin"})
        if org_role == OrgMembership.ORG_ROLE_ADMIN and not is_org_owner_or_admin(request.user, org):
            return _bad("Only the owner or an admin can register an admin", "permission_denied", 403)
        team_role = body.get("team_role") or TeamMembership.ROLE_MEMBER
        if team_role not in {TeamMembership.ROLE_MEMBER, TeamMembership.ROLE_LEAD}:
            return _bad({"team_role": "team_role must be member or lead"})
        if team_role == TeamMembership.ROLE_LEAD and not is_org_owner_or_admin(request.user, org):
            return _bad("Only the owner or an admin can make someone a team lead", "permission_denied", 403)
        activate = body.get("activate", False)
        if not isinstance(activate, bool):
            return _bad({"activate": "true or false"})
        username = " ".join(str(body.get("username") or "").split())[:150]
        if OrgMembership.objects.filter(org=org, user__email__iexact=email).exists():
            return _bad("This person is already in the organization", "conflict", 409)

        from billing_v2.entitlements import seat_blocked, seat_error

        with transaction.atomic():
            seats = seat_blocked(org, email=email)
            if seats is not None:
                return Response(seat_error(org, seats), status=409)
            membership, user, _temp = register_member(org, request.user, email, org_role=org_role, username=username)
            if team is not None:
                TeamMembership.objects.get_or_create(team=team, user=user, defaults={"team_role": team_role})
            if activate:
                membership = change_member_status(org, request.user, user, OrgMembership.STATUS_ACTIVE, reason="Registered")
        return Response(_member_payload(request.user, membership), status=status.HTTP_201_CREATED)


class MemberDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, user_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        membership = get_object_or_404(OrgMembership.objects.select_related("user", "org"), org=org, user_id=user_id)
        if membership.employment_status == OrgMembership.STATUS_PENDING and not can(
            request.user, "org.members.manage", org
        ):
            return Response({"error": "not_found", "details": "Member not found"}, status=404)
        data = _member_payload(request.user, membership)
        projects = (
            Project.objects.filter(org=org)
            .filter(Q(memberships__user_id=user_id) | Q(teams__memberships__user_id=user_id) | Q(lead_id=user_id))
            .filter(_visible_projects_q(request.user, org))
            .distinct()
            .order_by("name")
        )
        data["projects"] = [
            {"id": str(p.id), "name": p.name, "status": p.status, "is_lead": str(p.lead_id) == str(user_id)} for p in projects
        ]
        actor = OrgMembership.objects.filter(org=org, user=request.user).first()
        data["can"] = {
            "change_status": _may_change_status(request.user, org, actor, membership),
            "change_role": _may_change_role(request.user, org, actor, membership),
            "confirm_skills": str(request.user.id) != str(user_id)
            and (is_org_owner_or_admin(request.user, org) or lead_of_member(request.user, org, user_id)),
        }
        return Response(data)

    def patch(self, request, org_id, user_id):
        org = _org(org_id)
        request.org = org
        body = _body(request)
        membership = OrgMembership.objects.filter(org=org, user_id=user_id).select_related("user").first()
        manager = can(request.user, "org.members.manage", org)
        if membership is None:
            if not manager and not led_team_ids(request.user, org):
                HasPerm("org.members.manage").has_permission(request, self)
            return Response({"error": "not_found", "details": "Member not found"}, status=404)
        actor = OrgMembership.objects.filter(org=org, user=request.user).first()
        wants_status = "employment_status" in body
        wants_role = "org_role" in body
        wants_tier = "internship_tier" in body
        if not (wants_status or wants_role or wants_tier):
            if not manager and not lead_of_member(request.user, org, user_id):
                HasPerm("org.members.manage").has_permission(request, self)
            return _bad("Nothing to change: send employment_status, org_role or internship_tier")
        if str(user_id) == str(request.user.id):
            return _bad("You can't change your own status or role", "permission_denied", 403)
        if wants_status and not _may_change_status(request.user, org, actor, membership):
            HasPerm("org.members.manage").has_permission(request, self)
            return _bad("You can't change this person's status", "permission_denied", 403)
        if (wants_role or wants_tier) and not _may_change_role(request.user, org, actor, membership):
            return _bad("Only the owner or an admin changes roles", "permission_denied", 403)

        status_value = body.get("employment_status")
        if wants_status and status_value not in STATUS_VALUES - {OrgMembership.STATUS_PENDING}:
            return _bad({"employment_status": "Use active, paused, graduated, terminated or offboarding"})
        role_value = body.get("org_role")
        if wants_role and role_value not in {OrgMembership.ORG_ROLE_ADMIN, OrgMembership.ORG_ROLE_MEMBER}:
            return _bad({"org_role": "org_role must be admin or member. Ownership can't be moved here"})
        tier = body.get("internship_tier")
        if wants_tier and tier not in (None, 1, 2, 3):
            return _bad({"internship_tier": "1, 2, 3 or null"})
        reason = str(body.get("reason") or "")[:500]

        if wants_status and status_value != membership.employment_status:
            from billing_v2.entitlements import NOT_COUNTED, seat_blocked, seat_error

            with transaction.atomic():
                current = OrgMembership.objects.get(pk=membership.pk)
                if current.employment_status in NOT_COUNTED and status_value not in NOT_COUNTED:
                    seats = seat_blocked(org, adding_user_id=membership.user_id)
                    if seats is not None:
                        return Response(seat_error(org, seats), status=409)
                membership = change_member_status(org, request.user, membership.user, status_value, reason=reason)
        if wants_role and role_value != membership.org_role:
            before = membership.org_role
            membership.org_role = role_value
            membership.save(update_fields=["org_role", "updated_at"])
            audit(request.user, "member.role", target=membership, org=org, request=request, payload={"from": before, "to": role_value})
        if wants_tier and tier != membership.internship_tier:
            membership.internship_tier = tier
            membership.save(update_fields=["internship_tier", "updated_at"])
            audit(request.user, "member.tier", target=membership, org=org, request=request, payload={"tier": tier})
        membership.refresh_from_db()
        return Response(_member_payload(request.user, membership))


def _may_change_status(user, org, actor, membership) -> bool:
    if actor is None and not getattr(user, "is_platform_admin", False):
        return False
    if str(membership.user_id) == str(user.id):
        return False
    if membership.org_role == OrgMembership.ORG_ROLE_OWNER:
        return bool(actor and actor.org_role == OrgMembership.ORG_ROLE_OWNER)
    if can(user, "org.members.manage", org):
        if membership.org_role == OrgMembership.ORG_ROLE_ADMIN:
            return is_org_owner_or_admin(user, org)
        return True
    # Decision 8: a lead changes the status of plain members of a team they lead.
    return membership.org_role == OrgMembership.ORG_ROLE_MEMBER and lead_of_member(user, org, membership.user_id)


def _may_change_role(user, org, actor, membership) -> bool:
    if str(membership.user_id) == str(user.id) or not is_org_owner_or_admin(user, org):
        return False
    if membership.org_role == OrgMembership.ORG_ROLE_OWNER:
        return False  # the owner's seat is not changed here
    return True


# --- Teams -------------------------------------------------------------------------------------


def _clean_name(raw, field="name"):
    name = " ".join(str(raw or "").split())
    if not name:
        raise ValueError(f"{field} is required")
    if len(name) > 200:
        raise ValueError(f"{field} is at most 200 characters")
    return name


def _team_payload(team, viewer=None, counts=None, leads=None):
    data = {
        "id": str(team.id),
        "name": team.name,
        "description": team.description,
        "is_active": team.is_active,
    }
    if counts is not None:
        data["member_count"] = counts.get(team.id, 0)
    if leads is not None:
        data["leads"] = leads.get(team.id, [])
    return data


def _team_extras(teams):
    ids = [t.id for t in teams]
    counts = dict(TeamMembership.objects.filter(team_id__in=ids).values_list("team_id").annotate(n=Count("id")))
    leads = {}
    for row in TeamMembership.objects.filter(team_id__in=ids, team_role=TeamMembership.ROLE_LEAD).select_related("user"):
        leads.setdefault(row.team_id, []).append(_brief(row.user))
    return counts, leads


def _can_edit_team(user, team) -> bool:
    return can(user, "team.manage", team) or TeamMembership.objects.filter(
        team=team, user=user, team_role=TeamMembership.ROLE_LEAD
    ).exists()


class TeamListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("team.view").has_permission(request, self)
        teams = Team.objects.filter(org=org).order_by("name")
        scope = request.query_params.get("scope")
        team_ids = visible_team_ids(request.user, org)
        # ``scope=all`` lists every team's name (directory filters, register form); details stay scoped.
        if team_ids is not None and scope != "all":
            teams = teams.filter(id__in=team_ids)
        teams = list(teams)
        counts, leads = _team_extras(teams)
        mine = dict(
            TeamMembership.objects.filter(user=request.user, team__in=teams).values_list("team_id", "team_role")
        )
        rows = []
        for t in teams:
            row = _team_payload(t, counts=counts, leads=leads)
            row["my_role"] = mine.get(t.id)
            rows.append(row)
        return Response(rows)

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("team.manage").has_permission(request, self)
        body = _body(request)
        try:
            name = _clean_name(body.get("name"))
        except ValueError as exc:
            return _bad({"name": str(exc)})
        if Team.objects.filter(org=org, name__iexact=name).exists():
            return _bad({"name": "A team with this name already exists"}, "conflict", 409)
        description = str(body.get("description") or "")[:2000]
        lead = None
        if body.get("lead_id"):
            lead = _active_member_user(org, body.get("lead_id"))
            if lead is None:
                return _bad({"lead_id": "The lead must be an active member of this organization"})
        try:
            with transaction.atomic():
                team = Team.objects.create(org=org, name=name, description=description)
        except IntegrityError:
            return _bad({"name": "A team with this name already exists"}, "conflict", 409)
        if lead is not None:
            TeamMembership.objects.create(team=team, user=lead, team_role=TeamMembership.ROLE_LEAD)
        audit(request.user, "team.create", target=team, org=org, request=request, payload={"name": name})
        counts, leads = _team_extras([team])
        return Response(_team_payload(team, counts=counts, leads=leads), status=201)


class TeamDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        team = get_object_or_404(Team, pk=team_id, org=org)
        get_scoped_or_404(request.user, "team.view", team)
        counts, leads = _team_extras([team])
        data = _team_payload(team, counts=counts, leads=leads)
        data["can_edit"] = _can_edit_team(request.user, team)
        data["can_manage"] = can(request.user, "team.manage", team)
        return Response(data)

    def patch(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        team = Team.objects.filter(pk=team_id, org=org).first()
        manager = team is not None and can(request.user, "team.manage", team)
        if team is None or not (manager or _can_edit_team(request.user, team)):
            HasPerm("team.manage").has_permission(request, self)
            return Response({"error": "not_found", "details": "Team not found"}, status=404)
        body = _body(request)
        changed = {}
        if "name" in body:
            try:
                name = _clean_name(body["name"])
            except ValueError as exc:
                return _bad({"name": str(exc)})
            if Team.objects.filter(org=org, name__iexact=name).exclude(pk=team.pk).exists():
                return _bad({"name": "A team with this name already exists"}, "conflict", 409)
            team.name = name
            changed["name"] = name
        if "description" in body:
            team.description = str(body["description"] or "")[:2000]
            changed["description"] = True
        if "is_active" in body:
            if not manager:
                return _bad("Only admins archive teams", "permission_denied", 403)
            if not isinstance(body["is_active"], bool):
                return _bad({"is_active": "true or false"})
            team.is_active = body["is_active"]
            changed["is_active"] = team.is_active
        if not changed:
            return _bad("Nothing to change")
        team.save()
        action = "team.archive" if changed.get("is_active") is False else "team.update"
        audit(request.user, action, target=team, org=org, request=request, payload=changed)
        counts, leads = _team_extras([team])
        return Response(_team_payload(team, counts=counts, leads=leads))


def _active_member_user(org, user_id):
    uid = _uuid_or_none(user_id)
    if uid is None:
        return None
    membership = (
        OrgMembership.objects.filter(org=org, user_id=uid, employment_status=OrgMembership.STATUS_ACTIVE)
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


def _hours(value):
    if value is None or value == "":
        return None
    try:
        hours = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("weekly_target_hours must be a number of hours")
    if not hours.is_finite() or hours < 0 or hours > 168:
        raise ValueError("weekly_target_hours must be between 0 and 168")
    return hours.quantize(Decimal("0.01"))


def _task_target(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 1000:
        raise ValueError("weekly_task_target must be a whole number between 0 and 1000")
    return value


def _team_member_row(row):
    return {
        "user_id": str(row.user_id),
        "team_role": row.team_role,
        "username": row.user.username,
        "weekly_target_hours": str(row.weekly_target_hours) if row.weekly_target_hours is not None else None,
        "weekly_task_target": row.weekly_task_target,
        "joined_at": row.joined_at.isoformat(),
    }


class TeamMemberListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        team = get_object_or_404(Team, pk=team_id, org=org)
        get_scoped_or_404(request.user, "team.view", team)
        rows = TeamMembership.objects.filter(team=team).select_related("user")
        status_filter = request.query_params.get("status")
        statuses = dict(OrgMembership.objects.filter(org=org, user_id__in=[r.user_id for r in rows]).values_list("user_id", "employment_status"))
        out = []
        for r in sorted(rows, key=lambda r: (r.user.username or r.user.email or "").lower()):
            item = _team_member_row(r)
            item["employment_status"] = statuses.get(r.user_id)
            if status_filter == "active" and item["employment_status"] != OrgMembership.STATUS_ACTIVE:
                continue
            if status_filter == "inactive" and item["employment_status"] == OrgMembership.STATUS_ACTIVE:
                continue
            out.append(item)
        return Response(out)

    def post(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        team = Team.objects.filter(pk=team_id, org=org).first()
        if team is None or not _can_edit_team(request.user, team):
            HasPerm("team.manage").has_permission(request, self)
            return Response({"error": "not_found", "details": "Team not found"}, status=404)
        body = _body(request)
        user = _active_member_user(org, body.get("user_id"))
        if user is None:
            return _bad({"user_id": "Pick an active member of this organization"})
        role = body.get("team_role") or TeamMembership.ROLE_MEMBER
        if role not in {TeamMembership.ROLE_MEMBER, TeamMembership.ROLE_LEAD}:
            return _bad({"team_role": "team_role must be member or lead"})
        if role == TeamMembership.ROLE_LEAD and not is_org_owner_or_admin(request.user, org):
            return _bad("Only the owner or an admin makes someone a team lead", "permission_denied", 403)
        try:
            hours = _hours(body.get("weekly_target_hours"))
            tasks_target = _task_target(body.get("weekly_task_target"))
        except ValueError as exc:
            return _bad(str(exc))
        if TeamMembership.objects.filter(team=team, user=user).exists():
            return _bad("This person is already on the team", "conflict", 409)
        if not can(request.user, "team.manage", team) and not is_org_owner_or_admin(request.user, org):
            # A lead adds people who are on no team yet. Moving someone from another team is for admins:
            # being on a lead's team gives that lead status changes and team views over the person.
            if TeamMembership.objects.filter(team__org=org, user=user).exists():
                return _bad("This person is already on another team. An admin can move them.", "permission_denied", 403)
        row = TeamMembership.objects.create(
            team=team, user=user, team_role=role, weekly_target_hours=hours, weekly_task_target=tasks_target
        )
        audit(request.user, "team.member.add", target=team, org=org, request=request, payload={"user": str(user.id), "role": role})
        return Response(_team_member_row(row), status=201)


class TeamMemberDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _row(self, request, org_id, team_id, user_id):
        org = _org(org_id)
        request.org = org
        team = Team.objects.filter(pk=team_id, org=org).first()
        if team is None or not _can_edit_team(request.user, team):
            HasPerm("team.manage").has_permission(request, self)
            return org, None, None
        row = TeamMembership.objects.filter(team=team, user_id=user_id).select_related("user").first()
        return org, team, row

    def patch(self, request, org_id, team_id, user_id):
        org, team, row = self._row(request, org_id, team_id, user_id)
        if row is None:
            return Response({"error": "not_found", "details": "Not on this team"}, status=404)
        body = _body(request)
        changed = {}
        admin = is_org_owner_or_admin(request.user, org)
        if "team_role" in body:
            role = body["team_role"]
            if role not in {TeamMembership.ROLE_MEMBER, TeamMembership.ROLE_LEAD}:
                return _bad({"team_role": "team_role must be member or lead"})
            if role != row.team_role and not admin:
                return _bad("Only the owner or an admin changes who leads a team", "permission_denied", 403)
            row.team_role = role
            changed["team_role"] = role
        try:
            if "weekly_target_hours" in body:
                row.weekly_target_hours = _hours(body["weekly_target_hours"])
                changed["weekly_target_hours"] = str(row.weekly_target_hours) if row.weekly_target_hours is not None else None
            if "weekly_task_target" in body:
                row.weekly_task_target = _task_target(body["weekly_task_target"])
                changed["weekly_task_target"] = row.weekly_task_target
        except ValueError as exc:
            return _bad(str(exc))
        if not changed:
            return _bad("Nothing to change")
        if row.team_role == TeamMembership.ROLE_LEAD and "team_role" not in changed and not admin and str(row.user_id) != str(request.user.id):
            return _bad("Only the owner or an admin changes another lead's targets", "permission_denied", 403)
        row.save()
        if "team_role" in changed:
            from organizations.services import sync_user_type

            sync_user_type(row.user)
        audit(request.user, "team.member.update", target=team, org=org, request=request, payload={"user": str(row.user_id), **changed})
        return Response(_team_member_row(row))

    def delete(self, request, org_id, team_id, user_id):
        org, team, row = self._row(request, org_id, team_id, user_id)
        if row is None:
            return Response({"error": "not_found", "details": "Not on this team"}, status=404)
        if row.team_role == TeamMembership.ROLE_LEAD and not is_org_owner_or_admin(request.user, org):
            return _bad("Only the owner or an admin removes a team lead", "permission_denied", 403)
        user = row.user
        row.delete()
        from organizations.services import sync_user_type
        from rooms.services import ensure_team_room

        ensure_team_room(team)  # the team room follows the team
        sync_user_type(user)
        audit(request.user, "team.member.remove", target=team, org=org, request=request, payload={"user": str(user.id)})
        return Response(status=204)


# --- Projects ----------------------------------------------------------------------------------

PROJECT_STATUSES = {choice for choice, _ in Project.STATUS_CHOICES}


def _date_or_error(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{field} must be a date like 2026-10-21")


def _project_payload(project, viewer=None, with_members=False):
    data = {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "lead": str(project.lead_id) if project.lead_id else None,
        "lead_user": _brief(project.lead) if project.lead_id else None,
        "teams": [{"id": str(t.id), "name": t.name} for t in project.teams.all().order_by("name")],
        "starts_on": project.starts_on.isoformat() if project.starts_on else None,
        "due_on": project.due_on.isoformat() if project.due_on else None,
    }
    direct = ProjectMembership.objects.filter(project=project, source=ProjectMembership.SOURCE_DIRECT).select_related("user")
    data["direct_member_count"] = direct.count()
    if with_members:
        data["members"] = [_brief(row.user) for row in direct.order_by("user__username")]
    return data


def _can_edit_project(user, project) -> bool:
    return can(user, "project.manage", project) or (project.lead_id is not None and str(project.lead_id) == str(user.id))


def _apply_project_fields(project, body, org, manager):
    """Validate and set fields. Raises ValueError (400) or PermissionError (403). Returns changed keys."""
    changed = {}
    if "name" in body:
        project.name = _clean_name(body["name"])
        changed["name"] = project.name
    if "description" in body:
        project.description = str(body["description"] or "")[:4000]
        changed["description"] = True
    if "starts_on" in body:
        project.starts_on = _date_or_error(body["starts_on"], "starts_on")
        changed["starts_on"] = True
    if "due_on" in body:
        project.due_on = _date_or_error(body["due_on"], "due_on")
        changed["due_on"] = True
    if project.starts_on and project.due_on and project.due_on < project.starts_on:
        raise ValueError("due_on can't be before starts_on")
    if "status" in body:
        if body["status"] not in PROJECT_STATUSES:
            raise ValueError("status must be active, paused, done or archived")
        if not manager and body["status"] != project.status:
            raise PermissionError("Only admins change a project's status")
        project.status = body["status"]
        changed["status"] = project.status
    if "lead" in body or "lead_id" in body:
        raw = body.get("lead_id", body.get("lead"))
        if not manager:
            raise PermissionError("Only admins set a project's lead")
        if raw in (None, ""):
            project.lead = None
        else:
            lead = _active_member_user(org, raw)
            if lead is None:
                raise ValueError("The lead must be an active member of this organization")
            project.lead = lead
        changed["lead"] = str(project.lead_id) if project.lead_id else None
    return changed


def _project_team_ids(org, raw):
    if not isinstance(raw, list) or len(raw) > 50:
        raise ValueError("team_ids must be a list of team ids")
    ids = [_uuid_or_none(v) for v in raw]
    if any(i is None for i in ids):
        raise ValueError("team_ids must be a list of team ids")
    teams = list(Team.objects.filter(org=org, pk__in=ids))
    if len(teams) != len(set(ids)):
        raise ValueError("Every team must belong to this organization")
    return teams


class ProjectListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.view").has_permission(request, self)
        projects = Project.objects.filter(org=org).filter(_visible_projects_q(request.user, org)).distinct()
        status_filter = request.query_params.get("status")
        if status_filter:
            if status_filter not in PROJECT_STATUSES:
                return _bad("status must be active, paused, done or archived")
            projects = projects.filter(status=status_filter)
        projects = projects.select_related("lead").prefetch_related("teams").order_by("name")
        return Response([_project_payload(p, request.user) for p in projects])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("project.manage").has_permission(request, self)
        body = _body(request)
        project = Project(org=org)
        try:
            if "name" not in body:
                raise ValueError("name is required")
            _apply_project_fields(project, body, org, manager=True)
            teams = _project_team_ids(org, body["team_ids"]) if "team_ids" in body else []
        except ValueError as exc:
            return _bad(str(exc))
        project.save()
        if teams:
            project.teams.set(teams)
        from rooms.services import ensure_project_room

        ensure_project_room(project)
        audit(request.user, "project.create", target=project, org=org, request=request, payload={"name": project.name})
        return Response(_project_payload(project, request.user), status=201)


class ProjectDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, project_id):
        org = _org(org_id)
        request.org = org
        project = get_object_or_404(Project, pk=project_id, org=org)
        get_scoped_or_404(request.user, "project.view", project)
        data = _project_payload(project, request.user, with_members=True)
        data["can_edit"] = _can_edit_project(request.user, project)
        data["can_manage"] = can(request.user, "project.manage", project)
        return Response(data)

    def patch(self, request, org_id, project_id):
        org = _org(org_id)
        request.org = org
        project = Project.objects.filter(pk=project_id, org=org).first()
        if project is None or not _can_edit_project(request.user, project):
            HasPerm("project.manage").has_permission(request, self)
            return Response({"error": "not_found", "details": "Project not found"}, status=404)
        manager = can(request.user, "project.manage", project)
        body = _body(request)
        try:
            changed = _apply_project_fields(project, body, org, manager)
            teams = None
            if "team_ids" in body:
                if not manager:
                    raise PermissionError("Only admins change a project's teams")
                teams = _project_team_ids(org, body["team_ids"])
                changed["teams"] = [str(t.id) for t in teams]
        except ValueError as exc:
            return _bad(str(exc))
        except PermissionError as exc:
            return _bad(str(exc), "permission_denied", 403)
        if not changed:
            return _bad("Nothing to change")
        project.save()
        if teams is not None:
            project.teams.set(teams)
        if teams is not None or "lead" in changed:
            from rooms.services import ensure_project_room

            ensure_project_room(project)
        action = "project.archive" if changed.get("status") == Project.STATUS_ARCHIVED else "project.update"
        audit(request.user, action, target=project, org=org, request=request, payload=changed)
        return Response(_project_payload(project, request.user, with_members=True))


class ProjectMemberListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, project_id):
        org = _org(org_id)
        request.org = org
        project = Project.objects.filter(pk=project_id, org=org).first()
        if project is None or not _can_edit_project(request.user, project):
            HasPerm("project.manage").has_permission(request, self)
            return Response({"error": "not_found", "details": "Project not found"}, status=404)
        user = _active_member_user(org, _body(request).get("user_id"))
        if user is None:
            return _bad({"user_id": "Pick an active member of this organization"})
        row, created = ProjectMembership.objects.get_or_create(
            project=project, user=user, defaults={"source": ProjectMembership.SOURCE_DIRECT}
        )
        if not created:
            return _bad("This person is already on the project", "conflict", 409)
        audit(request.user, "project.member.add", target=project, org=org, request=request, payload={"user": str(user.id)})
        return Response(_brief(user), status=201)


class ProjectMemberDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def delete(self, request, org_id, project_id, user_id):
        org = _org(org_id)
        request.org = org
        project = Project.objects.filter(pk=project_id, org=org).first()
        if project is None or not _can_edit_project(request.user, project):
            HasPerm("project.manage").has_permission(request, self)
            return Response({"error": "not_found", "details": "Project not found"}, status=404)
        row = ProjectMembership.objects.filter(project=project, user_id=user_id, source=ProjectMembership.SOURCE_DIRECT).first()
        if row is None:
            return Response({"error": "not_found", "details": "Not a direct member of this project"}, status=404)
        row.delete()
        from rooms.services import prune_project_room

        prune_project_room(project)
        audit(request.user, "project.member.remove", target=project, org=org, request=request, payload={"user": str(user_id)})
        return Response(status=204)
