from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView, V2PublicAPIView
from organizations.models import AuditEvent, OrgMembership, Organization, PermissionGrant, PermissionRequest
from organizations.permissions import HasPerm, IsActiveOrgMember
from users.authentication import BearerJWTAuthentication
from organizations.permissions.registry import PERMISSION_CATALOG
from organizations.serializers import (
    AuditEventSerializer,
    PermissionGrantSerializer,
    PermissionRequestSerializer,
)
from organizations.services import audit, decide_request, grant_permission


def _org(kwargs) -> Organization:
    return get_object_or_404(Organization, pk=kwargs["org_id"], is_active=True)


class MyOrgsView(V2PublicAPIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Organization.objects.filter(
            is_active=True,
            memberships__user=request.user,
            memberships__employment_status=OrgMembership.STATUS_ACTIVE,
        ).distinct()
        slug = request.query_params.get("slug")
        if slug:
            qs = qs.filter(slug=slug)
        return Response([{"id": str(org.id), "slug": org.slug, "name": org.name} for org in qs])


class GrantListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        grants = PermissionGrant.objects.filter(org=org).order_by("-created_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(grants, request, view=self)
        return paginator.get_paginated_response(PermissionGrantSerializer(page, many=True).data)

    def post(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("grants.create").has_permission(request, self)
        serializer = PermissionGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = grant_permission(
            org,
            request.user,
            serializer.validated_data["grantee"],
            serializer.validated_data["perm_key"],
            scope_type=serializer.validated_data.get("scope_type") or "org",
            scope_id=serializer.validated_data.get("scope_id"),
            request=request,
        )
        return Response(PermissionGrantSerializer(grant).data, status=status.HTTP_201_CREATED)


class GrantRevokeView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    required_perm = "grants.revoke"

    def delete(self, request, org_id, grant_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("grants.revoke").has_permission(request, self)
        grant = get_object_or_404(PermissionGrant, pk=grant_id, org=org)
        if grant.revoked_at is None:
            grant.revoked_at = timezone.now()
            grant.revoked_by = request.user
            grant.save(update_fields=["revoked_at", "revoked_by"])
            audit(request.user, "perm.revoke", target=grant, request=request, org=org)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PermissionRequestListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        qs = PermissionRequest.objects.filter(org=org).order_by("-created_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(PermissionRequestSerializer(page, many=True).data)

    def post(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("permission_requests.create").has_permission(request, self)
        serializer = PermissionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = PermissionRequest.objects.create(
            org=org,
            requester=request.user,
            perm_key=serializer.validated_data["perm_key"],
            scope_type=serializer.validated_data.get("scope_type") or "org",
            scope_id=serializer.validated_data.get("scope_id"),
            reason=serializer.validated_data.get("reason") or "",
        )
        audit(request.user, "perm.request.create", target=req, request=request, org=org)
        return Response(PermissionRequestSerializer(req).data, status=status.HTTP_201_CREATED)


class PermissionRequestDecideView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    required_perm = "permission_requests.decide"

    def post(self, request, org_id, request_id, decision):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("permission_requests.decide").has_permission(request, self)
        req = get_object_or_404(PermissionRequest, pk=request_id, org=org)
        decide_request(req, request.user, approve=(decision == "approve"), request=request)
        return Response(PermissionRequestSerializer(req).data)


class AuditEventListView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    required_perm = "audit.view"

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("audit.view").has_permission(request, self)
        qs = AuditEvent.objects.filter(org=org).order_by("-created_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(AuditEventSerializer(page, many=True).data)


class PermissionCatalogView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org({"org_id": org_id})
        request.org = org
        HasPerm("org.members.view").has_permission(request, self)
        return Response(
            [{"key": key, **meta} for key, meta in PERMISSION_CATALOG.items()]
        )
