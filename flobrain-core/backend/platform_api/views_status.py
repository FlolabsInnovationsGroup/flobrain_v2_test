"""Public status endpoints (Phase 14f), signed out:

- ``GET  /api/public/status``: the sanitized projection (same as ``manage.py export_status``)
- ``POST /api/public/status/subscribe {email}``: always 202; a confirm link is emailed
- ``POST /api/public/status/confirm {token}``
- ``POST /api/public/status/unsubscribe {token}``
"""

import re

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from core_v2.views import V2PublicAPIView
from platform_api import status

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class StatusSubscribeThrottle(AnonRateThrottle):
    scope = "status_subscribe"

    def get_rate(self):
        return "10/hour"


class PublicStatusView(V2PublicAPIView):
    @extend_schema(summary="Public status: components and public platform incidents (no org data)")
    def get(self, request):
        response = Response(status.projection())
        response["Cache-Control"] = "public, max-age=30"
        return response


class StatusSubscribeView(V2PublicAPIView):
    throttle_classes = [StatusSubscribeThrottle]

    @extend_schema(summary="Ask for incident emails; a confirm link is sent")
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        email = data.get("email")
        if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
            return Response({"error": "invalid", "details": "Enter a valid email address"}, status=400)
        status.subscribe(email)
        return Response({"ok": True, "details": "If that address can get email, a confirm link is on its way."}, status=202)


class StatusConfirmView(V2PublicAPIView):
    throttle_classes = [StatusSubscribeThrottle]

    @extend_schema(summary="Confirm a status subscription from the emailed link")
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        token = data.get("token")
        if not isinstance(token, str) or not token or len(token) > 200:
            return Response({"error": "invalid", "details": "The link is not valid"}, status=400)
        sub = status.confirm(token)
        if sub is None:
            return Response({"error": "not_found", "details": "This link was already used or is not valid"}, status=404)
        return Response({"ok": True, "unsubscribe": status.unsubscribe_token(sub)})


class StatusUnsubscribeView(V2PublicAPIView):
    throttle_classes = [StatusSubscribeThrottle]

    @extend_schema(summary="Stop status emails (link from any status email)")
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        token = data.get("token")
        if not isinstance(token, str) or not token or len(token) > 200:
            return Response({"error": "invalid", "details": "The link is not valid"}, status=400)
        status.unsubscribe(token)
        return Response({"ok": True})  # same answer either way
