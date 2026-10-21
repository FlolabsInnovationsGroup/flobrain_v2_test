from django.urls import path

from timetracking.views import (
    CalendarView,
    DashboardMeView,
    TimeApprovalQueueView,
    TimeEntryDetailView,
    TimeEntryListCreateView,
    TimeEntryReviewView,
    TimeEntrySubmitView,
    TimeReportMeView,
    TimeReportTeamView,
    TimerStartView,
    TimerStopView,
    TimerView,
)

urlpatterns = [
    path("orgs/<uuid:org_id>/timer", TimerView.as_view(), name="v2-timer"),
    path("orgs/<uuid:org_id>/timer/start", TimerStartView.as_view(), name="v2-timer-start"),
    path("orgs/<uuid:org_id>/timer/stop", TimerStopView.as_view(), name="v2-timer-stop"),
    path("orgs/<uuid:org_id>/time-entries", TimeEntryListCreateView.as_view(), name="v2-time-entries"),
    path("orgs/<uuid:org_id>/time-entries/submit", TimeEntrySubmitView.as_view(), name="v2-time-entries-submit"),
    path("orgs/<uuid:org_id>/time-entries/approvals", TimeApprovalQueueView.as_view(), name="v2-time-approvals"),
    path("orgs/<uuid:org_id>/time-entries/<uuid:entry_id>", TimeEntryDetailView.as_view(), name="v2-time-entry"),
    path(
        "orgs/<uuid:org_id>/time-entries/<uuid:entry_id>/approve",
        TimeEntryReviewView.as_view(decision="approved"),
        name="v2-time-entry-approve",
    ),
    path(
        "orgs/<uuid:org_id>/time-entries/<uuid:entry_id>/reject",
        TimeEntryReviewView.as_view(decision="rejected"),
        name="v2-time-entry-reject",
    ),
    path("orgs/<uuid:org_id>/time-reports/me", TimeReportMeView.as_view(), name="v2-time-report-me"),
    path(
        "orgs/<uuid:org_id>/time-reports/team/<uuid:team_id>",
        TimeReportTeamView.as_view(),
        name="v2-time-report-team",
    ),
    path("orgs/<uuid:org_id>/dashboard/me", DashboardMeView.as_view(), name="v2-dashboard-me"),
    path("orgs/<uuid:org_id>/calendar", CalendarView.as_view(), name="v2-calendar"),
]
