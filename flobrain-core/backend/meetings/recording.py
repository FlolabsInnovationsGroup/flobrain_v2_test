"""Recording a FloBrain call, one track per speaker (2026-10-21).

Starting posts the notice (caller), then records every microphone already published; the
``track_published`` webhook adds anyone who starts speaking later. Stopping stops them all.
``Meeting.recording_egress_id`` is ``tracks`` while recording, ``starting`` while starting.
"""

from django.db import IntegrityError
from django.utils import timezone

from meetings import livekit
from meetings.models import Meeting, TrackEgress

TRACKS = "tracks"


def record_track(meeting, identity: str, name: str, track_sid: str):
    if TrackEgress.objects.filter(meeting=meeting, track_sid=track_sid).exists():
        return None
    egress_id = livekit.start_track_recording(meeting, identity, track_sid)
    try:
        return TrackEgress.objects.create(meeting=meeting, egress_id=egress_id, track_sid=track_sid, participant_identity=identity, participant_name=name)
    except IntegrityError:  # the webhook and the start raced for the same track
        livekit.stop_recording(egress_id)
        return None


def start(meeting) -> int:
    started = 0
    for track in livekit.audio_tracks(meeting):
        if record_track(meeting, track["identity"], track["name"], track["track_sid"]):
            started += 1
    Meeting.objects.filter(pk=meeting.pk).update(recording_egress_id=TRACKS, recording_started_at=timezone.now())
    return started


def stop(meeting) -> None:
    for te in TrackEgress.objects.filter(meeting=meeting, stopped_at__isnull=True):
        try:
            livekit.stop_recording(te.egress_id)
        except livekit.LiveKitError as exc:
            if not exc.gone:
                raise
        TrackEgress.objects.filter(pk=te.pk).update(stopped_at=timezone.now())
