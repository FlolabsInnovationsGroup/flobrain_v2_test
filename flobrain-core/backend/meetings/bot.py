"""Meeting bot (Phase 15; Q23 decided 2026-10-21: our own bot, no outside vendor).

Rules from the spec and Decision 37:
- Only someone with ``meeting.manage`` in the room invites it, and they confirm the host's consent.
- A recording notice goes to the room (and the bot announces itself in the meeting) before recording.
- Proactive answers are off by default and refused whenever a participant is not an org member.
``MEETING_BOT_VENDOR=self_hosted`` turns it on: the ``meeting-bot`` service (repo root) claims sessions
with a ``meeting_bot`` worker token, joins as a named guest, says that it records, and uploads the
audio, which then goes through the same Whisper transcription and summary as calls inside FloBrain.
"""

import re

from django.conf import settings

URLS = {
    "zoom": re.compile(r"^https://([a-z0-9-]+\.)?zoom\.us/j/\d{9,12}(\?pwd=[A-Za-z0-9._-]{1,64})?$"),
    "meet": re.compile(r"^https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}$"),
    "teams": re.compile(r"^https://teams\.microsoft\.com/l/meetup-join/[A-Za-z0-9%._\-/~?=&]{10,400}$"),
}

NOTICE = "Recording notice: the FloBrain meeting assistant is joining “{title}” to record and summarize it. It will say so when it joins."


BOT_NAME = "FloBrain assistant"
ANNOUNCE = "Hi, I'm the FloBrain assistant. I'm recording this meeting to transcribe and summarize it for the team. Ask the host to remove me if you don't agree."
STALE_MINUTES = 3

VENDORS: dict = {"self_hosted": "our meeting-bot service"}


def configured() -> bool:
    vendor = getattr(settings, "MEETING_BOT_VENDOR", "")
    if not vendor:
        from meetings import demo

        return demo.bot()  # the demo assistant walks through the steps by itself
    if vendor == "self_hosted":
        return True  # no outside key: our own bot service claims the sessions
    return bool(getattr(settings, "MEETING_BOT_API_KEY", "")) and vendor in VENDORS


def valid_url(platform: str, url: str) -> bool:
    pattern = URLS.get(platform)
    return bool(pattern and pattern.match(url or ""))


def proactive_allowed(participant_emails, org) -> bool:
    """Proactive answers only when every participant is an active member of the org."""
    from organizations.models import OrgMembership

    emails = {e.strip().lower() for e in participant_emails if e}
    if not emails:
        return False
    members = set(
        OrgMembership.objects.filter(org=org, employment_status="active", user__email__in=list(emails)).values_list("user__email", flat=True)
    )
    return {m.lower() for m in members} == emails
