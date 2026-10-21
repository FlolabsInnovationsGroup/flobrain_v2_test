from django.urls import path

from workers.views import ClaimView, CompleteView, FailView, HeartbeatView

urlpatterns = [
    path("workers/claim", ClaimView.as_view(), name="v2-worker-claim"),
    path("workers/jobs/<uuid:job_id>/heartbeat", HeartbeatView.as_view(), name="v2-worker-heartbeat"),
    path("workers/jobs/<uuid:job_id>/complete", CompleteView.as_view(), name="v2-worker-complete"),
    path("workers/jobs/<uuid:job_id>/fail", FailView.as_view(), name="v2-worker-fail"),
]
