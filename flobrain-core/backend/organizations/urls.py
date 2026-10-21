from django.urls import path

from organizations.views import (
    AuditEventListView,
    GrantListCreateView,
    GrantRevokeView,
    MyOrgsView,
    PermissionCatalogView,
    PermissionRequestDecideView,
    PermissionRequestListCreateView,
)
from organizations.views_directory import (
    MemberDetailView,
    MemberListCreateView,
    ProjectDetailView,
    ProjectListCreateView,
    TeamDetailView,
    TeamListCreateView,
    TeamMemberListView,
)
from organizations.views_dms import DirectMessageCreateView

urlpatterns = [
    path("orgs", MyOrgsView.as_view(), name="v2-my-orgs"),
    path("orgs/<uuid:org_id>/members", MemberListCreateView.as_view(), name="v2-members"),
    path("orgs/<uuid:org_id>/members/<uuid:user_id>", MemberDetailView.as_view(), name="v2-member-detail"),
    path("orgs/<uuid:org_id>/teams", TeamListCreateView.as_view(), name="v2-teams"),
    path("orgs/<uuid:org_id>/teams/<uuid:team_id>", TeamDetailView.as_view(), name="v2-team-detail"),
    path(
        "orgs/<uuid:org_id>/teams/<uuid:team_id>/members",
        TeamMemberListView.as_view(),
        name="v2-team-members",
    ),
    path("orgs/<uuid:org_id>/projects", ProjectListCreateView.as_view(), name="v2-projects"),
    path(
        "orgs/<uuid:org_id>/projects/<uuid:project_id>",
        ProjectDetailView.as_view(),
        name="v2-project-detail",
    ),
    path("orgs/<uuid:org_id>/grants", GrantListCreateView.as_view(), name="v2-grants"),
    path("orgs/<uuid:org_id>/grants/<uuid:grant_id>", GrantRevokeView.as_view(), name="v2-grant-revoke"),
    path(
        "orgs/<uuid:org_id>/permission-requests",
        PermissionRequestListCreateView.as_view(),
        name="v2-permission-requests",
    ),
    path(
        "orgs/<uuid:org_id>/permission-requests/<uuid:request_id>/<str:decision>",
        PermissionRequestDecideView.as_view(),
        name="v2-permission-request-decide",
    ),
    path("orgs/<uuid:org_id>/audit-events", AuditEventListView.as_view(), name="v2-audit-events"),
    path("orgs/<uuid:org_id>/permissions", PermissionCatalogView.as_view(), name="v2-permission-catalog"),
    path("orgs/<uuid:org_id>/dms", DirectMessageCreateView.as_view(), name="v2-dms"),
]
