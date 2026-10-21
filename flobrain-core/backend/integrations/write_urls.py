from django.urls import path

from integrations import write_views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/integrations/write", v.WriteCatalogView.as_view(), name="v2-write-integrations"),
    path("orgs/<uuid:org_id>/integrations/write/log", v.WriteLogView.as_view(), name="v2-write-log"),
    path("orgs/<uuid:org_id>/integrations/write/confirm", v.WriteConfirmView.as_view(), name="v2-write-confirm"),
    path(
        "orgs/<uuid:org_id>/integrations/write/connections/<uuid:connection_id>",
        v.WriteConnectionDetailView.as_view(),
        name="v2-write-connection",
    ),
    path("orgs/<uuid:org_id>/integrations/write/actions/<str:tool>", v.WriteActionToggleView.as_view(), name="v2-write-action"),
    path("orgs/<uuid:org_id>/integrations/write/<str:provider>/connect", v.WriteConnectView.as_view(), name="v2-write-connect"),
    path("integrations/write/oauth/callback/<str:provider>", v.WriteOAuthCallbackView.as_view(), name="v2-write-oauth-callback"),
]
