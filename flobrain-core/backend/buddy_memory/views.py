"""Buddy memory API (growth round M4). Flag ``buddy_memory`` (501 when off).

Your memory (``ai.use``): only ever your own rows; another person's id is 404.
- ``GET /orgs/{org}/memory``: rules, your pause, counts, what is never stored, your teams
- ``GET/POST/DELETE …/memory/items``: list (``q``, ``category``, ``status`` active|pending|all,
  ``scope`` person|team), add one, delete all of yours
- ``PATCH/DELETE …/memory/items/{id}``; ``POST …/memory/items/{id}/confirm`` and ``/reject``
- ``PUT …/memory/me`` ``{paused}``
Team memory and the rules (``memory.manage``):
- ``GET/PUT …/memory/rules``; ``GET …/memory/teams``
- ``GET/POST …/memory/teams/{team}/items``; ``PATCH/DELETE …/memory/teams/{team}/items/{id}``
Audited without the text of any memory.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from buddy_memory import filters, services
from buddy_memory.models import CATEGORIES, MemoryItem, MemoryPreference, MemorySettings
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from organizations.services.core import audit

MAX_QUERY = 100


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _bad(code, details, status=400):
    return Response({"error": code, "details": details}, status=status)


def _invalid(exc):
    status = {"limit": 409, "duplicate": 409}.get(exc.code, 400)
    return _bad(exc.code, exc.details, status)


def _gate(request, view, org_id, perm="ai.use"):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, services.FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "Buddy memory is not enabled"}, status=501)
    return org, None


def _my_teams(user, org):
    return Team.objects.filter(org=org, memberships__user=user).distinct().order_by("name")


def _own(request, org, item_id):
    return MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_PERSON, user=request.user, pk=item_id).select_related("created_by_buddy").first()


def _audit(request, org, action, item=None, **payload):
    audit(request.user, action, target=item, payload=payload, request=request, org=org)


class MemorySummaryView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="What buddies remember about you: rules, your pause, counts")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        services.purge(org=org)
        mine = services.personal(request.user, org)
        row = services.rules(org)
        manager = can(request.user, "memory.manage", org)
        teams = _my_teams(request.user, org)
        return Response({
            "rules": services.rules_payload(row),
            "me": {"paused": services.is_paused(request.user, org)},
            "counts": {
                "active": mine.filter(status=MemoryItem.STATUS_ACTIVE).count(),
                "pending": mine.filter(status=MemoryItem.STATUS_PENDING).count(),
            },
            "categories": list(CATEGORIES),
            "never_stored": list(filters.SENSITIVE),
            "limits": {"text": 300, "personal": services.MAX_PERSONAL},
            "can_manage": manager,
            "teams": [{"id": str(t.id), "name": t.name} for t in teams],
        })


class MemoryItemsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="List your memories (or your teams' memories with scope=team)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        params = request.query_params
        scope = params.get("scope") or "person"
        if scope == "team":
            ids = list(_my_teams(request.user, org).values_list("id", flat=True))
            qs = services.live(MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_TEAM, team_id__in=ids))
        elif scope == "person":
            qs = services.personal(request.user, org)
        else:
            return _bad("invalid", "scope must be person or team")
        status = params.get("status") or "all"
        if status in (MemoryItem.STATUS_ACTIVE, MemoryItem.STATUS_PENDING):
            qs = qs.filter(status=status)
        elif status != "all":
            return _bad("invalid", "status must be active, pending or all")
        category = params.get("category")
        if category:
            if category not in CATEGORIES:
                return _bad("invalid", "Unknown category")
            qs = qs.filter(category=category)
        q = (params.get("q") or "").strip()[:MAX_QUERY]
        if q:
            qs = qs.filter(text__icontains=q)
        qs = qs.select_related("created_by_buddy", "team").order_by("-pinned", "-created_at")[: services.MAX_PERSONAL]
        return Response([services.payload(i) for i in qs])

    @extend_schema(summary="Add a memory about yourself")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        row = services.rules(org)
        if not row.enabled:
            return _bad("memory_off", "Your organization has turned buddy memory off.", 409)
        data = _body(request)
        try:
            item, created = services.add_personal(
                request.user, org, data.get("text"), data.get("category") or "other", MemoryItem.SOURCE_MANUAL, row=row, confirmed=True
            )
        except services.MemoryInvalid as exc:
            return _invalid(exc)
        if not created:
            return _bad("duplicate", "You already have this memory.", 409)
        _audit(request, org, "memory.item.create", item, scope="person", category=item.category)
        return Response(services.payload(item), status=201)

    @extend_schema(summary="Delete all your memories in this organization")
    def delete(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        count = services.delete_items(org, request.user, MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_PERSON, user=request.user))
        _audit(request, org, "memory.item.delete_all", scope="person", count=count)
        return Response({"deleted": count})


class MemoryItemDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Change one of your memories (text, category, pinned)")
    def patch(self, request, org_id, item_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        item = _own(request, org, item_id)
        if item is None:
            return _bad("not_found", "Memory not found", 404)
        try:
            fields = services.edit(item, _body(request))
        except services.MemoryInvalid as exc:
            return _invalid(exc)
        if fields:
            _audit(request, org, "memory.item.update", item, scope="person", fields=sorted(set(fields) - {"digest", "expires_at", "confirmed"}))
        return Response(services.payload(item))

    @extend_schema(summary="Delete one of your memories (it is removed, not hidden)")
    def delete(self, request, org_id, item_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        item = _own(request, org, item_id)
        if item is None:
            return _bad("not_found", "Memory not found", 404)
        item_id = str(item.id)
        services.delete_items(org, request.user, [item])
        _audit(request, org, "memory.item.delete", scope="person", id=item_id)
        return Response(status=204)


class MemoryDecisionView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    decision = "confirm"

    @extend_schema(summary="Answer a suggestion: keep it (confirm) or drop it (reject)")
    def post(self, request, org_id, item_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        item = _own(request, org, item_id)
        if item is None:
            return _bad("not_found", "Memory not found", 404)
        if item.status != MemoryItem.STATUS_PENDING:
            return _bad("conflict", "This memory is not waiting for an answer.", 409)
        if self.decision == "confirm":
            if item.category in (services.rules(org).blocked_categories or []):
                return _bad("blocked_category", "Your organization doesn't let buddies remember this kind of thing.")
            services.confirm(item)
            _audit(request, org, "memory.item.confirm", item, scope="person", category=item.category)
            return Response(services.payload(item))
        item_id = str(item.id)
        services.delete_items(org, request.user, [item])
        _audit(request, org, "memory.item.reject", scope="person", id=item_id)
        return Response(status=204)


class MemoryMeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Pause or resume memory for yourself")
    def put(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        paused = _body(request).get("paused")
        if not isinstance(paused, bool):
            return _bad("invalid", "paused must be true or false")
        MemoryPreference.objects.update_or_create(org=org, user=request.user, defaults={"paused": paused})
        _audit(request, org, "memory.pause", paused=paused)
        return Response({"paused": paused})


class MemoryRulesView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="The organization's memory rules")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id, "memory.manage")
        if error:
            return error
        row = services.rules(org)
        stats = MemoryItem.objects.filter(org=org)
        return Response({
            **services.rules_payload(row),
            "totals": {
                "personal": stats.filter(scope=MemoryItem.SCOPE_PERSON).count(),
                "team": stats.filter(scope=MemoryItem.SCOPE_TEAM).count(),
            },
        })

    @extend_schema(summary="Change the memory rules (audited)")
    def put(self, request, org_id):
        org, error = _gate(request, self, org_id, "memory.manage")
        if error:
            return error
        data = _body(request)
        current = services.rules(org)
        before = services.rules_payload(current)
        changes = {}
        for key in ("enabled", "ask_before_saving", "team_memory"):
            if key in data:
                if not isinstance(data[key], bool):
                    return _bad("invalid", f"{key} must be true or false")
                changes[key] = data[key]
        if "retention_days" in data:
            days = data["retention_days"]
            if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650):
                return _bad("invalid", "retention_days must be 1 to 3650, or empty to keep until deleted")
            changes["retention_days"] = days
        if "blocked_categories" in data:
            blocked = data["blocked_categories"]
            if not isinstance(blocked, list) or not set(blocked) <= set(CATEGORIES):
                return _bad("invalid", f"blocked_categories may contain {', '.join(CATEGORIES)}")
            changes["blocked_categories"] = sorted(set(blocked))
        with transaction.atomic():
            row, _ = MemorySettings.objects.select_for_update().get_or_create(org=org, defaults=dict(services.DEFAULTS))
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_by = request.user
            row.save()
            removed = 0
            if "blocked_categories" in changes and changes["blocked_categories"]:
                # Blocked means not kept: existing memories in those categories are deleted.
                removed = MemoryItem.objects.filter(org=org, category__in=changes["blocked_categories"]).delete()[0]
            purged = services.reapply_retention(org, row) if "retention_days" in changes else {"memories": 0}
        after = services.rules_payload(row)
        diff = {k: [before[k], after[k]] for k in changes if before.get(k) != after.get(k)}
        _audit(request, org, "memory.rules.update", row, changes=diff, removed=removed + purged["memories"])
        return Response({**after, "removed": removed + purged["memories"]})


def _team(org, team_id):
    return Team.objects.filter(org=org, pk=team_id).first()


class MemoryTeamsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Teams and how many memories each has (memory.manage)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id, "memory.manage")
        if error:
            return error
        out = []
        for team in Team.objects.filter(org=org).order_by("name"):
            count = services.live(MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_TEAM, team=team)).count()
            members = TeamMembership.objects.filter(team=team).count()
            out.append({"id": str(team.id), "name": team.name, "memories": count, "members": members})
        return Response(out)


class MemoryTeamItemsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="A team's memories (memory.manage)")
    def get(self, request, org_id, team_id):
        org, error = _gate(request, self, org_id, "memory.manage")
        if error:
            return error
        team = _team(org, team_id)
        if team is None:
            return _bad("not_found", "Team not found", 404)
        qs = services.live(MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_TEAM, team=team)).select_related("team")
        return Response([services.payload(i) for i in qs.order_by("-pinned", "-created_at")])

    @extend_schema(summary="Add a team memory (memory.manage)")
    def post(self, request, org_id, team_id):
        org, error = _gate(request, self, org_id, "memory.manage")
        if error:
            return error
        team = _team(org, team_id)
        if team is None:
            return _bad("not_found", "Team not found", 404)
        row = services.rules(org)
        if not row.enabled or not row.team_memory:
            return _bad("team_memory_off", "Team memory is turned off in the memory rules.", 409)
        data = _body(request)
        try:
            item, created = services.add_team(request.user, org, team, data.get("text"), data.get("category") or "other")
        except services.MemoryInvalid as exc:
            return _invalid(exc)
        if not created:
            return _bad("duplicate", "This team already has this memory.", 409)
        _audit(request, org, "memory.team.create", item, scope="team", team=str(team.id), category=item.category)
        return Response(services.payload(item), status=201)


class MemoryTeamItemDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _item(self, request, org_id, team_id, item_id):
        org, error = _gate(request, self, org_id, "memory.manage")
        if error:
            return org, None, error
        item = MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_TEAM, team_id=team_id, pk=item_id).select_related("team").first()
        if item is None:
            return org, None, _bad("not_found", "Memory not found", 404)
        return org, item, None

    @extend_schema(summary="Change a team memory (memory.manage)")
    def patch(self, request, org_id, team_id, item_id):
        org, item, error = self._item(request, org_id, team_id, item_id)
        if error:
            return error
        try:
            fields = services.edit(item, _body(request))
        except services.MemoryInvalid as exc:
            return _invalid(exc)
        if fields:
            _audit(request, org, "memory.team.update", item, scope="team", team=str(item.team_id), fields=sorted(set(fields) - {"digest", "expires_at", "confirmed"}))
        return Response(services.payload(item))

    @extend_schema(summary="Delete a team memory (memory.manage)")
    def delete(self, request, org_id, team_id, item_id):
        org, item, error = self._item(request, org_id, team_id, item_id)
        if error:
            return error
        item_id = str(item.id)
        services.delete_items(org, None, [item])
        _audit(request, org, "memory.team.delete", scope="team", team=str(team_id), id=item_id)
        return Response(status=204)
