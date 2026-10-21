"""Impersonation tokens (Phase 17e).

A token has ``type: "impersonation"``, so every path that only accepts
``type: "access"`` (all of V1, the middleware, refresh) ignores it. Only
``BearerJWTAuthentication`` (V2) accepts it, and only when:

- the session is live (not ended, not expired) and the admin is still a platform admin;
- the target is still an active member of that org and not a platform admin;
- the method is safe (GET/HEAD/OPTIONS): impersonation is read-only;
- the path is ``/api/v2/me`` or under ``/api/v2/orgs/<that org>/``.

Each request is written to the org's audit log with the admin as impersonator.
"""

import time
import uuid

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from users.jwt_utils import ALGORITHM

TOKEN_TYPE = "impersonation"
MAX_MINUTES = 60
SAFE = {"GET", "HEAD", "OPTIONS"}


def make_token(session) -> str:
    payload = {
        "sub": str(session.user_id),
        "type": TOKEN_TYPE,
        "sid": str(session.id),
        "imp": str(session.admin_id),
        "org": str(session.org_id),
        "jti": uuid.uuid4().hex,
        "iat": int(time.time()),
        "exp": int(session.expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _decode(token):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None


def authenticate(request, token):
    """Return (user, payload) for a valid impersonation token, None if it is not one. Raises on misuse."""
    payload = _decode(token)
    if not payload or payload.get("type") != TOKEN_TYPE:
        return None
    from console.models import ImpersonationSession
    from organizations.models import OrgMembership

    try:
        session = ImpersonationSession.objects.select_related("admin", "user").get(pk=uuid.UUID(str(payload.get("sid"))))
    except (ImpersonationSession.DoesNotExist, ValueError, TypeError):
        raise AuthenticationFailed("Impersonation session not found")
    if (
        not session.is_live
        or str(session.user_id) != str(payload.get("sub"))
        or str(session.admin_id) != str(payload.get("imp"))
        or str(session.org_id) != str(payload.get("org"))
        or not session.admin.is_platform_admin
        or session.user.is_platform_admin
        or (session.admin.password_changed_at and session.admin.password_changed_at > session.created_at)
    ):
        raise AuthenticationFailed("Impersonation session ended")
    membership = OrgMembership.objects.filter(org_id=session.org_id, user_id=session.user_id).first()
    if not (membership and membership.is_active_member):
        raise AuthenticationFailed("Impersonation session ended")
    path = request.path
    if not (path.rstrip("/") == "/api/v2/me" or path.startswith(f"/api/v2/orgs/{session.org_id}/")):
        raise PermissionDenied("impersonation_scope: only this org's pages")
    if request.method not in SAFE:
        raise PermissionDenied("impersonation_read_only")
    from organizations.services.core import audit

    audit(
        session.user,
        "impersonation.request",
        target=session,
        payload={"method": request.method, "path": path[:300]},
        org=session.org,
        impersonator=session.admin,
    )
    payload["impersonation"] = True
    return session.user, payload


def end(session, by):
    from console.models import ImpersonationSession

    return ImpersonationSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(ended_at=timezone.now(), ended_by=by)


def is_impersonated(request) -> bool:
    auth = getattr(request, "auth", None)
    return isinstance(auth, dict) and bool(auth.get("impersonation"))
