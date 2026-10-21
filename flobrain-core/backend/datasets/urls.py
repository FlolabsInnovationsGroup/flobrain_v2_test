from django.urls import path

from datasets import views

P = "orgs/<uuid:org_id>/data"

urlpatterns = [
    path(f"{P}/meta", views.MetaView.as_view(), name="v2-data-meta"),
    path(f"{P}/settings", views.SettingsView.as_view(), name="v2-data-settings"),
    path(f"{P}/datasets", views.DatasetListView.as_view(), name="v2-data-datasets"),
    path(f"{P}/datasets/upload", views.UploadView.as_view(), name="v2-data-upload"),
    path(f"{P}/datasets/sheet", views.SheetView.as_view(), name="v2-data-sheet"),
    path(f"{P}/datasets/postgres", views.PostgresView.as_view(), name="v2-data-postgres"),
    path(f"{P}/datasets/<uuid:dataset_id>", views.DatasetDetailView.as_view(), name="v2-data-dataset"),
    path(f"{P}/datasets/<uuid:dataset_id>/refresh", views.RefreshView.as_view(), name="v2-data-refresh"),
    path(f"{P}/ask", views.AskView.as_view(), name="v2-data-ask"),
    path(f"{P}/cards", views.CardListView.as_view(), name="v2-data-cards"),
    path(f"{P}/cards/<uuid:card_id>", views.CardDetailView.as_view(), name="v2-data-card"),
    path(f"{P}/cards/<uuid:card_id>/run", views.CardRunView.as_view(), name="v2-data-card-run"),
    path(f"{P}/reports", views.ReportListView.as_view(), name="v2-data-reports"),
    path(f"{P}/reports/<uuid:report_id>", views.ReportDetailView.as_view(), name="v2-data-report"),
    path(f"{P}/reports/<uuid:report_id>/run", views.ReportRunView.as_view(), name="v2-data-report-run"),
]
