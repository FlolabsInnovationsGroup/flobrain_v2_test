from django.urls import path

from workspace import views

urlpatterns = [
    path("me/cockpit-layout", views.CockpitLayoutView.as_view(), name="v2-cockpit-layout"),
    path("orgs/<uuid:org_id>/me/presence", views.PresenceView.as_view(), name="v2-presence"),
]
