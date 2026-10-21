from django.urls import include, path

urlpatterns = [
    path("", include("users.v2.urls")),
    path("", include("organizations.urls")),
    path("", include("telemetry.urls")),
    path("", include("integrations_hr.urls")),
    path("", include("tasks.urls")),
    path("", include("timetracking.urls")),
    path("", include("rooms.urls")),
    path("", include("notifications.urls")),
    path("", include("realtime.urls")),
    path("", include("meetings.urls")),
    path("", include("docs_app.urls")),
    path("", include("integrations.urls")),
    path("", include("search.urls")),
    path("", include("brain.v2_urls")),
]
