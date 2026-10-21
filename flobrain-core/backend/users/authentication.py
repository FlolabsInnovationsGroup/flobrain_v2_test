from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from users.jwt_utils import decode_token, get_user_from_request, issued_before_password_change


class BearerJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        user = get_user_from_request(request)
        if user is None:
            header = request.META.get("HTTP_AUTHORIZATION") or ""
            if header.startswith("Bearer "):
                # Read-only, org-bound support sessions (Phase 17e); never accepted outside V2.
                from console.impersonation import authenticate as impersonate

                found = impersonate(request, header[7:].strip())
                if found is not None:
                    return found
                raise AuthenticationFailed("Invalid or expired token")
            return None
        token = (request.META.get("HTTP_AUTHORIZATION") or "")[7:].strip()
        payload = decode_token(token) or {}
        if issued_before_password_change(payload, user):
            raise AuthenticationFailed("Token issued before last password change")
        return (user, payload)

    def authenticate_header(self, request):
        return 'Bearer realm="api"'


class BearerJWTAuthenticationScheme:
    """Registered below so spectacular can import it lazily."""


try:
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class BearerJWTAuthenticationExtension(OpenApiAuthenticationExtension):
        target_class = "users.authentication.BearerJWTAuthentication"
        name = "BearerJWT"

        def get_security_definition(self, auto_schema):
            return {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }

except ImportError:  # spectacular is optional for unit tests that skip schema
    pass
