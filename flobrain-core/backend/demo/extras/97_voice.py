"""Voice notes in the demo (W7): three in the "Mobile app launch" room, already transcribed.

- Sara speaks Egyptian Arabic, Omar Gulf Arabic, Youssef English. Transcripts are the labelled
  demo transcripts from ``rooms.voice`` and each note is marked ``is_demo``.
- The audio is a generated, speech-paced tone (no real voice), so the player works offline.
- Translations into English (Arabic notes) and Arabic (English note) are cached, so the
  "Translated from Egyptian Arabic" label shows without any model call.
"""

import io
from datetime import timedelta


def seed(org, users, now):
    from content_studio import storage
    from rooms.models import MessageTranslation, Room, RoomMessage, VoiceNote
    from rooms.voice import DEMO_TRANSCRIPTS, demo_audio

    room = Room.objects.filter(org=org, kind=Room.KIND_PROJECT, name__icontains="launch").first()
    if room is None:
        return
    plan = [
        (users["designer"], "ar-EG", 55),
        (users["admin"], "ar-SA", 50),
        (users["member"], "en", 25),
    ]
    for i, (who, key, minutes_ago) in enumerate(plan):
        row = DEMO_TRANSCRIPTS[key]
        message = RoomMessage.objects.create(
            room=room, author=who, body=row["text"], kind=RoomMessage.KIND_VOICE, created_at=now - timedelta(minutes=minutes_ago)
        )
        note = VoiceNote.objects.create(
            org=org, message=message, content_type="audio/wav", duration_seconds=row["seconds"], language_hint=key,
            language=key, transcript=row["text"], status=VoiceNote.STATUS_DONE, is_demo=True,
            created_at=message.created_at,
        )
        audio = demo_audio(row["seconds"], seed=i)
        key_path = f"voice/{org.id}/{room.id}/{note.id}.wav"
        if storage.is_configured() and storage.put_file(key_path, io.BytesIO(audio), "audio/wav"):
            VoiceNote.objects.filter(pk=note.pk).update(storage_key=key_path, size_bytes=len(audio))
        for language, text in row["translations"].items():
            # Cached for this exact message version, like rooms.translation writes it.
            MessageTranslation.objects.create(
                message=message, language=language, text=f"{text} (demo translation)", created_at=message.updated_at
            )
