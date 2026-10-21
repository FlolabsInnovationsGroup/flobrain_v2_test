from django.urls import path

from tasks.views import (
    MissionControlView,
    ProjectFromTemplateView,
    ProjectTemplateView,
    TaskAssignView,
    TaskDetailView,
    TaskListCreateView,
    TaskMoveView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/tasks", TaskListCreateView.as_view(), name="v2-tasks"),
    path("orgs/<uuid:org_id>/tasks/<uuid:task_id>", TaskDetailView.as_view(), name="v2-task-detail"),
    path("orgs/<uuid:org_id>/tasks/<uuid:task_id>/move", TaskMoveView.as_view(), name="v2-task-move"),
    path("orgs/<uuid:org_id>/tasks/<uuid:task_id>/assign", TaskAssignView.as_view(), name="v2-task-assign"),
    path("orgs/<uuid:org_id>/project-templates", ProjectTemplateView.as_view(), name="v2-project-templates"),
    path("orgs/<uuid:org_id>/projects/from-template", ProjectFromTemplateView.as_view(), name="v2-project-from-template"),
    path("orgs/<uuid:org_id>/mission-control", MissionControlView.as_view(), name="v2-mission-control"),
]
