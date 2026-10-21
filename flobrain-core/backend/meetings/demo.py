"""Meetings that work end to end in the demo (``DEMO_MODE`` only, never in production).

Without LiveKit, Whisper or the bot service, the demo still lets people join a call, record it,
get a transcript with speakers, a summary and action items, and invite the assistant to an
outside meeting. Everything produced here is labelled as demo content.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

DEMO_KEY_PREFIX = "demo/"

# What the demo "hears": (speaker slot, seconds from start, text). Slot 0 is whoever recorded.
SCRIPT = [
    (0, 1, "Thanks for joining. This is a demo recording, so everything you hear is sample text."),
    (1, 6, "The Android build passed review last night. The login timeout is the only blocker left."),
    (0, 14, "Can we fix it before Friday?"),
    (1, 18, "Yes. I'll take it and pair with Omar on the session refresh."),
    (2, 26, "Store screenshots are ready in English and Arabic. I'll upload them tomorrow."),
    (0, 34, "Good. Then we keep the launch at the end of next month."),
    (2, 40, "Agreed. Someone should draft the launch blog post."),
    (1, 45, "Omar can draft it this week."),
    (0, 50, "Great. Let's meet again next Monday."),
]
BOT_SCRIPT = [
    ("Client", 2, "This is a demo transcript from the FloBrain assistant in an outside meeting."),
    ("Client", 8, "We'd like the pilot to start with two teams in November."),
    ("Account lead", 15, "That works. We'll send the onboarding plan by Thursday."),
    ("Client", 22, "Please include the pricing for fifty seats."),
]


def enabled() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


def calls() -> bool:
    from meetings import livekit

    return enabled() and not livekit.configured()


def asr() -> bool:
    return enabled() and not (getattr(settings, "ASR_BACKEND", "") or "")


def bot() -> bool:
    return enabled() and not (getattr(settings, "MEETING_BOT_VENDOR", "") or "")


def participants(meeting, user):
    """The recorder first, then up to two other room members, as (user, name)."""
    from rooms.models import RoomMember

    people = [user]
    others = RoomMember.objects.filter(room=meeting.room).exclude(user=user).select_related("user")[:2]
    people += [m.user for m in others]
    if len(people) < 3 and meeting.room.team_id:
        from organizations.models import TeamMembership

        extra = TeamMembership.objects.filter(team_id=meeting.room.team_id).exclude(user__in=people).select_related("user")[: 3 - len(people)]
        people += [m.user for m in extra]
    return [(u, (u.username or u.email.split("@")[0])[:150]) for u in people]


def finish_recording(meeting, user):
    """Stopping a demo recording: one recording per speaker, then the normal pipeline."""
    from meetings import pipeline
    from meetings.models import Recording

    made = []
    for slot, (person, name) in enumerate(participants(meeting, user)):
        rec = Recording.objects.create(
            org_id=meeting.org_id, meeting=meeting, source="livekit", content_type="audio/ogg",
            storage_key=f"{DEMO_KEY_PREFIX}{meeting.id}/speaker-{slot}.ogg", speaker=person, speaker_name=name,
            offset_seconds=0.0, duration_seconds=55,
        )
        made.append(rec)
        pipeline.queue_transcription(rec)
    return made


def transcript_for(recording) -> dict:
    """Canned Whisper output for a demo recording."""
    key = recording.storage_key
    if "/bot-" in key:
        rows = [{"start": float(t), "end": float(t) + 5, "text": f"{who}: {text}"} for who, t, text in BOT_SCRIPT]
    else:
        try:
            slot = int(key.rsplit("speaker-", 1)[1].split(".")[0])
        except (IndexError, ValueError):
            slot = 0
        rows = [{"start": float(t), "end": float(t) + 4, "text": text} for s, t, text in SCRIPT if s == slot]
    return {"text": " ".join(r["text"] for r in rows), "segments": rows, "language": "en"}


BOT_STEPS = [(0, "requested"), (4, "joining"), (8, "waiting_admission"), (14, "in_call"), (40, "done")]


def advance_bot(session):
    """Move a demo assistant through its states as time passes (checked when the page asks)."""
    from meetings import pipeline
    from meetings.models import MeetingBotSession, Recording

    if session.status in ("done", "failed", "cancelled"):
        return session
    elapsed = (timezone.now() - session.created_at).total_seconds()
    status = session.status
    for after, step in BOT_STEPS:
        if elapsed >= after:
            status = step
    if status == session.status:
        return session
    fields = {"status": status, "heartbeat_at": timezone.now()}
    if status in ("in_call", "done") and not session.joined_at:
        fields["joined_at"] = session.created_at + timedelta(seconds=14)
    if status == "done":
        rec = Recording.objects.create(
            org_id=session.org_id, meeting=session.meeting, source="bot", content_type="audio/ogg",
            storage_key=f"{DEMO_KEY_PREFIX}{session.meeting_id}/bot-{session.id}.ogg", duration_seconds=26,
        )
        fields.update(recording=rec, left_at=timezone.now())
        pipeline.queue_transcription(rec)
    MeetingBotSession.objects.filter(pk=session.pk).update(**fields)
    session.refresh_from_db()
    return session
