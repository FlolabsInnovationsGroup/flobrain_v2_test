from django.urls import path

from exports import views

urlpatterns = [
    path("orgs/<uuid:org_id>/exports/memory", views.MemoryExportListView.as_view(), name="v2-memory-exports"),
    path("orgs/<uuid:org_id>/exports/memory/<uuid:export_id>", views.MemoryExportDetailView.as_view(), name="v2-memory-export"),
]
