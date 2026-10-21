from django.urls import path

from integrations.views import ToolDetailView, ToolListCreateView

urlpatterns = [
    path("orgs/<uuid:org_id>/tools", ToolListCreateView.as_view(), name="v2-tools"),
    path("orgs/<uuid:org_id>/tools/<uuid:tool_id>", ToolDetailView.as_view(), name="v2-tool-detail"),
]
