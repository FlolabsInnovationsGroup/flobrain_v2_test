"""Bundled sample media for the demo (``DEMO_MODE`` only).

The files live in ``content_studio/static/demo/`` and are committed (each under 300 KB).
``manage.py build_studio_demo_media`` rebuilds them with FFmpeg (and its built-in flite
voice), so the spoken recording and its word timings always match. Every file says on
screen or in speech that it is demo media.
"""

import json
import os
import shutil
import subprocess
import tempfile

HERE = os.path.join(os.path.dirname(__file__), "static", "demo")

# Sample render outputs, one per aspect: preset → (file, width, height).
RENDERS = {
    "9x16_1080": ("render-9x16.mp4", 1080, 1920),
    "1x1_1080": ("render-1x1.mp4", 1080, 1080),
    "16x9_1080": ("render-16x9.mp4", 1920, 1080),
}
SOURCE = "source-recording.mp4"
SOURCE_WORDS = "source-recording.words.json"
VOICEOVER = "voiceover.m4a"
MANIFEST = "manifest.json"

# What the sample recording says. A number is a pause in seconds (auto-edit can cut it).
SCRIPT = [
    "This is a demo recording for FloBrain Content Studio.",
    "Welcome to the Nile Labs launch update.",
    "So, um, the mobile app passed store review last night.",
    1.4,
    "The Android login timeout is fixed, and the crash rate is down by half.",
    "Uh, we also finished the Arabic screens.",
    1.6,
    "Here is the big news. We launch at the end of next month, in English and Arabic.",
    "Like, every screen was tested with real users in Cairo.",
    1.2,
    "If you want early access, sign up on our website today.",
    "Thanks for watching, and see you at launch.",
]
VOICEOVER_TEXT = "This is a demo voiceover from FloBrain. A real voice is used once a text to speech provider is set up."
PHRASE_GAP = 0.25


def path(name):
    return os.path.join(HERE, name)


def manifest() -> dict:
    """Durations and sizes of the bundled files (written by the builder)."""
    try:
        with open(path(MANIFEST), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def source_words() -> list[dict]:
    try:
        with open(path(SOURCE_WORDS), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


# --- builder (needs ffmpeg/ffprobe; never runs in a request) ------------------------------


def _run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _duration(ffprobe, file):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", file],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def _speak(ffmpeg, text, out, tmp):
    textfile = os.path.join(tmp, "say.txt")
    with open(textfile, "w", encoding="utf-8") as fh:
        fh.write(text)
    _run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"flite=textfile={textfile}:voice=slt", "-ar", "16000", "-ac", "1", out])


def _silence(ffmpeg, seconds, out):
    _run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", f"{seconds:.3f}", out])


def _card(ffmpeg, out, width, height, seconds, lines, tmp, audio=None, clock=False):
    """A still title card (with an optional running clock) encoded small with x264."""
    textfile = os.path.join(tmp, f"card-{width}x{height}.txt")
    with open(textfile, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    size = max(24, min(width, height) // 14)
    filters = (
        f"drawtext=textfile={textfile}:font=Inter:fontcolor=white:fontsize={size}:line_spacing={size // 3}"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
    )
    if clock:
        filters += f",drawtext=text='%{{pts\\:hms}}':font=Inter:fontcolor=0xF2B134:fontsize={size // 2}:x=w-text_w-{size}:y=h-text_h-{size}"
    args = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0E7C66:s={width}x{height}:r=10:d={seconds:.3f}"]
    if audio:
        args += ["-i", audio]
    args += ["-vf", filters, "-c:v", "libx264", "-preset", "veryslow", "-crf", "34", "-tune", "stillimage", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-b:a", "24k", "-ac", "1", "-shortest"]
    else:
        args += ["-an"]
    args += ["-movflags", "+faststart", out]
    _run(args)


def build(ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe") -> dict:
    os.makedirs(HERE, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="studio-demo-")
    try:
        # 1. The spoken recording, phrase by phrase, so every word gets a timing.
        pieces, words, t = [], [], 0.0
        for n, item in enumerate(SCRIPT):
            piece = os.path.join(tmp, f"p{n}.wav")
            if isinstance(item, (int, float)):
                _silence(ffmpeg, float(item), piece)
                pieces.append(piece)
                t += float(item)
                continue
            _speak(ffmpeg, item, piece, tmp)
            length = _duration(ffprobe, piece)
            tokens = item.split()
            letters = sum(len(w) for w in tokens) or 1
            # flite leaves ~0.1 s of air at both ends; spread the words over the rest by length.
            start, span = t + 0.1, max(length - 0.2, 0.1)
            for w in tokens:
                share = span * len(w) / letters
                words.append({"w": w, "start": round(start, 3), "end": round(start + share * 0.92, 3), "speaker": "S1"})
                start += share
            pieces.append(piece)
            t += length
            gap = os.path.join(tmp, f"g{n}.wav")
            _silence(ffmpeg, PHRASE_GAP, gap)
            pieces.append(gap)
            t += PHRASE_GAP
        listing = os.path.join(tmp, "list.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.writelines(f"file '{p}'\n" for p in pieces)
        speech = os.path.join(tmp, "speech.wav")
        _run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", speech])
        total = _duration(ffprobe, speech)
        _card(
            ffmpeg, path(SOURCE), 1280, 720, total,
            ["Nile Labs launch update", "Demo recording (sample media)"], tmp, audio=speech, clock=True,
        )
        with open(path(SOURCE_WORDS), "w", encoding="utf-8") as fh:
            json.dump(words, fh, ensure_ascii=False, indent=1)

        # 2. One sample render per aspect.
        renders = {}
        for preset, (name, width, height) in RENDERS.items():
            label = preset.split("_")[0].replace("x", ":")
            _card(ffmpeg, path(name), width, height, 4.0, ["FloBrain demo render", f"{label} sample output"], tmp)
            renders[preset] = {"file": name, "width": width, "height": height, "duration_seconds": round(_duration(ffprobe, path(name)), 3)}

        # 3. The demo voiceover.
        spoken = os.path.join(tmp, "vo.wav")
        _speak(ffmpeg, VOICEOVER_TEXT, spoken, tmp)
        _run([ffmpeg, "-y", "-v", "error", "-i", spoken, "-c:a", "aac", "-b:a", "32k", "-ac", "1", "-movflags", "+faststart", path(VOICEOVER)])

        data = {
            "source": {"file": SOURCE, "width": 1280, "height": 720, "duration_seconds": round(_duration(ffprobe, path(SOURCE)), 3)},
            "renders": renders,
            "voiceover": {"file": VOICEOVER, "duration_seconds": round(_duration(ffprobe, path(VOICEOVER)), 3)},
        }
        with open(path(MANIFEST), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        return data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
