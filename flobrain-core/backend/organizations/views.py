from datetime import datetime, time, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView, V2PublicAPIView
from organizations.models import (
    AuditEvent,
    OrgMembership,
    Organization,
    PermissionGrant,
    PermissionRequest,
    Project,
    Team,
)
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from users.authentication import BearerJWTAuthentication
from organizations.permissions.registry import PERMISSION_CATALOG, ROLE_DEFAULTS
from organizations.serializers import (
    PermissionGrantSerializer,
    PermissionRequestSerializer,
)
from organizations.services import audit, decide_request, grant_permission
from users.models import User

MAX_GRANT_DAYS = 365
SCOPES = (PermissionGrant.SCOPE_ORG, PermissionGrant.SCOPE_TEAM, PermissionGrant.SCOPE_PROJECT)


def _org(kwargs) -> Organization:
    return get_object_or_404(Organization, pk=kwargs["org_id"], is_active=True)


def _bad(details, code="invalid", status_code=400):
    return Response({"error": code, "details": details}, status=status_code)


def _scope_object(org, scope_type, scope_id):
    """The object ``can()`` checks for this scope. ValueError (400) when the scope is not in this org."""
    scope_type = scope_type or PermissionGrant.SCOPE_ORG
    if scope_type not in SCOPES:
        raise ValueError("scope_type must be org, team or project")
    if scope_type == PermissionGrant.SCOPE_ORG:
        return org
    if not scope_id:
        raise ValueError(f"scope_id is required for a {scope_type} scope")
    model = Team if scope_type == PermissionGrant.SCOPE_TEAM else Project
    obj = model.objects.filter(pk=scope_id, org=org).first()
    if obj is None:
        raise ValueError(f"That {scope_type} is not in this organization")
    return obj


def _scope_names(org, rows):
    team_ids = {r.scope_id for r in rows if r.scope_type == PermissionGrant.SCOPE_TEAM and r.scope_id}
    project_ids = {r.scope_id for r in rows if r.scope_type == PermissionGrant.SCOPE_PROJECT and r.scope_id}
    names = dict(Team.objects.filter(org=org, pk__in=team_ids).values_list("id", "name"))
    names.update(dict(Project.objects.filter(org=org, pk__in=project_ids).values_list("id", "name")))
    return names


def _people(ids):
    ids = {i for i in ids if i}
    return {u.id: {"id": str(u.id), "username": u.username or ""} for u in User.objects.filter(pk__in=ids)}


def _label(key):
    return PERMISSION_CATALOG.get(key, {}).get("label", key)


def _grant_rows(org, grants):
    grants = list(grants)
    people = _people([g.grantee_id for g in grants] + [g.granted_by_id for g in grants] + [g.revoked_by_id for g in grants])
    names = _scope_names(org, grants)
    now = timezone.now()
    out = []
    for g in grants:
        data = PermissionGrantSerializer(g).data
        expired = bool(g.expires_at and g.expires_at <= now)
        data.update(
            {
                "label": _label(g.perm_key),
                "grantee_user": people.get(g.grantee_id),
                "granted_by_user": people.get(g.granted_by_id),
                "revoked_by_user": people.get(g.revoked_by_id),
                "scope_name": names.get(g.scope_id) if g.scope_id else None,
                "expired": expired,
                "active": g.revoked_at is None and not expired,
            }
        )
        out.append(data)
    return out


def _request_rows(org, reqs):
    reqs = list(reqs)
    people = _people([r.requester_id for r in reqs] + [r.decided_by_id for r in reqs])
    names = _scope_names(org, reqs)
    out = []
    for r in reqs:
        data = PermissionRequestSerializer(r).data
        data.update(
            {
                "label": _label(r.perm_key),
                "requester_user": people.get(r.requester_id),
                "decided_by_user": people.get(r.decided_by_id),
                "scope_name": names.get(r.scope_id) if r.scope_id else None,
            }
        )
        out.append(data)
    return out


def _expiry(data):
    """``expires_in_days`` (1 to 365) or ``expires_at`` (a future time within a year). None = no expiry."""
    days = data.get("expires_in_days")
    raw_at = data.get("expires_at")
    if days not in (None, ""):
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_GRANT_DAYS:
            raise ValueError(f"expires_in_days must be a whole number from 1 to {MAX_GRANT_DAYS}")
        return timezone.now() + timedelta(days=days)
    if raw_at not in (None, ""):
        at = parse_datetime(str(raw_at)) if isinstance(raw_at, str) else None
        if at is None:
            raise ValueError("expires_at must be a date and time")
        if timezone.is_naive(at):
            at = timezone.make_aware(at)
        now = timezone.now()
        if at <= now:
            raise ValueError("expires_at must be in the future")
        if at > now + timedelta(days=MAX_GRANT_DAYS):
            raise ValueError("A grant can last at most a year")
        return at
    return None


def _deciders(org):
    return list(
        OrgMembership.objects.filter(
            org=org,
            employment_status=OrgMembership.STATUS_ACTIVE,
            org_role__in=[OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN],
        ).values_list("user_id", flat=True)
    )


