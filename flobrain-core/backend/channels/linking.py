"""Link a FloBrain person to a WhatsApp number or Telegram chat with a one-time 6-digit code.

The person makes a code in Settings and sends it to the bot from their phone. The code is stored
hashed (HMAC with the server key, bound to the connection), expires after ``CODE_MINUTES``, works
once, and wrong guesses are limited per sender and per connection.
"""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from channels import ratelimit
from channels.models import ChannelLink

CODE_MINUTES = 10
CODE_TEXT = re.compile(r"^\s*(?:link|ربط|bağla|lier|vincular)?\s*(\d{6})\s*$", re.IGNORECASE)
FAIL_WINDOW = 3600


def _hash(connection_id, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"channel-link:{connection_id}:{code}".encode(), hashlib.sha256).hexdigest()


def create_code(user, org, connection) -> tuple[ChannelLink, str]:
    """A fresh pending link with its code (returned once). Older pending codes for this person stop working."""
    ChannelLink.objects.filter(user=user, connection=connection, status=ChannelLink.PENDING).update(status=ChannelLink.EXPIRED, code_hash="")
    code = f"{secrets.randbelow(1_000_000):06d}"
    link = ChannelLink.objects.create(
        org=org,
        user=user,
        connection=connection,
        status=ChannelLink.PENDING,
        code_hash=_hash(connection.id, code),
        code_expires_at=timezone.now() + timedelta(minutes=CODE_MINUTES),
    )
    return link, code


def is_code_attempt(text: str) -> bool:
    return bool(CODE_TEXT.match(text or ""))


def sender_locked(connection, sender: str) -> bool:
    per_sender = ratelimit.limit("link_failures_per_sender", 5)
    per_connection = ratelimit.limit("link_failures_per_connection", 50)
    return (
        ratelimit.count("link-fail-sender", f"{connection.id}:{sender}", FAIL_WINDOW) >= per_sender
        or ratelimit.count("link-fail-conn", str(connection.id), FAIL_WINDOW) >= per_connection
    )


def _fail(connection, sender):
    ratelimit.hit("link-fail-sender", f"{connection.id}:{sender}", 10**9, FAIL_WINDOW)
    ratelimit.hit("link-fail-conn", str(connection.id), 10**9, FAIL_WINDOW)


def redeem(connection, sender: str, sender_name: str, text: str) -> tuple[str, ChannelLink | None]:
    """Try ``text`` as a link code from ``sender``. Returns (outcome, link).

    outcome: linked | wrong | expired | locked | not_a_code
    """
    match = CODE_TEXT.match(text or "")
    if not match:
        return "not_a_code", None
    if sender_locked(connection, sender):
        return "locked", None
    digest = _hash(connection.id, match.group(1))
    now = timezone.now()
    with transaction.atomic():
        link = ChannelLink.objects.select_for_update().filter(connection=connection, status=ChannelLink.PENDING, code_hash=digest).first()
        if link is None:
            _fail(connection, sender)
            return "wrong", None
        if link.code_expires_at is None or link.code_expires_at <= now:
            ChannelLink.objects.filter(pk=link.pk).update(status=ChannelLink.EXPIRED, code_hash="")
            _fail(connection, sender)
            return "expired", None
        from organizations.models import OrgMembership

        member = OrgMembership.objects.filter(org=link.org, user=link.user).first()
        if member is None or not member.is_active_member:
            ChannelLink.objects.filter(pk=link.pk).update(status=ChannelLink.REVOKED, code_hash="")
            return "wrong", None
        # One person per phone/chat and one phone/chat per person on this connection.
        ChannelLink.objects.filter(connection=connection, status=ChannelLink.ACTIVE, external_id=sender).update(status=ChannelLink.REVOKED)
        ChannelLink.objects.filter(connection=connection, status=ChannelLink.ACTIVE, user=link.user).update(status=ChannelLink.REVOKED)
        link.status, link.code_hash, link.external_id = ChannelLink.ACTIVE, "", sender
        link.external_name, link.linked_at = (sender_name or "")[:120], now
        link.save(update_fields=["status", "code_hash", "external_id", "external_name", "linked_at"])
    return "linked", link


def active_link(connection, sender: str) -> ChannelLink | None:
    return (
        ChannelLink.objects.filter(connection=connection, status=ChannelLink.ACTIVE, external_id=sender)
        .select_related("user", "org")
        .first()
    )


def mask(external_id: str, kind: str) -> str:
    value = str(external_id or "")
    if not value:
        return ""
    if kind == "whatsapp":
        return f"+{value[:2]} •••• {value[-4:]}" if len(value) > 6 else "••••"
    return f"Chat •••{value[-3:]}" if len(value) > 3 else "Chat"
