from django.urls import path

from notifications.views import NotificationListView, NotificationReadView
from notifications.views_push import PreferenceView, PushSubscriptionView, VapidKeyView

urlpatterns = [
    path("orgs/<uuid:org_id>/notifications", NotificationListView.as_view(), name="v2-notifications"),
    path("orgs/<uuid:org_id>/notifications/read", NotificationReadView.as_view(), name="v2-notifications-read"),
    path("push/vapid-public-key", VapidKeyView.as_view(), name="v2-vapid"),
    path("me/push-subscriptions", PushSubscriptionView.as_view(), name="v2-push-subscriptions"),
    path("me/notification-preferences", PreferenceView.as_view(), name="v2-notification-prefs"),
]
