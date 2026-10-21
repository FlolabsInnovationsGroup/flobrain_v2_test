from jobs.queue import register
from notifications.push import send_to_user


@register("notifications.push")
def push(payload):
    for user_id in payload.get("users", [])[:200]:
        send_to_user(user_id, str(payload.get("title", "")), str(payload.get("url", "")), str(payload.get("kind", "")))
