"""Text-to-speech provider interface (Q18: the vendor is still open, so no real vendor ships here).

``TTS_PROVIDER`` names the provider in ``REGISTRY``. A provider is offered only when
``configured()`` is true; otherwise voiceovers are "Not configured" (501). Adding a vendor
later is one class plus one registry line:

    class AcmeTTS(TTSProvider):
        name, label = "acme", "Acme Voice"
        def configured(self): return bool(settings.TTS_ACME_API_KEY)
        def voices(self): return [Voice("narrator", "Narrator", "en")]
        def synthesize(self, text, voice, language): ... return Speech(audio_bytes, "audio/mpeg", 12.3)

``demo`` (bundled sample audio) is used only in ``DEMO_MODE``, by default when no provider is
named. Cloning a real person's voice needs that person's recorded consent (Decision 37) and is
not offered by any provider here.
"""

from dataclasses import dataclass

from django.conf import settings

MAX_CHARS = 5000


class TTSError(Exception):
    def __init__(self, code, transient=False):
        super().__init__(code)
        self.code, self.transient = code, transient


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    language: str

    def as_dict(self):
        return {"id": self.id, "label": self.label, "language": self.language}


@dataclass(frozen=True)
class Speech:
    audio: bytes
    content_type: str
    duration_seconds: float


class TTSProvider:
    name = ""
    label = ""
    is_demo = False

    def configured(self) -> bool:
        return False

    def voices(self) -> list[Voice]:
        return []

    def synthesize(self, text: str, voice: str, language: str) -> Speech:
        raise TTSError("not_configured")

    def info(self) -> dict:
        return {
            "provider": self.name,
            "label": self.label,
            "demo": self.is_demo,
            "voices": [v.as_dict() for v in self.voices()],
            "max_chars": MAX_CHARS,
        }


class DemoTTS(TTSProvider):
    """Returns the bundled sample voiceover whatever the text (it says so in the audio)."""

    name = "demo"
    label = "Demo voice (sample audio)"
    is_demo = True

    def configured(self):
        return bool(getattr(settings, "DEMO_MODE", False))

    def voices(self):
        return [Voice("demo-narrator", "Demo narrator", "en")]

    def synthesize(self, text, voice, language):
        from content_studio import demo_media

        if not self.configured():
            raise TTSError("not_configured")
        try:
            with open(demo_media.path(demo_media.VOICEOVER), "rb") as fh:
                audio = fh.read()
        except OSError as exc:
            raise TTSError("demo_media_missing") from exc
        duration = (demo_media.manifest().get("voiceover") or {}).get("duration_seconds") or 6.5
        return Speech(audio, "audio/mp4", float(duration))


REGISTRY: dict[str, type[TTSProvider]] = {"demo": DemoTTS}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def get_tts():
    """The configured provider, or None ("Not configured")."""
    name = (getattr(settings, "TTS_PROVIDER", "") or "").strip()
    if not name and getattr(settings, "DEMO_MODE", False):
        name = "demo"
    cls = REGISTRY.get(name)
    if cls is None:
        return None
    provider = cls()
    return provider if provider.configured() else None
