"""
JWT creation and validation for auth (custom User model, not Django AUTH_USER_MODEL).
"""
import time
import uuid
from typing import Optional

import jwt
from django.conf import settings

# Token lifetimes (seconds)
ACCESS_LIFETIME = 60 * 60  # 1 hour
REFRESH_LIFETIME = 7 * 24 * 60 * 60  # 7 days
ALGORITHM = "HS256"


def make_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "exp": int(time.time()) + ACCESS_LIFETIME,
        "iat": int(time.time()),
    }
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def make_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "exp": int(time.time()) + REFRESH_LIFETIME,
        "iat": int(time.time()),
    }
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
    except jwt.InvalidTokenError:
        return None


def get_user_from_request(request):
    """Extract users.User from Authorization: Bearer <access_token>. None if invalid."""
    from users.models import User

    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None
