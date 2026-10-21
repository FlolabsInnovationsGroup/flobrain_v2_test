from jobs.queue import register


@register("meetings.transcribe")
def transcribe_recording(payload):
    return {"ok": False, "reason": "not_implemented"}


@register("meetings.summarize")
def summarize_meeting(payload):
    return {"ok": False, "reason": "not_implemented"}
