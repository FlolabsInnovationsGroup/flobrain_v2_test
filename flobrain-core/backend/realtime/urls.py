from django.urls import path

from realtime.views import RealtimeTicketView

urlpatterns = [
    path("realtime/ticket", RealtimeTicketView.as_view(), name="v2-realtime-ticket"),
]
