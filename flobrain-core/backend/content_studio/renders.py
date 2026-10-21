"""Render queue (Phase 9b): users queue jobs; GPU workers claim and report them.

The job's ``spec`` is frozen when queued and holds storage keys only. URLs are
minted when a worker claims the job: short-lived GETs for that job's inputs and
one PUT for that job's own output key. Workers never see user tokens, social
credentials or other jobs' files.
"""

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from content_studio import storage
from content_studio.models import RenderJob

CODECS = {"h264", "hevc", "av1"}


def month_renders(org) -> int:
    """Renders this month. A cancelled job counts once a worker started it (GPU time was spent)."""
    from django.db.models import Q

    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        RenderJob.objects.filter(org=org, queued_at__gte=start)
        .exclude(Q(status=RenderJob.STATUS_CANCELLED) & Q(started_at__isnull=True))
        .count()
    )


def changed_sources(project) -> list[str]:
    """Assets whose stored object no longer matches the ETag recorded at upload."""
    changed = []
    for asset in project.source_assets.all():
        meta = storage.head(asset.storage_key)
        if meta is None or (asset.source_etag and (meta.get("etag") or "") != asset.source_etag):
            changed.append(str(asset.id))
    return changed


def resolution_for(preset, template_spec):
    if preset in RenderJob.PRESETS:
        return list(RenderJob.PRESETS[preset])
    res = (template_spec or {}).get("resolution")
    return list(res) if res else None


def build_spec(project, preset, edl_version=None, operations=None, text_fields=None):
    template = project.template.spec if project.template_id else None
    kit = project.brand_kit
    sources = [
        {
            "asset": str(a.id),
            "kind": a.kind,
            "key": a.storage_key,
            "etag": a.source_etag,
            "duration_seconds": a.duration_seconds,
        }
        for a in project.source_assets.all().order_by("created_at")
    ]
    brand = None
    if kit is not None:
        from content_studio.models import MediaAsset

        logo_keys = list(MediaAsset.objects.filter(org=project.org, pk__in=kit.logos).values_list("storage_key", flat=True))
        brand = {
            "colors": kit.colors,
            "fonts": kit.fonts,
            "caption_style": kit.caption_style,
            "watermark": kit.watermark,
            "logo_keys": logo_keys,
            # Asset ids too, so consent is checked on everything that appears in the output.
            "asset_ids": [str(i) for i in kit.logos]
            + [str(i) for i in (kit.intro_asset_id, kit.outro_asset_id) if i],
            "intro_key": kit.intro_asset.storage_key if kit.intro_asset_id else None,
            "outro_key": kit.outro_asset.storage_key if kit.outro_asset_id else None,
        }
    return {
        "preset": preset,
        "resolution": resolution_for(preset, template),
        "sources": sources,
        "template": template,
        "brand": brand,
        "edl_version": edl_version,
        "operations": operations or [],
        "text_fields": text_fields or {},  # data for template text layers; workers pass it via textfile=
    }


def payload(job, with_url=False):
    data = {
        "id": str(job.id),
        "project": str(job.project_id),
        "preset": job.preset,
        "status": job.status,
        "progress": job.progress,
        "edl_version": job.edl_version,
        "error": job.error,
        "gpu_seconds": job.gpu_seconds,
        "queued_at": job.queued_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "demo": bool((job.output_meta or {}).get("demo")),
    }
    if with_url and job.status == RenderJob.STATUS_SUCCEEDED:
        data["output_url"] = storage.presign_get(job.output_key)
        data["output"] = job.output_meta
    return data


def _input_keys(spec):
    keys = [s["key"] for s in spec.get("sources", [])]
    brand = spec.get("brand") or {}
    keys += brand.get("logo_keys") or []
    keys += [k for k in (brand.get("intro_key"), brand.get("outro_key")) if k]
    return keys


def requeue_stale(now=None):
    now = now or timezone.now()
    stale = now - timedelta(seconds=int(getattr(settings, "RENDER_STALE_SECONDS", 600)))
    return RenderJob.objects.filter(status=RenderJob.STATUS_RUNNING, heartbeat_at__lt=stale).update(
        status=RenderJob.STATUS_QUEUED, worker=None, progress=0, started_at=None, heartbeat_at=None
    )


