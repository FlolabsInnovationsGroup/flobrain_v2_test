from django.urls import path

from console import views

urlpatterns = [
    path("platform/orgs", views.PlatformOrgListView.as_view(), name="v2-platform-orgs"),
    path("platform/orgs/<uuid:org_id>/flags", views.PlatformOrgFlagsView.as_view(), name="v2-platform-org-flags"),
    path("platform/impersonations", views.PlatformImpersonationView.as_view(), name="v2-platform-impersonations"),
    path("platform/impersonations/<uuid:session_id>/end", views.PlatformImpersonationEndView.as_view(), name="v2-platform-impersonation-end"),
    path("orgs/<uuid:org_id>/impersonations", views.OrgImpersonationListView.as_view(), name="v2-org-impersonations"),
    path("orgs/<uuid:org_id>/impersonations/<uuid:session_id>/end", views.OrgImpersonationEndView.as_view(), name="v2-org-impersonation-end"),
]
