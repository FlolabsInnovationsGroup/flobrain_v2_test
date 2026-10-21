from django.urls import path

from docs_app.views import (
    DocumentDetailView,
    DocumentFileListView,
    DocumentRestoreView,
    DocumentRevisionDetailView,
    DocumentRevisionListView,
    DocumentSearchView,
    FileCompleteView,
    FileDetailView,
    FileDownloadView,
    FilePresignView,
    FileUploadView,
    RoomDocListCreateView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/docs", RoomDocListCreateView.as_view(), name="v2-room-docs"),
    path("orgs/<uuid:org_id>/docs/search", DocumentSearchView.as_view(), name="v2-docs-search"),
    path("orgs/<uuid:org_id>/docs/<uuid:doc_id>", DocumentDetailView.as_view(), name="v2-doc-detail"),
    path("orgs/<uuid:org_id>/docs/<uuid:doc_id>/revisions", DocumentRevisionListView.as_view(), name="v2-doc-revisions"),
    path("orgs/<uuid:org_id>/docs/<uuid:doc_id>/revisions/<int:version>", DocumentRevisionDetailView.as_view(), name="v2-doc-revision"),
    path("orgs/<uuid:org_id>/docs/<uuid:doc_id>/revisions/<int:version>/restore", DocumentRestoreView.as_view(), name="v2-doc-restore"),
    path("orgs/<uuid:org_id>/docs/<uuid:doc_id>/files", DocumentFileListView.as_view(), name="v2-doc-files"),
    path("orgs/<uuid:org_id>/files/presign", FilePresignView.as_view(), name="v2-file-presign"),
    path("orgs/<uuid:org_id>/files/<uuid:file_id>", FileDetailView.as_view(), name="v2-file-detail"),
    path("orgs/<uuid:org_id>/files/<uuid:file_id>/upload", FileUploadView.as_view(), name="v2-file-upload"),
    path("orgs/<uuid:org_id>/files/<uuid:file_id>/complete", FileCompleteView.as_view(), name="v2-file-complete"),
    path("orgs/<uuid:org_id>/files/<uuid:file_id>/download", FileDownloadView.as_view(), name="v2-file-download"),
]
