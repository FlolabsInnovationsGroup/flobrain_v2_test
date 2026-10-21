from django.urls import path

from agents.views import ScheduleDetailView, ScheduleListCreateView, ScheduleRunListView, ScheduleRunNowView

urlpatterns = [
    path("orgs/<uuid:org_id>/agents/schedules", ScheduleListCreateView.as_view(), name="v2-agent-schedules"),
    path(
        "orgs/<uuid:org_id>/agents/schedules/<uuid:schedule_id>",
        ScheduleDetailView.as_view(),
        name="v2-agent-schedule",
    ),
    path(
        "orgs/<uuid:org_id>/agents/schedules/<uuid:schedule_id>/runs",
        ScheduleRunListView.as_view(),
        name="v2-agent-schedule-runs",
    ),
    path(
        "orgs/<uuid:org_id>/agents/schedules/<uuid:schedule_id>/run",
        ScheduleRunNowView.as_view(),
        name="v2-agent-schedule-run",
    ),
]
