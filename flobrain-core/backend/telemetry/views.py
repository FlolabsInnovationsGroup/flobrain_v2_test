from urllib.parse import urlparse

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from telemetry.models import FeedbackItem, ProductEvent

ALLOWED_EVENT_NAMES = frozenset({"page.viewed", "feature.used", "funnel.step"})
ALLOWED_PROPERTIES = frozenset({"page", "feature", "step", "source"})


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _is_org_admin(user, org) -> bool:
    if getattr(user, "is_platform_admin", False):
        return True
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(
        membership
        and membership.is_active_member
        and membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}
    )


def _clean_page(value: str) -> str:
    raw = (value or "").split("?", 1)[0]
    parsed = urlparse(raw)
    return parsed.path or raw


class ProductEventCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        name = (request.data.get("name") or "").strip()
        if name not in ALLOWED_EVENT_NAMES:
            return Response(
                {"error": "invalid_event", "details": "Event name is not allowlisted"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_props = request.data.get("properties") or {}
        if not isinstance(raw_props, dict):
            return Response(
                {"error": "invalid_properties", "details": "properties must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        props = {k: v for k, v in raw_props.items() if k in ALLOWED_PROPERTIES}
        if "page" in props:
            props["page"] = _clean_page(str(props["page"]))
        event = ProductEvent.objects.create(org=org, user=request.user, name=name, properties=props)
        return Response({"id": str(event.id), "ok": True}, status=status.HTTP_201_CREATED)


class FeedbackCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        kind = request.data.get("kind")
        text = (request.data.get("text") or "").strip()
        page = _clean_page(request.data.get("page") or "")
        if kind not in {c[0] for c in FeedbackItem.KIND_CHOICES} or not text:
            return Response(
                {"error": "invalid_feedback", "details": "kind and text are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item = FeedbackItem.objects.create(
            org=org,
            user=request.user,
            page=page,
            kind=kind,
            text=text,
            screenshot_file=request.data.get("screenshot_file") or "",
        )
        return Response({"id": str(item.id), "ok": True}, status=status.HTTP_201_CREATED)


class AdminFeedbackListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        if not _is_org_admin(request.user, org):
            return Response({"error": "permission_denied", "details": "Admin only"}, status=status.HTTP_403_FORBIDDEN)
        qs = FeedbackItem.objects.filter(org=org).order_by("-created_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = [
            {
                "id": str(item.id),
                "kind": item.kind,
                "page": item.page,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in page
        ]
        return paginator.get_paginated_response(data)


class AdminAnalyticsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        if not _is_org_admin(request.user, org):
            return Response({"error": "permission_denied", "details": "Admin only"}, status=status.HTTP_403_FORBIDDEN)
        names = list(
            ProductEvent.objects.filter(org=org).values_list("name", flat=True).distinct()
        )
        return Response({"event_names": names, "count": ProductEvent.objects.filter(org=org).count()})
