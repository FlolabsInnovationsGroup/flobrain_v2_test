"""SCIM 2.0 provisioning (Phase 17d): ``/scim/v2/Users`` and ``/scim/v2/Groups``.

Rules (Decisions 8 and 41):
- SCIM never grants owner, admin or lead. New people are org members; SCIM never changes an
  existing role, and never pauses or deletes the org owner.
- Without a team (no mapped group) a new member is ``pending``; joining a mapped group makes them
  ``active`` and adds the team membership (role member).
- ``active=false`` (or DELETE) pauses the membership, which revokes their API tokens. No data is deleted.
"""

import hashlib
import hmac
import re
import secrets
import uuid

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core_v2.views import V2APIView
from organizations.models import OrgMembership, Organization, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit
from sso.models import SCIMGroupMap, SCIMToken

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
FILTER_RE = re.compile(r'^\s*(userName|externalId|displayName)\s+eq\s+"([^"]{1,254})"\s*$')
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def _error(status, detail, scim_type=None):
    body = {"schemas": [ERROR_SCHEMA], "status": str(status), "detail": detail}
    if scim_type:
        body["scimType"] = scim_type
    return Response(body, status=status, content_type="application/scim+json")


class SCIMAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer scim_"):
            raise exceptions.AuthenticationFailed("SCIM token required")
        digest = _hash(header[7:].strip())
        token = SCIMToken.objects.select_related("org", "created_by").filter(token_hash=digest, revoked_at__isnull=True).first()
        if token is None or not hmac.compare_digest(token.token_hash, digest) or not token.org.is_active:
            raise exceptions.AuthenticationFailed("invalid SCIM token")
        from organizations.permissions.engine import can

        # A token lives only while the owner who made it still owns the org.
        if token.created_by is None or not can(token.created_by, "sso.manage", token.org):
            raise exceptions.AuthenticationFailed("invalid SCIM token")
        return None, token


class SCIMJSONParser(JSONParser):
    media_type = "application/scim+json"


class SCIMView(APIView):
    authentication_classes = [SCIMAuthentication]
    permission_classes = []
    throttle_classes = []
    parser_classes = [JSONParser, SCIMJSONParser]

    @property
    def org(self):
        return self.request.auth.org

    def handle_exception(self, exc):
        if isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
            return _error(401, "invalid SCIM token")
        if isinstance(exc, exceptions.ParseError):
            return _error(400, "invalid JSON", "invalidSyntax")
        return super().handle_exception(exc)


