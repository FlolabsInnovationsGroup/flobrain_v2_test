"""Meetings demo data: a past meeting with a transcript by speaker, a meeting going on now that
anyone in the room can join, and an outside client call the assistant already attended."""

from datetime import timedelta

SYNC = [
    ("admin", 2, "Quick sync on the launch. This is demo text."),
    ("lead", 7, "Android login timeout is the last blocker. I expect a fix by Thursday."),
    ("designer", 15, "Store screenshots are done in English and Arabic."),
    ("admin", 22, "Then we launch at the end of next month. Sara owns the store screenshots."),
    ("lead", 30, "Someone needs to order an Android test device."),
    ("admin", 36, "I'll order it today, and I'll draft the blog post this week."),
]
CLIENT = [
    ("Client", 3, "We'd like the pilot to start with two teams in November."),
    ("Account lead", 11, "That works. We'll send the onboarding plan by Thursday."),
    ("Client", 19, "Please include the pricing for fifty seats."),
]


def seed(org, users, now):
    from meetings.models import Meeting, MeetingBotSession, MeetingSummary, Recording, Transcript
    from rooms.models import Room

    sync = Meeting.objects.filter(org=org, title="Weekly launch sync").first()
    if sync and not sync.recordings.exists():
        start = sync.started_at or now
        for key in ("admin", "lead", "designer"):
            user = users[key]
            rows = [{"start": float(t), "end": float(t) + 5, "text": text} for who, t, text in SYNC if who == key]
            rec = Recording.objects.create(
                org=org, meeting=sync, source="livekit", storage_key=f"demo/{sync.id}/speaker-{key}.ogg", content_type="audio/ogg",
                duration_seconds=41, transcript_status="done", speaker=user, speaker_name=user.username, recorded_at=start,
            )
            Transcript.objects.create(recording=rec, text=" ".join(r["text"] for r in rows), segments=rows, language="en")

    room = sync.room if sync else Room.objects.filter(org=org).exclude(kind=Room.KIND_DIRECT).first()
    if room is None:
        return
    Meeting.objects.create(org=org, room=room, title="Launch standup (live now)", created_by=users["lead"], started_at=now - timedelta(minutes=5))

    client = Meeting.objects.create(
        org=org, room=room, title="Pilot call with Acme (example)", created_by=users["admin"],
        started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=2, minutes=35),
    )
    rec = Recording.objects.create(
        org=org, meeting=client, source="bot", storage_key=f"demo/{client.id}/bot-seed.ogg", content_type="audio/ogg",
        duration_seconds=24, transcript_status="done", recorded_at=client.started_at,
    )
    rows = [{"start": float(t), "end": float(t) + 6, "text": f"{who}: {text}"} for who, t, text in CLIENT]
    Transcript.objects.create(recording=rec, text=" ".join(r["text"] for r in rows), segments=rows, language="en")
    MeetingBotSession.objects.create(
        org=org, meeting=client, platform="zoom", meeting_url="https://example.zoom.us/j/1234567890", status="done",
        consent_confirmed_by=users["admin"], recording_notice_sent_at=client.started_at, joined_at=client.started_at,
        left_at=client.ended_at, recording=rec, created_at=client.started_at - timedelta(minutes=1),
    )
    MeetingSummary.objects.create(
        meeting=client,
        text="Demo summary: the client wants a two-team pilot in November and pricing for fifty seats.",
        decisions=["Pilot starts in November with two teams"],
        action_items=[{"id": "c1", "text": "Send the onboarding plan by Thursday", "owner": "Omar"}, {"id": "c2", "text": "Prepare pricing for 50 seats", "owner": "Nadia"}],
    )