def claim(worker, org=None):
    """Give one queued job to ``worker`` with its input GETs and its output PUT, or None.
    ``org`` limits the claim to one org (the in-process demo worker)."""
    requeue_stale()
    with transaction.atomic():
        qs = RenderJob.objects.filter(status=RenderJob.STATUS_QUEUED).order_by("queued_at")
        if org is not None:
            qs = qs.filter(org=org)
        if connection.vendor == "postgresql":
            qs = qs.select_for_update(skip_locked=True)
        job = qs.first()
        if job is None:
            return None
        now = timezone.now()
        updated = RenderJob.objects.filter(pk=job.pk, status=RenderJob.STATUS_QUEUED).update(
            status=RenderJob.STATUS_RUNNING,
            worker=worker,
            started_at=now,
            heartbeat_at=now,
            output_key=f"content/{job.org_id}/renders/{job.id}/output.mp4",
        )
        if not updated:
            return None
    job.refresh_from_db()
    inputs = {key: storage.presign_get(key, expires=3600) for key in _input_keys(job.spec)}
    return {
        "job": str(job.id),
        "spec": job.spec,
        "inputs": inputs,
        "output": {"key": job.output_key, "url": storage.presign_put(job.output_key, "video/mp4", expires=3600), "method": "PUT"},
        "heartbeat_seconds": 30,
    }


def _held(worker, job_id):
    return RenderJob.objects.filter(pk=job_id, worker=worker, status=RenderJob.STATUS_RUNNING).first()


def heartbeat(worker, job_id, progress):
    job = _held(worker, job_id)
    if job is None:
        return None
    job.progress = max(0, min(100, int(progress)))
    job.heartbeat_at = timezone.now()
    job.save(update_fields=["progress", "heartbeat_at"])
    return job


def complete(worker, job_id, meta):
    """Validate the reported output before marking it succeeded. Returns (job, error)."""
    job = _held(worker, job_id)
    if job is None:
        return None, "not_found"
    try:
        width, height = int(meta.get("width")), int(meta.get("height"))
        duration = float(meta.get("duration_seconds"))
        gpu_seconds = float(meta.get("gpu_seconds") or 0)
    except (TypeError, ValueError):
        return job, "invalid"
    codec = str(meta.get("codec") or "").lower()
    error = ""
    expected = job.spec.get("resolution")
    if expected and [width, height] != list(expected):
        error = "wrong_resolution"
    elif codec not in CODECS:
        error = "wrong_codec"
    elif not 0 < duration <= float(getattr(settings, "CONTENT_MAX_SOURCE_SECONDS", 10800)):
        error = "wrong_duration"
    elif gpu_seconds < 0 or gpu_seconds > (timezone.now() - job.started_at).total_seconds() * 8 + 60:
        error = "wrong_gpu_seconds"  # at most 8 GPUs' worth of the wall time
    meta_out = None if error else storage.head(job.output_key)
    if not error and meta_out is None:
        error = "output_missing"
    job.finished_at = timezone.now()
    job.gpu_seconds = max(0.0, gpu_seconds) if not error else 0.0
    if error:
        job.status, job.error = RenderJob.STATUS_FAILED, error
    else:
        job.status, job.progress = RenderJob.STATUS_SUCCEEDED, 100
        # The ETag pins the exact bytes: approval and publish compare it (a later PUT is refused).
        job.output_meta = {
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "codec": codec,
            "etag": (meta_out or {}).get("etag") or "",
        }
    job.save()
    if not error:
        _notify_finished(job)
    return job, error


def _notify_finished(job):
    """Tell the person who queued it (bell, and push if they allow it)."""
    import logging

    try:
        from notifications.services import notify

        notify(
            job.org,
            [job.requested_by],
            "render_finished",
            {"render": str(job.id), "project": str(job.project_id), "title": job.project.title[:120]},
            link=f"studio/{job.project_id}",
            push=True,
        )
    except Exception:  # noqa: BLE001 - a notification problem never fails a render
        logging.getLogger(__name__).exception("render_finished notification failed")


def fail(worker, job_id, error):
    job = _held(worker, job_id)
    if job is None:
        return None
    job.status, job.error, job.finished_at = RenderJob.STATUS_FAILED, str(error or "worker_error")[:200], timezone.now()
    job.save(update_fields=["status", "error", "finished_at"])
    return job
