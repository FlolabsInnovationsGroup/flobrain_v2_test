from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.views import V2APIView, V2PublicAPIView
from notifications.models import NotificationPreference, PushSubscription
from notifications.push import endpoint_allowed

TYPES = (
    "meeting_started", "team_chat_message", "project_chat_message", "ai_response", "direct_message", "task_assigned",
    "task_deadline_reached", "announcement", "action_proposed", "publish_failed", "render_finished", "permission_request",
    "budget_alert", "agent_paused", "impersonation_started", "meeting_summary_ready",
)


# The customer is promised that support access is always visible.
ALWAYS_ON = {"impersonation_started"}


class VapidKeyView(V2PublicAPIView):
    @extend_schema(summary="Web Push public key (empty when push is not set up)")
    def get(self, request):
        return Response({"public_key": getattr(settings, "VAPID_PUBLIC_KEY", "") or ""})


class PushSubscriptionView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Register this browser for push")
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        endpoint = str(data.get("endpoint") or "")
        keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
        p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
        if not endpoint_allowed(endpoint) or len(endpoint) > 800:
            return Response({"error": "invalid", "details": "Not a browser push endpoint"}, status=400)
        if not (20 <= len(p256dh) <= 200 and 8 <= len(auth) <= 100):
            return Response({"error": "invalid", "details": "keys.p256dh and keys.auth are required"}, status=400)
        PushSubscription.objects.filter(endpoint=endpoint).exclude(user=request.user).delete()
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={"user": request.user, "p256dh": p256dh, "auth": auth, "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200]},
        )
        return Response({"subscribed": True}, status=201)

    @extend_schema(summary="Stop push for this browser")
    def delete(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        PushSubscription.objects.filter(user=request.user, endpoint=str(data.get("endpoint") or "")).delete()
        return Response(status=204)


class PreferenceView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="My notification preferences, one row per type")
    def get(self, request):
        rows = {p.type: p for p in NotificationPreference.objects.filter(user=request.user)}
        return Response(
            [
                {
                    "type": t,
                    "enabled": rows[t].enabled if t in rows else True,
                    "push": rows[t].push if t in rows else True,
                    "sound": rows[t].sound_key if t in rows else "chime",
                }
                for t in TYPES
            ]
        )

    @extend_schema(summary="Change one notification type")
    def put(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        kind = data.get("type")
        if kind not in TYPES:
            return Response({"error": "invalid", "details": "unknown type"}, status=400)
        defaults = {}
        if kind in ALWAYS_ON and data.get("enabled") is False:
            return Response({"error": "invalid", "details": "Support-access notices can't be turned off"}, status=400)
        for key in ("enabled", "push"):
            if key in data:
                if not isinstance(data[key], bool):
                    return Response({"error": "invalid", "details": f"{key} must be true or false"}, status=400)
                defaults[key] = data[key]
        if "sound" in data:
            if data["sound"] not in NotificationPreference.SOUNDS:
                return Response({"error": "invalid", "details": "unknown sound"}, status=400)
            defaults["sound_key"] = data["sound"]
        row, _ = NotificationPreference.objects.update_or_create(user=request.user, type=kind, defaults=defaults)
        return Response({"type": row.type, "enabled": row.enabled, "push": row.push, "sound": row.sound_key})
