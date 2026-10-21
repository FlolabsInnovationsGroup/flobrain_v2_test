from datetime import timedelta

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from users.jwt_utils import get_user_from_request

_LAST_ACTIVE_MIN_INTERVAL = timedelta(minutes=1)


class LastActiveMiddleware(MiddlewareMixin):
    """Throttled last_active update (at most once per minute) for V2 requests."""

    def process_request(self, request):
        if not request.path.startswith("/api/v2/"):
            return None
        user = get_user_from_request(request)
        if user is None:
            return None
        now = timezone.now()
        if user.last_active is None or (now - user.last_active) >= _LAST_ACTIVE_MIN_INTERVAL:
            user.last_active = now
            user.save(update_fields=["last_active"])
        return None
