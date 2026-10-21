import uuid

from django.db import models
from django.utils import timezone


class Meeting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="meetings")
    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="meetings")
    title = models.CharField(max_length=200)
    provider = models.CharField(max_length=32, default="local")
    join_url = models.URLField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    # Calls inside FloBrain (LiveKit). Recording needs meeting.manage and posts a notice first.
    recording_egress_id = models.CharField(max_length=64, blank=True, default="")
    recording_started_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    recording_started_at = models.DateTimeField(null=True, blank=True)
    auto_summarize = models.BooleanField(default=True)

    class Meta:
        db_table = "meetings"


class Recording(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="recordings")
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="recordings")
    play_url = models.URLField(blank=True, default="")
    recorded_at = models.DateTimeField(default=timezone.now)
    SOURCES = ("upload", "livekit", "bot")
    source = models.CharField(max_length=8, default="upload")
    storage_key = models.CharField(max_length=300, blank=True, default="")
    content_type = models.CharField(max_length=60, blank=True, default="audio/ogg")
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    transcript_status = models.CharField(max_length=12, default="none")  # none|queued|running|done|failed
    transcript_error = models.CharField(max_length=80, blank=True, default="")
    transcript_updated_at = models.DateTimeField(null=True, blank=True)
    # Calls inside FloBrain record each speaker's audio track on its own (track egress), so the
    # transcript knows who said what without guessing. Mixed recordings (bot, uploads) have no speaker.
    egress_id = models.CharField(max_length=64, blank=True, default="")
    speaker = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    speaker_name = models.CharField(max_length=150, blank=True, default="")
    offset_seconds = models.FloatField(default=0)  # when this track started, from the start of recording

    class Meta:
        db_table = "recordings"
        ordering = ["-recorded_at"]


class TrackEgress(models.Model):
    """One participant's audio track being recorded during a FloBrain call."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="track_egresses")
    egress_id = models.CharField(max_length=64, unique=True)
    track_sid = models.CharField(max_length=64)
    participant_identity = models.CharField(max_length=64)
    participant_name = models.CharField(max_length=150, blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    stopped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "meeting_track_egresses"
        constraints = [models.UniqueConstraint(fields=["meeting", "track_sid"], name="unique_track_egress")]


class Transcript(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recording = models.OneToOneField(Recording, on_delete=models.CASCADE, related_name="transcript")
    text = models.TextField(blank=True, default="")
    segments = models.JSONField(default=list, blank=True)
    language = models.CharField(max_length=8, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "transcripts"


class MeetingSummary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.OneToOneField(Meeting, on_delete=models.CASCADE, related_name="summary")
    text = models.TextField(blank=True, default="")
    decisions = models.JSONField(default=list, blank=True)
    action_items = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "meeting_summaries"


class MeetingBotSession(models.Model):
    """The meeting bot in one meeting (Phase 15). It announces itself, records only with the
    host's consent, and posts a recording notice to the room before anything is recorded."""

    PLATFORMS = ("zoom", "meet", "teams")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="bot_sessions")
    platform = models.CharField(max_length=8)
    meeting_url = models.URLField(max_length=500)
    status = models.CharField(max_length=24, default="requested")  # requested|joining|waiting_admission|in_call|uploading|done|failed|cancelled|expired
    vendor_bot_id = models.CharField(max_length=128, blank=True, default="")
    consent_confirmed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    recording_notice_sent_at = models.DateTimeField(null=True, blank=True)
    proactive_answers = models.BooleanField(default=False)
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    # Our own bot service (decided 2026-10-21: no outside vendor). It claims a session, joins as a
    # named guest, announces itself, records audio and uploads it here.
    worker = models.ForeignKey("workers.WorkerToken", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=120, blank=True, default="")
    recording = models.ForeignKey(Recording, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "meeting_bot_sessions"