class MyOrgsView(V2PublicAPIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Organization.objects.filter(
            is_active=True,
            memberships__user=request.user,
            memberships__employment_status=OrgMembership.STATUS_ACTIVE,
        ).distinct()
        slug = request.query_params.get("slug")
        if slug:
            qs = qs.filter(slug=slug)
        return Response([{"id": str(org.id), "slug": org.slug, "name": org.name} for org in qs])


def _sees_all_grants(user, org) -> bool:
    return any(can(user, key, org) for key in ("grants.create", "grants.revoke", "audit.view"))


class GrantListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        grants = PermissionGrant.objects.filter(org=org).order_by("-created_at")
        if not _sees_all_grants(request.user, org):
            grants = grants.filter(grantee=request.user)  # members see the grants they hold
        grantee = request.query_params.get("grantee")
        if grantee:
            grants = grants.filter(grantee_id=grantee) if _is_uuid(grantee) else grants.none()
        if request.query_params.get("active") in {"1", "true"}:
            now = timezone.now()
            grants = grants.filter(revoked_at__isnull=True).exclude(expires_at__lte=now)
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(grants, request, view=self)
        return paginator.get_paginated_response(_grant_rows(org, page))

    def post(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("grants.create").has_permission(request, self)
        serializer = PermissionGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        grantee = data["grantee"]
        if not OrgMembership.objects.filter(org=org, user=grantee, employment_status=OrgMembership.STATUS_ACTIVE).exists():
            return _bad({"grantee": "Pick an active member of this organization"})
        if grantee.id == request.user.id:
            return _bad({"grantee": "You can't grant a permission to yourself"})
        key = data["perm_key"]
        scope_type = data.get("scope_type") or PermissionGrant.SCOPE_ORG
        try:
            scope_obj = _scope_object(org, scope_type, data.get("scope_id"))
            expires_at = _expiry(request.data if isinstance(request.data, dict) else {})
        except ValueError as exc:
            return _bad(str(exc))
        if not can(request.user, key, scope_obj):
            return _bad("You can only grant permissions you hold yourself", "permission_denied", 403)
        grantee_role = OrgMembership.objects.filter(org=org, user=grantee).values_list("org_role", flat=True).first()
        if key in ROLE_DEFAULTS.get(grantee_role, frozenset()):
            # Their role already gives it. A second grant on top of an existing grant is allowed (to extend one).
            return _bad("This person's role already includes this permission", "conflict", 409)
        grant = grant_permission(
            org,
            request.user,
            grantee,
            key,
            scope_type=scope_type,
            scope_id=scope_obj.id if scope_type != PermissionGrant.SCOPE_ORG else None,
            expires_at=expires_at,
            request=request,
        )
        from notifications.services import notify

        notify(org, [grantee], "access.granted", {"perm_key": key, "label": _label(key)}, link="settings/access")
        return Response(_grant_rows(org, [grant])[0], status=status.HTTP_201_CREATED)


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


class GrantRevokeView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    required_perm = "grants.revoke"

    def delete(self, request, org_id, grant_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("grants.revoke").has_permission(request, self)
        grant = get_object_or_404(PermissionGrant, pk=grant_id, org=org)
        if grant.revoked_at is None:
            grant.revoked_at = timezone.now()
            grant.revoked_by = request.user
            grant.save(update_fields=["revoked_at", "revoked_by"])
            audit(request.user, "perm.revoke", target=grant, request=request, org=org, payload={"perm_key": grant.perm_key, "grantee": str(grant.grantee_id)})
        return Response(status=status.HTTP_204_NO_CONTENT)


class PermissionRequestListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        qs = PermissionRequest.objects.filter(org=org).order_by("-created_at")
        if not can(request.user, "permission_requests.decide", org) or request.query_params.get("mine") in {"1", "true"}:
            qs = qs.filter(requester=request.user)  # members see their own requests
        status_filter = request.query_params.get("status")
        if status_filter:
            if status_filter not in {c for c, _ in PermissionRequest.STATUS_CHOICES}:
                return _bad("status must be pending, approved or rejected")
            qs = qs.filter(status=status_filter)
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(_request_rows(org, page))

    def post(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("permission_requests.create").has_permission(request, self)
        serializer = PermissionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        key = data["perm_key"]
        scope_type = data.get("scope_type") or PermissionGrant.SCOPE_ORG
        try:
            scope_obj = _scope_object(org, scope_type, data.get("scope_id"))
        except ValueError as exc:
            return _bad(str(exc))
        my_role = OrgMembership.objects.filter(org=org, user=request.user).values_list("org_role", flat=True).first()
        if key in ROLE_DEFAULTS.get(my_role, frozenset()):
            # A held grant may be asked for again (to extend it); a role default never needs a request.
            return _bad("Your role already includes this permission", "conflict", 409)
        scope_id = scope_obj.id if scope_type != PermissionGrant.SCOPE_ORG else None
        if PermissionRequest.objects.filter(
            org=org, requester=request.user, perm_key=key, scope_type=scope_type, scope_id=scope_id,
            status=PermissionRequest.STATUS_PENDING,
        ).exists():
            return _bad("You already asked for this. It is waiting for a decision", "conflict", 409)
        req = PermissionRequest.objects.create(
            org=org,
            requester=request.user,
            perm_key=key,
            scope_type=scope_type,
            scope_id=scope_id,
            reason=str(data.get("reason") or "")[:1000],
        )
        audit(request.user, "perm.request.create", target=req, request=request, org=org, payload={"perm_key": key})
        from notifications.services import notify

        notify(
            org,
            [uid for uid in _deciders(org) if uid != request.user.id],
            "access.requested",
            {"by": request.user.username or "", "perm_key": key, "label": _label(key)},
            link="settings/access",
        )
        return Response(_request_rows(org, [req])[0], status=status.HTTP_201_CREATED)


class PermissionRequestDecideView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    required_perm = "permission_requests.decide"

    def post(self, request, org_id, request_id, decision):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("permission_requests.decide").has_permission(request, self)
        if decision not in {"approve", "reject"}:
            return Response({"error": "not_found", "details": "Use approve or reject"}, status=404)
        req = get_object_or_404(PermissionRequest, pk=request_id, org=org)
        if req.status != PermissionRequest.STATUS_PENDING:
            return _bad("This request was already decided", "conflict", 409)
        if req.requester_id == request.user.id:
            return _bad("Someone else decides your own request", "permission_denied", 403)
        try:
            scope_obj = _scope_object(org, req.scope_type, req.scope_id)
        except ValueError:
            scope_obj = None
        if scope_obj is None:
            return _bad("The team or project in this request no longer exists", "conflict", 409)
        if not can(request.user, req.perm_key, scope_obj):
            return _bad("Only someone who holds this permission can decide", "permission_denied", 403)
        days = None
        body = request.data if isinstance(request.data, dict) else {}
        if decision == "approve" and body.get("expires_in_days") not in (None, ""):
            days = body.get("expires_in_days")
            if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_GRANT_DAYS:
                return _bad(f"expires_in_days must be a whole number from 1 to {MAX_GRANT_DAYS}")
        decide_request(req, request.user, approve=(decision == "approve"), request=request, days=days)
        from notifications.services import notify

        notify(
            org,
            [req.requester_id],
            "access.decided",
            {"perm_key": req.perm_key, "label": _label(req.perm_key), "outcome": req.status},
            link="settings/access",
        )
        return Response(_request_rows(org, [req])[0])


def _day_bound(raw, end=False):
    """A date (whole day) or a date-time. ValueError on anything else."""
    value = str(raw).strip()
    as_dt = parse_datetime(value)
    if as_dt is not None:
        return as_dt if timezone.is_aware(as_dt) else timezone.make_aware(as_dt)
    as_date = parse_date(value)
    if as_date is None:
        raise ValueError("Dates look like 2026-10-21")
    moment = datetime.combine(as_date, time.max if end else time.min)
    return timezone.make_aware(moment)


class AuditEventListView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    required_perm = "audit.view"

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("audit.view").has_permission(request, self)
        qs = AuditEvent.objects.filter(org=org).order_by("-created_at")
        params = request.query_params
        try:
            actor = params.get("actor")
            if actor:
                if not _is_uuid(actor):
                    raise ValueError("actor must be a member id")
                qs = qs.filter(actor_id=actor)
            action = (params.get("action") or "").strip()
            if action:
                qs = qs.filter(action__istartswith=action[:100])  # "perm" finds perm.grant, perm.revoke, ...
            target_type = (params.get("target_type") or "").strip()
            if target_type:
                qs = qs.filter(target_type__iexact=target_type[:64])
            if params.get("since"):
                qs = qs.filter(created_at__gte=_day_bound(params["since"]))
            if params.get("until"):
                qs = qs.filter(created_at__lte=_day_bound(params["until"], end=True))
        except ValueError as exc:
            return _bad(str(exc))
        paginator = V2PageNumberPagination()
        page = list(paginator.paginate_queryset(qs, request, view=self))
        people = _people([e.actor_id for e in page] + [e.impersonator_id for e in page])
        rows = [
            {
                "id": str(e.id),
                "actor": str(e.actor_id) if e.actor_id else None,
                "actor_user": people.get(e.actor_id),
                "impersonator": str(e.impersonator_id) if e.impersonator_id else None,
                "impersonator_user": people.get(e.impersonator_id),
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "payload": e.payload,
                "ip": e.ip,
                "created_at": e.created_at.isoformat(),
            }
            for e in page
        ]
        return paginator.get_paginated_response(rows)


class AuditActionListView(V2APIView):
    """The distinct action names in this org's log, for the filter box."""

    permission_classes = [IsActiveOrgMember]
    required_perm = "audit.view"

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("audit.view").has_permission(request, self)
        actions = (
            AuditEvent.objects.filter(org=org).order_by("action").values_list("action", flat=True).distinct()[:300]
        )
        return Response(list(actions))


class PermissionCatalogView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        from organizations.permissions.registry import OWNER_ONLY_KEYS

        return Response(
            [{"key": key, **meta, "grantable": key not in OWNER_ONLY_KEYS} for key, meta in PERMISSION_CATALOG.items()]
        )
