from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
import re
from zoneinfo import available_timezones

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


PHONE = re.compile(r"^\+[1-9]\d{7,14}$")
LOCALES = ("en", "ar", "tr", "fr", "pt")


def normalize_phone(raw) -> str:
    """E.164: a plus, a country code and 8 to 15 digits. Spaces, dots, dashes and brackets are dropped;
    a leading 00 becomes +. Raises ValidationError with a sentence for the form."""
    value = re.sub(r"[\s().-]", "", str(raw or ""))
    if value.startswith("00"):
        value = "+" + value[2:]
    if not PHONE.fullmatch(value):
        raise serializers.ValidationError("Enter the number with its country code, like +20 100 123 4567")
    return value


class V2FirstLoginSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def validate_phone(self, value):
        if not value:
            return ""
        return normalize_phone(value)

    def validate(self, attrs):
        user = self.context.get("user")
        # Decision 10: first sign-in sets a password and a phone number (unless one is on file).
        if not attrs.get("phone") and not (user is not None and user.phone):
            raise serializers.ValidationError({"phone": "Add your phone number"})
        return attrs

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


class V2MeUpdateSerializer(serializers.Serializer):
    """What a person edits on their own profile. Email, role and type are not here."""

    username = serializers.CharField(required=False, max_length=150)
    phone = serializers.CharField(required=False, max_length=40)
    timezone = serializers.CharField(required=False, allow_blank=True, max_length=64)
    locale = serializers.ChoiceField(required=False, choices=LOCALES)
    about_me = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    discord_handle = serializers.CharField(required=False, allow_blank=True, max_length=100)
    linkedin_url = serializers.URLField(required=False, allow_blank=True, max_length=200)

    def validate_username(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Your name can't be empty")
        return name

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_timezone(self, value):
        if value and value not in _timezones():
            raise serializers.ValidationError("Pick a time zone from the list, like Africa/Cairo")
        return value or None

    def validate_linkedin_url(self, value):
        if value and not value.lower().startswith(("https://", "http://")):
            raise serializers.ValidationError("Use a full https:// link")
        return value or None


_TZ_CACHE: set[str] = set()


def _timezones() -> set[str]:
    if not _TZ_CACHE:
        _TZ_CACHE.update(available_timezones())
    return _TZ_CACHE
