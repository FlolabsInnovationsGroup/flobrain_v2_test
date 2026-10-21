from content_studio import transcribe  # noqa: F401 - registers content.transcribe
from content_studio.publishing import publish
from jobs.queue import register


@register("content.publish")
def publish_job(payload):
    job = publish(payload["job_id"])
    return {"ok": True, "status": job.status if job else "skipped"}
