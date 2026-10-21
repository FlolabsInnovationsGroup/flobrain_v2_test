from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.members import can_receive_dm
from users.models import User


class DirectMessageCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("chat.use").has_permission(request, self)
        recipient = get_object_or_404(User, pk=request.data.get("user_id"))
        if not can_receive_dm(recipient, org):
            return Response({"error": "not_found", "details": "Recipient not found"}, status=404)
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"error": "invalid", "details": "body is required"}, status=400)
        return Response({"ok": True, "to": str(recipient.id)}, status=201)
