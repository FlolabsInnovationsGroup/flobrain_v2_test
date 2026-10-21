from django.urls import path

from notifications.views import NotificationListView, NotificationReadView

urlpatterns = [
    path("orgs/<uuid:org_id>/notifications", NotificationListView.as_view(), name="v2-notifications"),
    path("orgs/<uuid:org_id>/notifications/read", NotificationReadView.as_view(), name="v2-notifications-read"),
]
