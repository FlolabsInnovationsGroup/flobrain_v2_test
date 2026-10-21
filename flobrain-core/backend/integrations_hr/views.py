import hashlib
import hmac
import json

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import HRApplicant, Organization
from organizations.services.members import register_member


class HRApplicantWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        secret = getattr(settings, "HR_WEBHOOK_SECRET", "") or ""
        if not secret:
            return Response({"error": "unavailable", "details": "HR webhook is not configured"}, status=503)
        provided = request.headers.get("X-Flobrain-Signature") or request.META.get("HTTP_X_FLOBRAIN_SIGNATURE", "")
        raw = request.body or b""
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            return Response({"error": "invalid_signature", "details": "HMAC mismatch"}, status=401)
        try:
            data = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return Response({"error": "invalid_json", "details": "Body must be JSON"}, status=400)
        org = get_object_or_404(Organization, slug=data.get("org_slug") or "flolabs", is_active=True)
        email = (data.get("email") or "").strip().lower()
        if not email:
            return Response({"error": "invalid", "details": "email is required"}, status=400)
        from django.db import transaction

        from billing_v2.entitlements import seat_blocked

        with transaction.atomic():
            if seat_blocked(org, email=email) is not None:
                return Response({"error": "seat_limit", "details": "All seats are taken"}, status=409)
            membership, user, _temp = register_member(
                org,
                None,
                email,
                username=data.get("full_name") or "",
            )
        applicant = HRApplicant.objects.create(
            org=org,
            email=email,
            full_name=data.get("full_name") or email,
            source=data.get("source") or "hr_webhook",
            reference=data.get("reference") or "",
            payload={"keys": sorted(data.keys())},
            membership=membership,
        )
        return Response({"id": str(applicant.id), "user_id": str(user.id)}, status=201)
