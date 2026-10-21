from django.urls import path

from connectors import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/integrations", v.CatalogView.as_view(), name="v2-integrations"),
    path("orgs/<uuid:org_id>/integrations/items", v.ItemListView.as_view(), name="v2-integration-items"),
    path("orgs/<uuid:org_id>/integrations/connections/<uuid:connection_id>", v.ConnectionDetailView.as_view(), name="v2-integration-connection"),
    path("orgs/<uuid:org_id>/integrations/connections/<uuid:connection_id>/sync", v.ConnectionSyncView.as_view(), name="v2-integration-sync"),
    path("orgs/<uuid:org_id>/integrations/<str:key>/connect", v.ConnectView.as_view(), name="v2-integration-connect"),
    path("orgs/<uuid:org_id>/tasks/<uuid:task_id>/links", v.TaskLinkView.as_view(), name="v2-task-links"),
]
