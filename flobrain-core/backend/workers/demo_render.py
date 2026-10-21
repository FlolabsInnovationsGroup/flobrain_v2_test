"""In-process demo render worker (``DEMO_MODE`` only; never in production).

There is no GPU worker in a demo, so this stands in for one. It uses the same worker
code path as JarvisLabs workers (``renders.claim`` → ``heartbeat`` → ``complete``) with
its own ``WorkerToken``: it claims the org's queued jobs, reports progress for a few
seconds, then uploads the bundled sample MP4 for the job's aspect and reports believable
``gpu_seconds``. The output is marked ``demo`` and its picture says "FloBrain demo render".

It runs lazily: the render list and detail endpoints call ``tick(org)`` when demo mode is on.
"""

import io
import random

from django.conf import settings
from django.utils import timezone

from content_studio import demo_media, renders, storage
from content_studio.models import RenderJob
from workers.models import WorkerToken

WORKER_NAME = "Demo render worker (in-process)"
RUN_SECONDS = 6.0
MAX_CLAIMS_PER_TICK = 20


def enabled() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


def worker():
    row = WorkerToken.objects.filter(name=WORKER_NAME, kind="render", revoked_at__isnull=True).first()
    if row is None:
        row, _raw = WorkerToken.issue(WORKER_NAME, kind="render")  # the raw token is never needed in-process
    return row


def _sample(resolution):
    for preset, (name, width, height) in demo_media.RENDERS.items():
        if resolution and [width, height] == list(resolution):
            return preset, name, width, height
    return None


def _planned_seconds(job) -> float:
    """How long the real edit would be: kept source ranges, or the template's duration."""
    from content_studio.edl import kept_ranges
    from content_studio.models import MediaAsset

    spec = job.spec or {}
    if spec.get("template") and not spec.get("sources"):
        return float((spec.get("template") or {}).get("duration_seconds") or 3.0)
    total = 0.0
    ops = spec.get("operations") or []
    for source in spec.get("sources") or []:
        asset = MediaAsset.objects.filter(pk=source.get("asset")).first()
        if asset is not None and asset.duration_seconds:
            total += sum(b - a for a, b in kept_ranges(asset, ops))
    return total or 30.0


def _finish(token, job):
    sample = _sample((job.spec or {}).get("resolution"))
    if sample is None:
        res = "x".join(str(v) for v in (job.spec or {}).get("resolution") or []) or "custom"
        renders.fail(token, job.id, f"Demo worker has no sample output for {res}")
        return
    preset, name, width, height = sample
    try:
        with open(demo_media.path(name), "rb") as fh:
            data = fh.read()
    except OSError:
        renders.fail(token, job.id, "Demo sample media is missing (run build_studio_demo_media)")
        return
    storage.put_file(job.output_key, io.BytesIO(data), "video/mp4")
    rng = random.Random(str(job.id))
    planned = _planned_seconds(job)
    wall = (timezone.now() - job.started_at).total_seconds() if job.started_at else RUN_SECONDS
    gpu = round(min(planned * rng.uniform(0.45, 0.7) + rng.uniform(1.5, 4.0), wall * 8 + 50), 1)
    duration = (demo_media.manifest().get("renders") or {}).get(preset, {}).get("duration_seconds") or 4.0
    done, error = renders.complete(
        token, job.id, {"width": width, "height": height, "duration_seconds": duration, "codec": "h264", "gpu_seconds": gpu}
    )
    if done is not None and not error:
        meta = dict(done.output_meta or {})
        meta.update(demo=True, sample=name, planned_duration_seconds=round(planned, 2))
        RenderJob.objects.filter(pk=done.pk).update(output_meta=meta)


def tick(org, now=None) -> int:
    """Advance this org's demo renders. Returns how many jobs it touched."""
    if not enabled():
        return 0
    now = now or timezone.now()
    token = worker()
    touched = 0
    for _ in range(MAX_CLAIMS_PER_TICK):
        if renders.claim(token, org=org) is None:
            break
        touched += 1
    for job in RenderJob.objects.filter(org=org, worker=token, status=RenderJob.STATUS_RUNNING):
        elapsed = (now - job.started_at).total_seconds() if job.started_at else 0
        if elapsed >= RUN_SECONDS:
            _finish(token, job)
        else:
            renders.heartbeat(token, job.id, int(elapsed / RUN_SECONDS * 100))
        touched += 1
    return touched
