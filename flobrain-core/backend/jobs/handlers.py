from jobs.queue import register


@register("ping")
def ping(payload):
    return {"ok": True, "payload": payload}
