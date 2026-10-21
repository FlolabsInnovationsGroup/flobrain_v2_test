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


def enqueue(name: str, payload: dict | None = None):
    """E17: run inline when JOBS_EAGER; otherwise report unavailable until Redis/Celery is approved."""
    payload = payload or {}
    handler = _REGISTRY.get(name)
    if handler is None:
        raise KeyError(f"Unknown job: {name}")
    if jobs_eager():
        return handler(payload)
    from jobs.models import Job

    Job.objects.create(kind=name, payload=payload)
    logger.warning("Job %s queued; worker process is not this request (JOBS_EAGER is off)", name)
    return {"ok": False, "reason": "unavailable"}
