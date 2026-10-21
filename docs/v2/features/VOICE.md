# Voice notes (W7)

People can send voice notes in rooms and speak to a buddy instead of typing. Audio is transcribed on the org's own Whisper server, with hints for Egyptian and Gulf Arabic. Readers see the transcript in their own language.

## What it does

- **Rooms.** A mic button next to Send. Hold to record and release to send, or tap (Enter/Space) to start and tap again to send. Escape, Cancel or sliding off the button throws the recording away. A timer shows the length, and recording stops by itself at 5 minutes. The message shows a player (play/pause, scrubber, length), the transcript (can be hidden), and when the note was spoken in another language, "Translated from Egyptian Arabic" with "Show original".
- **Buddy chat.** The same mic button turns speech into text and puts it in the composer. The person checks the text before sending. Nothing is stored.
- **Channels hook.** `rooms.voice.transcribe_bytes` lets the channels app transcribe inbound WhatsApp and Telegram voice notes.

## Flag and permissions

- Flag `voice_notes` (off by default; on in the demo). Checked with `effective_flag` on every endpoint. When it is off, endpoints answer `501 not_implemented` (like other V2 flags) and the UI hides the mic and player.
- Room endpoints need `chat.use` and room access (`user_can_access_room` + `room.view`), the same rules as text messages. Owners and admins can read team and project rooms they are not in, so they can also play those notes. Direct and group rooms stay private to their members.
- Buddy voice input needs `ai.use`.
- Support (impersonation) sessions cannot upload, translate or play audio.

## Endpoints

All under `/api/v2`.

| Method | Path | What |
|---|---|---|
| POST | `orgs/{org}/rooms/{room}/voice` | Multipart `file`, optional `duration` (seconds, from the recorder) and `language` (hint such as `ar-EG`). Creates a `RoomMessage(kind="voice")` and a `VoiceNote` (status `pending`). 201 with the note. |
| GET | `orgs/{org}/rooms/{room}/voice[?translate_to=xx]` | The room's voice notes (latest 200). With `translate_to`, done notes in another language get `translation`. `translation_note` explains when nothing could be translated (`not_configured`, `private_only`, `deferred`). |
| GET | `orgs/{org}/rooms/{room}/voice/{id}/audio` | The audio bytes, for people who can read the room. `Cache-Control: private, no-store`, `nosniff`. No public or presigned URL is ever returned. |
| POST | `orgs/{org}/rooms/{room}/voice/{id}/retry` | The author queues a failed transcript again. |
| POST | `orgs/{org}/buddies/voice-input` | Multipart `file` (+ optional `duration`, `language`). Returns `{text, language, demo, duration}`. The clip lives in a temp file only while it is transcribed and is deleted even on failure. |

Validation errors are `400 {"error": "invalid", "code": ..., "details": ...}` with codes `empty`, `too_large`, `unsupported_type`, `type_mismatch`, `too_long`, `bad_duration`, `bad_language`.

## Models

- `RoomMessage.kind`: `text` (default) or `voice`. New field, default keeps old rows as text.
- `VoiceNote` (table `room_voice_notes`): one per voice message. `storage_key`, `content_type`, `size_bytes`, `duration_seconds`, `language_hint`, `language` (detected: `ar-EG`, `ar-SA`, `ar-AE`, `ar`, `en`...), `transcript` (raw Whisper text), `status` (`pending`/`done`/`failed`), `error`, `is_demo`.
- The message `body` holds the transcript once it is ready (empty while pending). Authors can correct it with the normal message edit. Search and room translation work on it.
- Translations are cached per language in the existing `MessageTranslation` table, tied to the message version, so an edited transcript is translated again.
- Migration: `rooms/0003_voice_notes`.

## Transcription

