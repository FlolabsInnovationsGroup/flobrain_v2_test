from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from core_v2.views import V2APIView
from integrations.models import DEFAULT_TOOLS, ExternalTool
from integrations.serializers import ToolWriteSerializer
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _seed_defaults(org):
    if ExternalTool.objects.filter(org=org).exists():
        return
    for index, (name, url) in enumerate(DEFAULT_TOOLS):
        ExternalTool.objects.create(org=org, name=name, url=url, sort_order=index)


def _payload(tool):
    return {"id": str(tool.id), "name": tool.name, "url": tool.url, "sort_order": tool.sort_order}


class ToolListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        _seed_defaults(org)
        return Response([_payload(tool) for tool in ExternalTool.objects.filter(org=org)])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("tools.manage").has_permission(request, self)
        serializer = ToolWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = (serializer.validated_data.get("name") or "").strip()
        url = serializer.validated_data.get("url") or ""
        if not name:
            return Response({"error": "invalid", "details": "name is required"}, status=400)
        if not url:
            return Response({"error": "invalid", "details": "url is invalid"}, status=400)
        tool = ExternalTool.objects.create(org=org, name=name[:80], url=url)
        return Response(_payload(tool), status=201)


class ToolDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def patch(self, request, org_id, tool_id):
        org = _org(org_id)
        request.org = org
        HasPerm("tools.manage").has_permission(request, self)
        tool = get_object_or_404(ExternalTool, pk=tool_id, org=org)
        serializer = ToolWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "name" in serializer.validated_data:
            name = (serializer.validated_data.get("name") or "").strip()
            if not name:
                return Response({"error": "invalid", "details": "name is required"}, status=400)
            tool.name = name[:80]
        if "url" in serializer.validated_data:
            tool.url = serializer.validated_data["url"]
        if "sort_order" in serializer.validated_data:
            tool.sort_order = serializer.validated_data["sort_order"]
        tool.save()
        return Response(_payload(tool))

    def delete(self, request, org_id, tool_id):
        org = _org(org_id)
        request.org = org
        HasPerm("tools.manage").has_permission(request, self)
        tool = get_object_or_404(ExternalTool, pk=tool_id, org=org)
        tool.delete()
        return Response(status=204)