def _user_payload(org, user):
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return {
        "schemas": [USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "displayName": user.username or user.email,
        "emails": [{"value": user.email, "primary": True}],
        "active": bool(membership and membership.is_active_member),
        "meta": {"resourceType": "User"},
    }


def _members_of_org(org):
    from users.models import User

    return User.objects.filter(org_memberships__org=org).distinct()


def _paginate(request, items):
    try:
        start = max(1, int(request.query_params.get("startIndex", 1)))
        count = max(0, min(200, int(request.query_params.get("count", 100))))
    except ValueError:
        start, count = 1, 100
    page = items[start - 1 : start - 1 + count]
    return {"schemas": [LIST_SCHEMA], "totalResults": len(items), "startIndex": start, "itemsPerPage": len(page), "Resources": page}


SCIM_REASON = "scim"


def _is_lead(org, user):
    return TeamMembership.objects.filter(team__org=org, user=user, team_role=TeamMembership.ROLE_LEAD).exists()


def _set_active(org, user, active):
    """Deprovisioning may pause anyone but the owner. Reactivation only undoes what SCIM did,
    and only for plain members (never admins or leads, never a pause a person made)."""
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if membership is None:
        return None
    if not active:
        if membership.org_role == OrgMembership.ORG_ROLE_OWNER:
            return "owner"
        if membership.employment_status == OrgMembership.STATUS_PAUSED:
            return membership
        membership.employment_status = OrgMembership.STATUS_PAUSED
        membership.status_changed_at, membership.status_changed_by, membership.status_reason = timezone.now(), None, SCIM_REASON
        membership.save()  # the membership signal revokes API tokens when it stops being active
        user.password_changed_at = timezone.now()  # and their sessions end, as with a manual pause
        user.save(update_fields=["password_changed_at"])
        return membership
    if membership.employment_status not in (OrgMembership.STATUS_PAUSED, OrgMembership.STATUS_PENDING):
        return membership
    if (
        membership.org_role != OrgMembership.ORG_ROLE_MEMBER
        or _is_lead(org, user)
        or membership.status_reason != SCIM_REASON
    ):
        return "protected"
    has_team = TeamMembership.objects.filter(team__org=org, user=user).exists()
    membership.employment_status = OrgMembership.STATUS_ACTIVE if has_team else OrgMembership.STATUS_PENDING
    membership.status_changed_at, membership.status_changed_by = timezone.now(), None
    membership.save()
    return membership


def _verified_domains(org):
    from sso.models import SSOConnection

    c = SSOConnection.objects.filter(org=org).first()
    return {d.lower() for d in (c.verified_domains if c else [])}


class UsersView(SCIMView):
    def get(self, request):
        users = _members_of_org(self.org).order_by("email")
        flt = request.query_params.get("filter")
        if flt:
            match = FILTER_RE.match(flt)
            if not match or match.group(1) != "userName":
                return _error(400, "only userName eq is supported", "invalidFilter")
            users = users.filter(email__iexact=match.group(2))
        return Response(_paginate(request, [_user_payload(self.org, u) for u in users]), content_type="application/scim+json")

    def post(self, request):
        from users.models import User

        data = request.data if isinstance(request.data, dict) else {}
        email = str(data.get("userName") or "").strip().lower()
        if not EMAIL_RE.match(email):
            return _error(400, "userName must be an email", "invalidValue")
        if email.rsplit("@", 1)[-1] not in _verified_domains(self.org):
            # Only people in domains this org proved it owns; never someone else's account.
            return _error(400, "userName must be in one of the organization's verified domains", "invalidValue")
        name = data.get("name") if isinstance(data.get("name"), dict) else {}
        try:
            with transaction.atomic():
                user = User.objects.filter(email__iexact=email).first()
                if user is not None and OrgMembership.objects.filter(org=self.org, user=user).exists():
                    return _error(409, "user already exists in this organization", "uniqueness")
                from billing_v2.entitlements import seat_blocked

                if seat_blocked(self.org, adding_user_id=user.id if user else None) is not None:
                    return _error(409, "all seats are taken; add seats in billing", "tooMany")
                if user is None:
                    display = str(data.get("displayName") or name.get("formatted") or email.split("@")[0])[:150]
                    # No usable password: SSO only (or a reset the user starts themselves).
                    user = User.objects.create(email=email, username=display, password_hash=make_password(None), provider="scim")
                if OrgMembership.objects.filter(org=self.org, user=user).exists():
                    return _error(409, "user already exists in this organization", "uniqueness")
                OrgMembership.objects.create(
                    org=self.org,
                    user=user,
                    org_role=OrgMembership.ORG_ROLE_MEMBER,  # never owner/admin/lead
                    employment_status=OrgMembership.STATUS_PENDING,
                    status_reason=SCIM_REASON,
                )
        except IntegrityError:
            return _error(409, "user already exists", "uniqueness")
        if data.get("active") is False:
            _set_active(self.org, user, False)
        audit(None, "scim.user_create", target=user, payload={"email_domain": email.rsplit("@", 1)[-1]}, org=self.org)
        return Response(_user_payload(self.org, user), status=201, content_type="application/scim+json")


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _org_user(org, user_id):
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return None
    return _members_of_org(org).filter(pk=uid).first()


class UserDetailView(SCIMView):
    def get(self, request, user_id):
        user = _org_user(self.org, user_id)
        return Response(_user_payload(self.org, user), content_type="application/scim+json") if user else _error(404, "not found")

    def _apply_active(self, user, active):
        result = _set_active(self.org, user, active)
        if result == "owner":
            return _error(403, "SCIM cannot deactivate the organization owner")
        if result == "protected":
            return _error(403, "SCIM cannot reactivate admins, leads, or people paused in FloBrain")
        audit(None, "scim.user_active", target=user, payload={"active": active}, org=self.org)
        return None

    def put(self, request, user_id):
        user = _org_user(self.org, user_id)
        if user is None:
            return _error(404, "not found")
        data = request.data if isinstance(request.data, dict) else {}
        if "active" in data:
            active = _as_bool(data["active"])
            if active is None:
                return _error(400, "active must be true or false", "invalidValue")
            err = self._apply_active(user, active)
            if err:
                return err
        return Response(_user_payload(self.org, user), content_type="application/scim+json")

    def patch(self, request, user_id):
        user = _org_user(self.org, user_id)
        if user is None:
            return _error(404, "not found")
        data = request.data if isinstance(request.data, dict) else {}
        for op in data.get("Operations") or []:
            if not isinstance(op, dict) or str(op.get("op", "")).lower() not in ("replace", "add"):
                continue
            value = op.get("value")
            path = op.get("path")
            if path == "active":
                active = value
            elif isinstance(value, dict) and "active" in value:
                active = value["active"]
            else:
                continue
            active = _as_bool(active)
            if active is None:
                return _error(400, "active must be true or false", "invalidValue")
            err = self._apply_active(user, active)
            if err:
                return err
        return Response(_user_payload(self.org, user), content_type="application/scim+json")

    def delete(self, request, user_id):
        user = _org_user(self.org, user_id)
        if user is None:
            return _error(404, "not found")
        err = self._apply_active(user, False)
        return err or Response(status=204)


def _group_payload(g):
    members = []
    if g.team_id:
        members = [{"value": str(uid)} for uid in TeamMembership.objects.filter(team_id=g.team_id).values_list("user_id", flat=True)]
    return {
        "schemas": [GROUP_SCHEMA],
        "id": str(g.id),
        "displayName": g.display_name,
        "externalId": g.external_id,
        "members": members,
        "meta": {"resourceType": "Group"},
    }


def _sync_members(org, group, op, user_ids):
    if group.team_id is None:
        return  # unmapped groups do nothing until an admin maps them to a team
    for raw in user_ids:
        user = _org_user(org, raw)
        if user is None:
            continue
        if op == "add":
            membership = OrgMembership.objects.filter(org=org, user=user).first()
            if membership is None or membership.employment_status in (OrgMembership.STATUS_PAUSED, OrgMembership.STATUS_TERMINATED, OrgMembership.STATUS_OFFBOARDING):
                continue  # a paused person does not get team access back through a group
            TeamMembership.objects.get_or_create(team_id=group.team_id, user=user)
            pending = OrgMembership.objects.filter(org=org, user=user, employment_status=OrgMembership.STATUS_PENDING)
            if pending.exists():
                _set_active(org, user, True)  # a mapped team is the team assignment Decision 41 asks for (SCIM-made only)
        elif op == "remove":
            # Leads are managed in FloBrain; SCIM removes plain team members only.
            TeamMembership.objects.filter(team_id=group.team_id, user=user, team_role=TeamMembership.ROLE_MEMBER).delete()


def _member_ids(value):
    if isinstance(value, list):
        return [m.get("value") for m in value if isinstance(m, dict)]
    return []


class GroupsView(SCIMView):
    def get(self, request):
        groups = SCIMGroupMap.objects.filter(org=self.org).order_by("display_name")
        flt = request.query_params.get("filter")
        if flt:
            match = FILTER_RE.match(flt)
            if not match or match.group(1) not in ("displayName", "externalId"):
                return _error(400, "only displayName or externalId eq is supported", "invalidFilter")
            field = "display_name" if match.group(1) == "displayName" else "external_id"
            groups = groups.filter(**{field: match.group(2)})
        return Response(_paginate(request, [_group_payload(g) for g in groups]), content_type="application/scim+json")

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get("displayName") or "").strip()[:200]
        if not name:
            return _error(400, "displayName is required", "invalidValue")
        external = str(data.get("externalId") or name)[:200]
        group, created = SCIMGroupMap.objects.get_or_create(org=self.org, external_id=external, defaults={"display_name": name})
        if not created:
            return _error(409, "group exists", "uniqueness")
        _sync_members(self.org, group, "add", _member_ids(data.get("members")))
        return Response(_group_payload(group), status=201, content_type="application/scim+json")


