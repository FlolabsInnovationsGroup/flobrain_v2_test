from django.conf import settings
from rest_framework.throttling import UserRateThrottle


class AISendThrottle(UserRateThrottle):
    """Per-user limit for AI send. Rate comes from FLOBRAIN_V2, default 30/min."""

    scope = "ai_send"

    def get_rate(self):
        return settings.FLOBRAIN_V2.get("AI_SEND_RATE", "30/min")