1. Upload checks: at most 10 MB, a declared type we accept (`audio/webm`, `audio/ogg`, `audio/mp4`, `audio/x-m4a`, `audio/mpeg`...), magic bytes that match it (WebM DocType, `OggS`, `ftyp` brand, MP3 frame or ID3), and at most 5 minutes. The length is read from the container (WebM Duration or block times, Ogg granule, MP4 `mvhd`/`mehd`/last `tfdt`, MP3 Xing/VBRI or bitrate); the recorder's own `duration` is used only when the container does not say. Whisper's reported length is checked again after transcription.
2. Audio goes to private storage (`content_studio.storage`: S3 bucket or local folder) under `voice/{org}/{room}/{note}.{ext}`.
3. A job (`rooms.voice_transcribe`) sends it to Whisper through `meetings.voice_asr`, which uses the same settings as meetings (`ASR_BACKEND`, `ASR_BASE_URL`, `ASR_MODEL`, `ASR_API_KEY`) and only calls the configured URL. Without a jobs worker (and outside eager mode) the job runs right after the request commits.
4. Dialect hints: `ar-EG` sends `language=ar` and an Egyptian colloquial `prompt`; Gulf codes (`ar-SA`, `ar-AE`, `ar-KW`, `ar-QA`, `ar-BH`, `ar-OM`) send `language=ar` and a Gulf prompt. The hint comes from the upload, else the org setting `voice_language_hint`, else the person's locale if it is an Arabic dialect. Without a hint Whisper detects the language; for Arabic the dialect is guessed from words only one dialect uses (falls back to `ar`).
5. The transcript becomes the message body. Readers' clients poll (rooms have no realtime push yet: `/realtime/ticket` answers "use polling"), so nothing is broadcast.
6. Translation runs when a reader lists voice notes with `translate_to`, through `rooms.translation.translate_page` (direct provider only, AI policy and budget, usage events, one call per message). It is skipped for private-only orgs without a self-hosted model, and limited by the AI send throttle.

Deleting a voice message deletes its audio from storage.

## Channels hook

```python
from rooms.voice import transcribe_bytes, VoiceError

text, language = transcribe_bytes(org, data, mime, hint="")
```

- `org`: the `Organization`. Its `settings["voice_language_hint"]` is the default hint.
- `data`: raw audio bytes (Ogg/Opus from WhatsApp and Telegram, WebM, M4A or MP3), up to 10 MB and 5 minutes.
- `mime`: the sender's declared type, may be empty or unknown (the magic bytes decide); a known type must match them.
- `hint` (optional): `ar-EG`, `ar-SA`, `en`...
- Returns `(text, language)`, language as above. Synchronous; nothing is stored.
- Raises `VoiceError` with `.code`: `empty`, `too_large`, `unsupported_type`, `type_mismatch`, `too_long`, `not_configured`, `unavailable`, `http_<status>`, `bad_response`, `no_speech`.
- It does not check flags. The caller decides whether the org may use it.

## Security notes

- Magic bytes must match the declared type; the stored and served type is the one we detected, served with `nosniff`.
- Storage keys are built by the server from ids. Audio is only streamed through the authenticated endpoint after the same room check as messages.
- Whisper is the org's own server; audio never goes to a third party. Translation sends only the transcript text, through the direct provider, under the AI policy.
- The audit log records `room.voice_note.create` with ids, seconds and bytes, never audio or text.
- Upload and voice input share the per-user AI send throttle.

## Demo

- `DEMO_MODE` without `ASR_BACKEND`: transcription answers with one of three labelled demo transcripts (Egyptian Arabic, Gulf Arabic, English), chosen from the hint or the person's locale. Notes are marked `demo` and the UI shows "Demo transcript".
- `demo/extras/97_voice.py` seeds three transcribed notes in the "Mobile app launch" room (Sara: Egyptian, Omar: Gulf, Youssef: English) with cached English and Arabic translations. Their audio is a generated speech-paced tone (WAV), not a real voice.
- `brain/llm/demo_handlers/voice.py` answers translations of the demo transcripts.

## Before production

- Run the Whisper server (`ASR_BACKEND=http`, `ASR_BASE_URL`, `ASR_MODEL`, e.g. faster-whisper large-v3) and a jobs worker (`JOBS_WORKER_ENABLED`). Optional `VOICE_ASR_TIMEOUT` (default 180 s) and `VOICE_TMP_DIR`.
- Configure content storage (`CONTENT_STORAGE=s3` with a private bucket).
- A direct AI provider for translations.
- Check Whisper quality on real Egyptian and Gulf recordings and tune the prompts.

## Known limits

- No realtime push: new notes and finished transcripts appear on the next poll.
- The dialect guess is a word list; plain `ar` is shown when it cannot tell.
- Fragmented MP4 from Safari has no total length in its header; the last fragment start (a lower bound) or the recorder's count is used, and Whisper's length is checked after.
- Audio is served whole (no range requests). Fine for 10 MB clips.
- Room translation of voice notes is on whenever the reader's language differs; it does not depend on the `live_translation` flag.
