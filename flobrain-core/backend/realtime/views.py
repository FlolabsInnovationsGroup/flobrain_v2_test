from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.views import V2PublicAPIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from users.authentication import BearerJWTAuthentication


class RealtimeTicketView(V2PublicAPIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org_id = request.data.get("org_id") or request.headers.get("X-Org-Id")
        org = Organization.objects.filter(pk=org_id, is_active=True).first() if org_id else None
        membership = (
            OrgMembership.objects.filter(org=org, user=request.user).first() if org is not None else None
        )
        if org is None or membership is None or not membership.is_active_member:
            return Response({"error": "permission_denied", "details": "Not an active org member"}, status=403)
        if not effective_flag(org, membership, "realtime", default=False):
            return Response(
                {"error": "unavailable", "details": "Realtime is off; use polling"},
                status=503,
            )
        return Response(
            {"error": "not_implemented", "details": "Realtime is not implemented; use polling"},
            status=501,
        )
