import hashlib
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core_v2.views import V2PublicAPIView
from organizations.services.members import v2_workspace_signin_allowed
from users.authentication import BearerJWTAuthentication
from users.jwt_utils import decode_token, make_access_token, make_refresh_token
from users.models import BlacklistedRefreshToken, PasswordResetToken, User
from users.v2.serializers import (
    V2FirstLoginSerializer,
    V2ForgotPasswordSerializer,
    V2MeSerializer,
    V2RefreshSerializer,
    V2ResetPasswordSerializer,
    V2SignInSerializer,
    V2SignOutSerializer,
    hash_password,
)

_UserManager = getattr(User, "objects")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _tokens_for(user: User) -> dict:
    return {
        "access": make_access_token(str(user.id)),
        "refresh": make_refresh_token(str(user.id)),
        "user_id": str(user.id),
        "must_change_password": bool(user.must_change_password),
    }


class V2SignInView(V2PublicAPIView):
    def post(self, request):
        serializer = V2SignInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        if not v2_workspace_signin_allowed(user):
            return Response(
                {
                    "error": "membership_inactive",
                    "details": "Pending or inactive members cannot sign in",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(_tokens_for(user))


class V2RefreshView(V2PublicAPIView):
    def post(self, request):
        serializer = V2RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh = serializer.validated_data["refresh"]
        payload = decode_token(refresh)
        if not payload or payload.get("type") != "refresh":
            return Response(
                {"error": "invalid_token", "details": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if BlacklistedRefreshToken.objects.filter(token_hash=_hash_token(refresh)).exists():
            return Response(
                {"error": "revoked_token", "details": "Please sign in again"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        user_id = payload.get("sub")
        try:
            user = _UserManager.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "invalid_token", "details": "User not found"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if user.password_changed_at and payload.get("iat") is not None:
            if int(payload["iat"]) < int(user.password_changed_at.timestamp()):
                return Response(
                    {"error": "stale_token", "details": "Token issued before last password change"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
        return Response({"access": make_access_token(str(user.id))})


class V2SignOutView(V2PublicAPIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = V2SignOutSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        refresh = serializer.validated_data["refresh"]
        payload = decode_token(refresh)
        if not payload or payload.get("type") != "refresh" or payload.get("sub") != str(request.user.id):
            return Response(
                {"error": "invalid_token", "details": "Invalid refresh token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        exp = payload.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp, tz=dt_timezone.utc)
            if exp is not None
            else timezone.now()
        )
        BlacklistedRefreshToken.objects.update_or_create(
            token_hash=_hash_token(refresh),
            defaults={"expires_at": expires_at},
        )
        return Response({"ok": True})


class V2ForgotPasswordView(V2PublicAPIView):
    def post(self, request):
        serializer = V2ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = _UserManager.filter(email=email).first()
        if user:
            raw = secrets.token_urlsafe(32)
            PasswordResetToken.objects.create(
                user=user,
                token_hash=_hash_token(raw),
                expires_at=timezone.now() + timedelta(hours=1),
            )
            base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
            reset_url = f"{base}/w/reset-password?token={raw}"
            send_mail(
                subject="Reset your FloBrain password",
                message=f"Reset your password: {reset_url}",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
                recipient_list=[user.email],
                fail_silently=True,
            )
        return Response({"ok": True})


class V2ResetPasswordView(V2PublicAPIView):
    def post(self, request):
        serializer = V2ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_row = (
            PasswordResetToken.objects.filter(
                token_hash=_hash_token(serializer.validated_data["token"]),
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("user")
            .first()
        )
        if token_row is None:
            return Response(
                {"error": "invalid_token", "details": "Reset token is invalid or expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = token_row.user
        user.password_hash = hash_password(serializer.validated_data["password"])
        user.password_changed_at = timezone.now()
        user.must_change_password = False
        user.save(update_fields=["password_hash", "password_changed_at", "must_change_password"])
        token_row.used_at = timezone.now()
        token_row.save(update_fields=["used_at"])
        return Response({"ok": True})


class V2FirstLoginView(V2PublicAPIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = V2FirstLoginSerializer(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.password_hash = hash_password(serializer.validated_data["password"])
        user.password_changed_at = timezone.now()
        user.must_change_password = False
        user.temp_password_expires_at = None
        user.save(
            update_fields=[
                "password_hash",
                "password_changed_at",
                "must_change_password",
                "temp_password_expires_at",
            ]
        )
        return Response(_tokens_for(user))


class V2MeView(V2PublicAPIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(V2MeSerializer(request.user).data)
