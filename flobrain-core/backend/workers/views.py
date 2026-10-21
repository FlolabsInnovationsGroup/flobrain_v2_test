"""Worker API (Phase 9b). ``Authorization: Worker <token>`` only; no user tokens accepted."""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from content_studio import renders
from core_v2.errors import v2_exception_handler
from workers.authentication import IsWorker, WorkerAuthentication


class WorkerAPIView(APIView):
    authentication_classes = [WorkerAuthentication]
    permission_classes = [IsWorker]
    throttle_classes = []

    def get_exception_handler(self):
        return v2_exception_handler


def _gone():
    return Response({"error": "not_found", "details": "Job not held by this worker"}, status=404)


class ClaimView(WorkerAPIView):
    @extend_schema(summary="Claim one queued render job")
    def post(self, request):
        claimed = renders.claim(request.auth)
        return Response(claimed) if claimed else Response(status=204)


class HeartbeatView(WorkerAPIView):
    @extend_schema(summary="Report progress on a held job")
    def post(self, request, job_id):
        data = request.data if isinstance(request.data, dict) else {}
        try:
            progress = int(data.get("progress") or 0)
        except (TypeError, ValueError):
            return Response({"error": "invalid", "details": "progress must be 0..100"}, status=400)
        job = renders.heartbeat(request.auth, job_id, progress)
        return Response({"status": job.status, "cancel": False}) if job else _gone()


class CompleteView(WorkerAPIView):
    @extend_schema(summary="Report a finished render (validated before it counts)")
    def post(self, request, job_id):
        data = request.data if isinstance(request.data, dict) else {}
        job, error = renders.complete(request.auth, job_id, data)
        if job is None:
            return _gone()
        if error == "invalid":
            return Response({"error": "invalid", "details": "width, height, duration_seconds are required"}, status=400)
        return Response({"status": job.status, "error": job.error}, status=200 if not error else 422)


class FailView(WorkerAPIView):
    @extend_schema(summary="Report a failed render")
    def post(self, request, job_id):
        data = request.data if isinstance(request.data, dict) else {}
        job = renders.fail(request.auth, job_id, data.get("error"))
        return Response({"status": job.status}) if job else _gone()
