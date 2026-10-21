import tempfile
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from content_studio import storage
from jobs.queue import enqueue, register
from privacy.models import DataExportJob, RetentionPolicy
from privacy.services import apply_retention, build_export

EXPORT_JOB = "privacy.export"
RETENTION_JOB = "privacy.retention"


@register(EXPORT_JOB)
def run_export(payload):
    claimed = DataExportJob.objects.filter(pk=payload.get("export_id"), status="queued").update(status="running")
    if not claimed:
        return
    job = DataExportJob.objects.select_related("user").get(pk=payload["export_id"])
    key = f"privacy/{job.user_id}/{job.id}/my-data.zip"
    try:
        data, _counts = build_export(job.user)
        with tempfile.SpooledTemporaryFile(max_size=64 << 20) as tmp:
            tmp.write(data)
            tmp.seek(0)
            if not storage.put_file(key, tmp, "application/zip"):
                raise RuntimeError("storage_not_configured")
    except Exception as exc:  # noqa: BLE001 - only the failure class is recorded
        DataExportJob.objects.filter(pk=job.pk).update(status="failed", error=type(exc).__name__[:200], finished_at=timezone.now())
        return
    days = int(getattr(settings, "EXPORT_RETENTION_DAYS", 7))
    DataExportJob.objects.filter(pk=job.pk).update(
        status="succeeded", storage_key=key, size_bytes=len(data), finished_at=timezone.now(), expires_at=timezone.now() + timedelta(days=days)
    )


@register(RETENTION_JOB)
def run_retention(payload):
    qs = RetentionPolicy.objects.select_related("org").filter(org__is_active=True)
    if payload.get("org_id"):
        qs = qs.filter(org_id=payload["org_id"])
    return {str(p.org_id): apply_retention(p) for p in qs}


def request_export(job):
    return enqueue(EXPORT_JOB, {"export_id": str(job.id)})