class GroupDetailView(SCIMView):
    def _group(self, group_id):
        try:
            gid = uuid.UUID(str(group_id))
        except ValueError:
            return None
        return SCIMGroupMap.objects.filter(org=self.org, pk=gid).first()

    def get(self, request, group_id):
        group = self._group(group_id)
        return Response(_group_payload(group), content_type="application/scim+json") if group else _error(404, "not found")

    def patch(self, request, group_id):
        group = self._group(group_id)
        if group is None:
            return _error(404, "not found")
        data = request.data if isinstance(request.data, dict) else {}
        for op in data.get("Operations") or []:
            if not isinstance(op, dict):
                continue
            kind = str(op.get("op", "")).lower()
            path = str(op.get("path") or "")
            if kind == "add" and path in ("members", ""):
                value = op.get("value")
                ids = _member_ids(value if path == "members" else (value or {}).get("members") if isinstance(value, dict) else [])
                _sync_members(self.org, group, "add", ids)
            elif kind == "remove" and path.startswith("members"):
                ids = _member_ids(op.get("value"))
                match = re.match(r'^members\[value eq "([^"]+)"\]$', path)
                if match:
                    ids.append(match.group(1))
                _sync_members(self.org, group, "remove", ids)
            elif kind == "replace" and path == "displayName" and isinstance(op.get("value"), str):
                group.display_name = op["value"][:200]
                group.save(update_fields=["display_name"])
        return Response(_group_payload(group), content_type="application/scim+json")

    def delete(self, request, group_id):
        group = self._group(group_id)
        if group is None:
            return _error(404, "not found")
        group.delete()  # team memberships stay; removing people from teams is a FloBrain decision
        return Response(status=204)


