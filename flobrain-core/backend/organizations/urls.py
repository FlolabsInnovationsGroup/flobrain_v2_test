from django.urls import path

from organizations.views import (
    AuditActionListView,
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
    ProjectMemberDetailView,
    ProjectMemberListView,
    TeamDetailView,
    TeamListCreateView,
    TeamMemberDetailView,
    TeamMemberListView,
)
from organizations.views_dms import DirectMessageCreateView
from organizations.views_access_me import MyAccessView
from organizations.views_policy import OrgPolicyView
from organizations.views_skills import MemberSkillDetailView, MemberSkillListView, TaskSuggestAssigneeView

urlpatterns = [
    path("orgs/<uuid:org_id>/policy", OrgPolicyView.as_view(), name="v2-org-policy"),
    path("orgs", MyOrgsView.as_view(), name="v2-my-orgs"),
    path("orgs/<uuid:org_id>/members", MemberListCreateView.as_view(), name="v2-members"),
    path("orgs/<uuid:org_id>/members/<uuid:user_id>", MemberDetailView.as_view(), name="v2-member-detail"),
    path("orgs/<uuid:org_id>/members/<uuid:user_id>/skills", MemberSkillListView.as_view(), name="v2-member-skills"),
    path(
        "orgs/<uuid:org_id>/members/<uuid:user_id>/skills/<int:skill_id>",
        MemberSkillDetailView.as_view(),
        name="v2-member-skill-detail",
    ),
    path(
        "orgs/<uuid:org_id>/tasks/<uuid:task_id>/suggest-assignee",
        TaskSuggestAssigneeView.as_view(),
        name="v2-task-suggest-assignee",
    ),
    path("orgs/<uuid:org_id>/teams", TeamListCreateView.as_view(), name="v2-teams"),
    path("orgs/<uuid:org_id>/teams/<uuid:team_id>", TeamDetailView.as_view(), name="v2-team-detail"),
    path(
        "orgs/<uuid:org_id>/teams/<uuid:team_id>/members",
        TeamMemberListView.as_view(),
        name="v2-team-members",
    ),
    path(
        "orgs/<uuid:org_id>/teams/<uuid:team_id>/members/<uuid:user_id>",
        TeamMemberDetailView.as_view(),
        name="v2-team-member-detail",
    ),
    path("orgs/<uuid:org_id>/projects", ProjectListCreateView.as_view(), name="v2-projects"),
    path(
        "orgs/<uuid:org_id>/projects/<uuid:project_id>",
        ProjectDetailView.as_view(),
        name="v2-project-detail",
    ),
    path(
        "orgs/<uuid:org_id>/projects/<uuid:project_id>/members",
        ProjectMemberListView.as_view(),
        name="v2-project-members",
    ),
    path(
        "orgs/<uuid:org_id>/projects/<uuid:project_id>/members/<uuid:user_id>",
        ProjectMemberDetailView.as_view(),
        name="v2-project-member-detail",
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
    path("orgs/<uuid:org_id>/audit-events/actions", AuditActionListView.as_view(), name="v2-audit-actions"),
    path("orgs/<uuid:org_id>/permissions", PermissionCatalogView.as_view(), name="v2-permission-catalog"),
    path("orgs/<uuid:org_id>/me/access", MyAccessView.as_view(), name="v2-my-access"),
    path("orgs/<uuid:org_id>/dms", DirectMessageCreateView.as_view(), name="v2-dms"),
]
