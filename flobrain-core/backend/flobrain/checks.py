import os

from django.conf import settings
from django.core.checks import Error, Warning, register

_ZERO_AES = "0" * 64


def _aes_key() -> str:
    return os.environ.get("AES_MASTER_KEY", _ZERO_AES)


@register()
def check_aes_master_key(app_configs, **kwargs):
    """Refuse a missing or all-zero AES_MASTER_KEY in non-DEBUG, unless overridden."""
    errors = []
    key = _aes_key()
    insecure = not key or key == _ZERO_AES
    allow = os.environ.get("ALLOW_INSECURE_AES_MASTER_KEY") == "1"
    testing = getattr(settings, "TESTING", False)
    if insecure and not settings.DEBUG and not allow and not testing:
        errors.append(
            Error(
                "AES_MASTER_KEY is missing or all zeros. Set a 64-char hex key, "
                "or set ALLOW_INSECURE_AES_MASTER_KEY=1 until production archives "
                "are checked (Open Question 12).",
                id="flobrain.E001",
            )
        )
    return errors


@register()
def check_secret_key_strength(app_configs, **kwargs):
    warnings = []
    secret = settings.SECRET_KEY or ""
    if len(secret) < 32 or secret.startswith("django-insecure"):
        warnings.append(
            Warning(
                "SECRET_KEY is shorter than 32 bytes or uses the django-insecure prefix. "
                "HS256 tokens should use a longer key (Open Question 31).",
                id="flobrain.W001",
            )
        )
    return warnings
