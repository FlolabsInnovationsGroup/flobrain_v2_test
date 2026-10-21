from automations.engine import JOB, process_run
from jobs.queue import register


@register(JOB)
def run_automation(payload):
    run = process_run(payload["run_id"])
    return {"ok": True, "status": run.status if run else "skipped"}
