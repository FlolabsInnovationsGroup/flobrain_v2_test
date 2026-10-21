from django.urls import path

from integrations.v2_views import CredentialDetailView, CredentialListCreateView, CredentialMetaView
from integrations.views import ToolDetailView, ToolListCreateView

urlpatterns = [
    path("orgs/<uuid:org_id>/tools", ToolListCreateView.as_view(), name="v2-tools"),
    path("orgs/<uuid:org_id>/tools/<uuid:tool_id>", ToolDetailView.as_view(), name="v2-tool-detail"),
    path("orgs/<uuid:org_id>/credentials", CredentialListCreateView.as_view(), name="v2-credentials"),
    path("orgs/<uuid:org_id>/credentials/meta", CredentialMetaView.as_view(), name="v2-credentials-meta"),
    path(
        "orgs/<uuid:org_id>/credentials/<uuid:credential_id>",
        CredentialDetailView.as_view(),
        name="v2-credential-detail",
    ),
]