# --- admin: tokens and group mapping (V2 session auth) -------------------------------


class SCIMTokenView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _org(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("sso.manage").has_permission(request, self)
        return org

    def get(self, request, org_id):
        org = self._org(request, org_id)
        rows = SCIMToken.objects.filter(org=org).order_by("-created_at")
        groups = SCIMGroupMap.objects.filter(org=org).order_by("display_name")
        return Response(
            {
                "tokens": [{"id": str(t.id), "last4": t.last4, "revoked": t.revoked_at is not None} for t in rows],
                "groups": [{"id": str(g.id), "display_name": g.display_name, "team": str(g.team_id) if g.team_id else None} for g in groups],
            }
        )

    def post(self, request, org_id):
        org = self._org(request, org_id)
        data = request.data if isinstance(request.data, dict) else {}
        if data.get("revoke"):
            done = SCIMToken.objects.filter(org=org, revoked_at__isnull=True, pk=data["revoke"] if _is_uuid(data["revoke"]) else None).update(
                revoked_at=timezone.now()
            )
            if done:
                audit(request.user, "scim.token_revoke", payload={"token": str(data["revoke"])}, request=request, org=org)
            return Response(status=204)
        if data.get("map_group"):
            from organizations.models import Team

            group = SCIMGroupMap.objects.filter(org=org, pk=data["map_group"] if _is_uuid(data["map_group"]) else None).first()
            team = Team.objects.filter(org=org, pk=data.get("team") if _is_uuid(data.get("team")) else None).first()
            if group is None or (data.get("team") and team is None):
                return Response({"error": "not_found", "details": "Group or team not found"}, status=404)
            group.team = team
            group.save(update_fields=["team"])
            audit(request.user, "scim.group_map", target=group, payload={"team": str(team.id) if team else None}, request=request, org=org)
            return Response({"id": str(group.id), "team": str(team.id) if team else None})
        raw = "scim_" + secrets.token_urlsafe(32)
        token = SCIMToken.objects.create(org=org, token_hash=_hash(raw), last4=raw[-4:], created_by=request.user)
        audit(request.user, "scim.token_create", target=token, request=request, org=org)
        return Response({"id": str(token.id), "token": raw}, status=201)


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
