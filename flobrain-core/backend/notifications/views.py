from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from notifications.models import Notification
from notifications.serializers import NotificationReadSerializer
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember


class NotificationListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("notification.view").has_permission(request, self)
        qs = Notification.objects.filter(org=org, user=request.user)
        if request.query_params.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            [
                {
                    "id": str(row.id),
                    "kind": row.kind,
                    "payload": row.payload,
                    "read_at": row.read_at.isoformat() if row.read_at else None,
                    "created_at": row.created_at.isoformat(),
                }
                for row in page
            ]
        )


class NotificationReadView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("notification.view").has_permission(request, self)
        serializer = NotificationReadSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        qs = Notification.objects.filter(org=org, user=request.user, read_at__isnull=True)
        ids = serializer.validated_data.get("ids")
        if ids:
            qs = qs.filter(pk__in=ids)
        updated = qs.update(read_at=timezone.now())
        return Response({"ok": True, "read": updated})
