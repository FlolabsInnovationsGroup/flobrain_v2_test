"""The buddy-turn hook (``buddies.chat.run_buddy_turn``), in three small calls.

- ``before_turn``: memory commands answered without a model; returns the turn's (status, body)
  or None.
- ``context``: the quoted "What you know about this person" block for the system prompt.
- ``after_turn``: proposes facts from the person's message and returns text to add to the reply
  (the "Should I remember this?" question), or "".

Memory must never break a buddy turn: every error is logged (no text) and ignored.
Only the ``buddy`` surface takes part in commands and capture (not scheduled agents), and a turn
on the person's own AI key (BYOK) never sends their message to the platform model for capture.
"""

import logging

logger = logging.getLogger(__name__)


def _usage():
    return {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "model": "", "token_state": "measured"}


def before_turn(user, org, chat, text, data=None, surface="buddy"):
    if surface != "buddy":
        return None
    try:
        from buddy_memory.commands import handle

        reply = handle(user, org, chat, getattr(chat, "buddy", None), text)
        if reply is None:
            return None
        from brain.models import Message

        Message.objects.create(chat=chat, role=Message.ROLE_USER, text=text)
        Message.objects.create(chat=chat, role=Message.ROLE_ASSISTANT, text=reply)
        return 200, {
            "usage": _usage(),
            "citations": [],
            "sources_state": "none",
            "proposals": [],
            "proposal_errors": [],
            "external_calls": [],
            "memory": {"command": True},
        }
    except Exception:  # noqa: BLE001 - memory never breaks a turn
        logger.exception("buddy memory command failed")
        return None


def context(user, org, buddy, text) -> str:
    try:
        from buddy_memory.services import context_block

        return context_block(user, org, buddy, text)
    except Exception:  # noqa: BLE001
        logger.exception("buddy memory context failed")
        return ""


def after_turn(user, org, chat, text, data=None, surface="buddy") -> str:
    if surface != "buddy" or (data or {}).get("credential_id"):
        return ""
    try:
        from brain.models import Message
        from buddy_memory import capture

        message = chat.messages.filter(role=Message.ROLE_USER).order_by("-created_at", "-id").first()
        items = capture.propose(user, org, chat, getattr(chat, "buddy", None), text, message=message)
        return capture.reply_note(items)
    except Exception:  # noqa: BLE001
        logger.exception("buddy memory capture failed")
        return ""
