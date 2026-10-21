"""Voice notes that arrive on WhatsApp or Telegram.

The media reference (provider media id / file id) is stored on the inbound event or customer
message. When the org has ``voice_notes`` on, the audio is downloaded from the provider (allowlisted
hosts, 10 MB cap) and transcribed with ``rooms.voice.transcribe_bytes`` on the org's own Whisper
server. Nothing is stored. Demo connections are never downloaded; the caller then asks the person to
type, or hands the customer to a person.
"""

import logging

logger = logging.getLogger(__name__)


def _voice_on(org) -> bool:
    from organizations.flags import effective_flag

    return bool(effective_flag(org, None, "voice_notes", default=False))


def transcribe_inbound(connection, media: dict, language_hint: str = "") -> str | None:
    """Return the transcript of an inbound voice note, or None when it cannot be transcribed.

    ``media`` is ``{"type": "voice", "ref": <provider media id>, "mime": <type>}``.
    """
    from channels import providers

    if not isinstance(media, dict) or not media.get("ref"):
        return None
    if providers.simulated(connection) or not _voice_on(connection.org):
        return None
    try:
        data = providers.download_media(connection, str(media["ref"]))
    except providers.ProviderError as exc:
        logger.info("channels: voice download refused (%s)", exc.code)
        return None
    from rooms import voice as room_voice

    try:
        text, _language = room_voice.transcribe_bytes(connection.org, data, media.get("mime"), language_hint)
    except room_voice.VoiceError as exc:
        logger.info("channels: voice transcription failed (%s)", getattr(exc, "code", "error"))
        return None
    return text or None
