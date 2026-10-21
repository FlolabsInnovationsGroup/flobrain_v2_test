from django.urls import path

from search.views import GlobalSearchView

urlpatterns = [
    path("orgs/<uuid:org_id>/search", GlobalSearchView.as_view(), name="v2-search"),
]
