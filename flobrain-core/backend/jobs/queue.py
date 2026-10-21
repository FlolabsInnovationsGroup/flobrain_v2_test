import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, callable] = {}


def register(name: str):
    def decorator(fn):
        _REGISTRY[name] = fn
        return fn

    return decorator


def jobs_eager() -> bool:
    if getattr(settings, "TESTING", False):
        return True
    flag = getattr(settings, "JOBS_EAGER", None)
    if flag is None:
        return bool(getattr(settings, "DEBUG", False))
    return bool(flag)


def worker_enabled() -> bool:
    """True once a `manage.py run_jobs` process is deployed (INFRA_CHANGES.md)."""
    return bool(getattr(settings, "JOBS_WORKER_ENABLED", False))


def enqueue(name: str, payload: dict | None = None):
    """E17: run inline when JOBS_EAGER; queue on PostgreSQL when a worker exists; else unavailable.

    Without a worker process nothing would ever run the row, so no row is
    created and the caller is told the feature is unavailable.
    """
    payload = payload or {}
    handler = _REGISTRY.get(name)
    if handler is None:
        raise KeyError(f"Unknown job: {name}")
    if jobs_eager():
        return handler(payload)
    if not worker_enabled():
        logger.warning("Job %s not queued: no worker process (JOBS_WORKER_ENABLED is off)", name)
        return {"ok": False, "reason": "unavailable"}
    from jobs.models import Job

    job = Job.objects.create(kind=name, payload=payload)
    return {"ok": True, "status": "queued", "job_id": str(job.id)}
