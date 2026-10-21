from django.urls import path

from imports import views

P = "orgs/<uuid:org_id>/imports"

urlpatterns = [
    path(f"{P}", views.RunListView.as_view(), name="v2-imports"),
    path(f"{P}/meta", views.MetaView.as_view(), name="v2-imports-meta"),
    path(f"{P}/upload", views.UploadView.as_view(), name="v2-imports-upload"),
    path(f"{P}/sample", views.SampleView.as_view(), name="v2-imports-sample"),
    path(f"{P}/notion/pages", views.NotionPagesView.as_view(), name="v2-imports-notion-pages"),
    path(f"{P}/notion", views.NotionImportView.as_view(), name="v2-imports-notion"),
    path(f"{P}/drive/files", views.DriveFilesView.as_view(), name="v2-imports-drive-files"),
    path(f"{P}/drive", views.DriveImportView.as_view(), name="v2-imports-drive"),
    path(f"{P}/<uuid:run_id>", views.RunDetailView.as_view(), name="v2-imports-run"),
    path(f"{P}/<uuid:run_id>/start", views.StartView.as_view(), name="v2-imports-start"),
    path(f"{P}/<uuid:run_id>/cancel", views.CancelView.as_view(), name="v2-imports-cancel"),
    path(f"{P}/<uuid:run_id>/resume", views.ResumeView.as_view(), name="v2-imports-resume"),
    path(f"{P}/<uuid:run_id>/undo", views.UndoView.as_view(), name="v2-imports-undo"),
]
