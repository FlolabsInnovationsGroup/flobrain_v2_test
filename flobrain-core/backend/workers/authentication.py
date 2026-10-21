"""``Authorization: Worker <token>`` for render workers. Never a user session or JWT."""

import hmac

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from workers.models import WorkerToken, hash_token


class WorkerAuthentication(authentication.BaseAuthentication):
    keyword = "Worker"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(self.keyword + " "):
            return None
        raw = header[len(self.keyword) + 1 :].strip()
        if not raw:
            raise exceptions.AuthenticationFailed("worker token required")
        digest = hash_token(raw)
        row = WorkerToken.objects.filter(token_hash=digest, revoked_at__isnull=True).first()
        if row is None or not hmac.compare_digest(row.token_hash, digest):
            raise exceptions.AuthenticationFailed("invalid worker token")
        WorkerToken.objects.filter(pk=row.pk).update(last_seen_at=timezone.now())
        return AnonymousUser(), row

    def authenticate_header(self, request):
        return self.keyword


class IsWorker(permissions.BasePermission):
    """A render worker token (the original kind)."""

    kind = "render"

    def has_permission(self, request, view):
        return isinstance(request.auth, WorkerToken) and request.auth.kind == self.kind


class IsMeetingBotWorker(IsWorker):
    kind = "meeting_bot"
