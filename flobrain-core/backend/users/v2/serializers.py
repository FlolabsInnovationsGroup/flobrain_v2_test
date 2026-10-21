from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from users.models import User

_UserManager = getattr(User, "objects")
_DoesNotExist = getattr(User, "DoesNotExist", Exception)


class V2SignInSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            user = _UserManager.get(email=attrs["email"])
        except _DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")
        if not check_password(attrs["password"], user.password_hash):
            raise serializers.ValidationError("Invalid credentials")
        attrs["user"] = user
        return attrs


class V2RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class V2SignOutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=True)
    refresh_token = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        token = attrs.get("refresh") or attrs.get("refresh_token")
        if not token:
            raise serializers.ValidationError("refresh is required")
        attrs["refresh"] = token
        return attrs


class V2ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class V2ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value


class V2FirstLoginSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        user = self.context.get("user")
        try:
            validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value


class V2MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "user_type",
            "phone",
            "avatar_url",
            "discord_handle",
            "linkedin_url",
            "about_me",
            "must_change_password",
            "timezone",
            "locale",
            "portfolio_slug",
            "is_platform_admin",
        )
        read_only_fields = fields


def hash_password(raw: str) -> str:
    return make_password(raw)
