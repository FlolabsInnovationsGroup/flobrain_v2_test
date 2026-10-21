import tempfile
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from content_studio import storage
from exports.builder import build
from exports.models import MemoryExport
from jobs.queue import enqueue, register

JOB = "exports.memory"


@register(JOB)
def run(payload):
    claimed = MemoryExport.objects.filter(pk=payload.get("export_id"), status=MemoryExport.STATUS_QUEUED).update(
        status=MemoryExport.STATUS_RUNNING
    )
    if not claimed:
        return
    export = MemoryExport.objects.select_related("org").get(pk=payload["export_id"])
    key = f"exports/{export.org_id}/{export.id}/memory.zip"
    try:
        with tempfile.SpooledTemporaryFile(max_size=64 << 20) as tmp:
            counts = build(export.org, tmp)
            tmp.seek(0, 2)
            size = tmp.tell()
            if not storage.put_file(key, tmp, "application/zip"):
                raise RuntimeError("storage_not_configured")
    except Exception as exc:  # noqa: BLE001 - the export records the failure class only
        MemoryExport.objects.filter(pk=export.pk).update(
            status=MemoryExport.STATUS_FAILED, error=type(exc).__name__[:200], finished_at=timezone.now()
        )
        return
    days = int(getattr(settings, "EXPORT_RETENTION_DAYS", 7))
    MemoryExport.objects.filter(pk=export.pk).update(
        status=MemoryExport.STATUS_SUCCEEDED,
        storage_key=key,
        size_bytes=size,
        counts=counts,
        finished_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=days),
    )


def request(export):
    return enqueue(JOB, {"export_id": str(export.id)})
