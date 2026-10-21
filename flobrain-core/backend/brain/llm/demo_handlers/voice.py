"""Demo model answers for voice note translations (W7, ``DEMO_AI`` only).

Voice transcripts are translated with the rooms translation prompt. When the text is one of the
demo transcripts (``rooms.voice.DEMO_TRANSCRIPTS``: Egyptian Arabic, Gulf Arabic, English), this
returns its canned translation, marked as demo output. Anything else passes (returns None).
"""

import re

from brain.llm.demo_ai import _result

LANGUAGE = re.compile(r"ISO code '([a-zA-Z-]{2,8})'")
DEMO_SUFFIX = " (demo translation)"


def handle(system, user, messages, tools):
    if "translat" not in (system or "").lower():
        return None
    match = LANGUAGE.search(system or "")
    if not match:
        return None
    from rooms.voice import DEMO_TRANSCRIPTS

    language = match.group(1).lower().split("-")[0]
    text = (user or "").strip()
    for row in DEMO_TRANSCRIPTS.values():
        if text == row["text"]:
            translated = row["translations"].get(language)
            if translated:
                return _result(translated + DEMO_SUFFIX)
            return None  # no canned line for this language: the built-in demo answer labels it
    return None
