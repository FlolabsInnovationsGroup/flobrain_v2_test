"""``Authorization: Bearer fbp_…`` for the public API and MCP only.

Each request re-checks: token active and not expired, token created after the
owner's last password change, membership active, ``api_access`` on. A failed
membership or password check revokes the token for good.
"""

import hmac

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from organizations.flags import effective_flag
from organizations.models import OrgMembership
from platform_api.models import PAT_PREFIX, PersonalAccessToken, hash_token


def _revoke(token):
    PersonalAccessToken.objects.filter(pk=token.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())


class PATAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return None
        raw = header[7:].strip()
        if not raw.startswith(PAT_PREFIX):
            raise exceptions.AuthenticationFailed("a personal access token is required here")
        digest = hash_token(raw)
        token = PersonalAccessToken.objects.select_related("user", "org").filter(token_hash=digest).first()
        if token is None or not hmac.compare_digest(token.token_hash, digest) or token.revoked_at is not None:
            raise exceptions.AuthenticationFailed("invalid or revoked token")
        now = timezone.now()
        if token.expires_at and token.expires_at <= now:
            raise exceptions.AuthenticationFailed("token expired")
        user = token.user
        if user.password_changed_at and token.created_at < user.password_changed_at:
            _revoke(token)
            raise exceptions.AuthenticationFailed("token issued before the last password change")
        membership = OrgMembership.objects.filter(org=token.org, user=user).first()
        if membership is None or not membership.is_active_member or not token.org.is_active:
            _revoke(token)
            raise exceptions.AuthenticationFailed("membership is not active")
        if not effective_flag(token.org, membership, "api_access", default=False):
            raise exceptions.PermissionDenied("api_access is not enabled")
        PersonalAccessToken.objects.filter(pk=token.pk).update(last_used_at=now)
        return user, token

    def authenticate_header(self, request):
        return 'Bearer realm="public-api"'


class HasPAT(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, PersonalAccessToken)


def require_scope(request, scope):
    if scope not in (request.auth.scopes or []):
        raise exceptions.PermissionDenied(f"token lacks the {scope} scope")
