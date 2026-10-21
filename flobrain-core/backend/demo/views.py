"""Demo mode endpoints (only when ``DEMO_MODE=True``; 404 otherwise).

- ``GET  /api/v2/demo``: whether demo mode is on, and the roles to pick from
- ``POST /api/v2/demo/signin {role}``: tokens for that seeded demo user (seeds the org on first use)
- ``POST /api/v2/demo/reset``: rebuild the demo org (signed-in demo users only, once a minute)
"""

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView, V2PublicAPIView
from demo import seed
from demo.models import DemoAccount


def enabled() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


def _off():
    return Response({"error": "not_found"}, status=404)


def _roles():
    return [
        {"key": key, "name": name, "org_role": role, "description": text, "email": seed.email_for(key)}
        for key, (name, role, text) in seed.ROLES.items()
    ]


def _seed_once():
    """One builder at a time; a real org on the demo slug stops it."""
    if not cache.add("demo:seeding", 1, timeout=120):
        return Response({"error": "busy", "details": "The demo is being built. Try again in a moment."}, status=503)
    try:
        seed.reset()
    except seed.DemoSlugTaken:
        return Response({"error": "conflict", "details": "A real organization uses the demo address; demo mode won't touch it"}, status=409)
    finally:
        cache.delete("demo:seeding")
    return None


class DemoInfoView(V2PublicAPIView):
    @extend_schema(summary="Demo mode and its roles")
    def get(self, request):
        if not enabled():
            return Response({"enabled": False})
        return Response({"enabled": True, "org_slug": seed.DEMO_SLUG, "roles": _roles()})


class DemoSignInView(V2PublicAPIView):
    @extend_schema(summary="Sign in as one demo role")
    def post(self, request):
        if not enabled():
            return _off()
        data = request.data if isinstance(request.data, dict) else {}
        role = str(data.get("role") or "")
        if role not in seed.ROLES:
            return Response({"error": "invalid", "details": "role must be one of " + ", ".join(seed.ROLES)}, status=400)
        account = DemoAccount.objects.select_related("user").filter(role=role).first()
        if account is None:
            error = _seed_once()
            if error is not None:
                return error
            account = DemoAccount.objects.select_related("user").filter(role=role).first()
            if account is None:
                return Response({"error": "busy", "details": "The demo is being built. Try again in a moment."}, status=503)
        from users.v2.views import _tokens_for

        return Response({**_tokens_for(account.user), "org_slug": seed.DEMO_SLUG, "role": role})


class DemoResetView(V2APIView):
    permission_classes = []

    @extend_schema(summary="Rebuild the demo org")
    def post(self, request):
        if not enabled():
            return _off()
        if not request.user.is_authenticated or not DemoAccount.objects.filter(user_id=request.user.id).exists():
            return Response({"error": "permission_denied", "details": "Demo users only"}, status=403)
        if not cache.add("demo:reset", 1, timeout=60):
            return Response({"error": "rate_limited", "details": "Try again in a minute"}, status=429)
        error = _seed_once()
        if error is not None:
            return error
        return Response({"reset": True, "org_slug": seed.DEMO_SLUG})


class DemoIdPView(V2PublicAPIView):
    """The demo SAML identity provider's sign-in page (demo only)."""

    @extend_schema(exclude=True)
    def get(self, request):
        from demo import idp
        from sso.models import SSOConnection

        if not enabled():
            return _off()
        found = idp.read_request(request.query_params.get("SAMLRequest"))
        relay = str(request.query_params.get("RelayState") or "")[:200]
        if found is None or not relay:
            return Response({"error": "invalid", "details": "Not a sign-in request from FloBrain"}, status=400)
        request_id, sp_entity = found
        connection = next(
            (c for c in SSOConnection.objects.filter(idp_entity_id=idp.IDP_ENTITY, enabled=True).select_related("org") if saml_sp(c) == sp_entity),
            None,
        )
        if connection is None or "demo_idp_key" not in (connection.metadata or {}):
            return Response({"error": "not_found"}, status=404)
        return idp.page(connection, request_id, relay)


def saml_sp(connection):
    from sso import saml

    return saml.sp_entity_id(connection.org_id)
