from agents.service import RUN_JOB, execute_run
from jobs.queue import register


@register(RUN_JOB)
def run_agent(payload):
    run = execute_run(payload["run_id"])
    return {"ok": True, "status": run.status}
