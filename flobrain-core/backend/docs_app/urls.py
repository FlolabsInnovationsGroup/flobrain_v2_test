from django.urls import path

from docs_app.views import (
    DocumentDetailView,
    DocumentSearchView,
    FileCompleteView,
    FilePresignView,
    RoomDocListCreateView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/rooms/<uuid:room_id>/docs", RoomDocListCreateView.as_view(), name="v2-room-docs"),
    path("orgs/<uuid:org_id>/docs/search", DocumentSearchView.as_view(), name="v2-docs-search"),
    path("orgs/<uuid:org_id>/docs/<uuid:doc_id>", DocumentDetailView.as_view(), name="v2-doc-detail"),
    path("orgs/<uuid:org_id>/files/presign", FilePresignView.as_view(), name="v2-file-presign"),
    path("orgs/<uuid:org_id>/files/<uuid:file_id>/complete", FileCompleteView.as_view(), name="v2-file-complete"),
]
