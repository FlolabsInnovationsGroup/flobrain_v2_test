"""Shared prompt pieces for retrieved sources (7i knowledge ask, 8a buddies).

Sources are quoted data: each sits inside a ``<source>`` tag that its own text
cannot open or close, and the caller's system prompt says they are not
instructions.
"""

import re

from django.conf import settings

EXCERPT_CHARS = 300


_TAG = re.compile(r"<(\s*/?\s*)source", re.IGNORECASE)


def quote(text: str) -> str:
    """A source cannot open or close a source tag, in any case or spacing."""
    return _TAG.sub(lambda m: "&lt;" + m.group(1) + "source", text or "")


def quote_attr(text: str) -> str:
    return quote(text).replace('"', "&quot;").replace("\n", " ")


def sources_block(hits) -> tuple[str, int]:
    """The ``Sources:`` block and how many hits fit in ``KNOWLEDGE_CONTEXT_CHARS``."""
    budget = int(getattr(settings, "KNOWLEDGE_CONTEXT_CHARS", 12000) or 12000)
    parts, used = [], 0
    for n, hit in enumerate(hits, start=1):
        body = quote(hit.chunk.text)
        if used + len(body) > budget:
            body = body[: max(0, budget - used)]
        if not body:
            break
        kind = "document" if hit.chunk.source_type == "doc" else "room message"
        parts.append(f'<source id="{n}" type="{kind}" title="{quote_attr(hit.title)}">\n{body}\n</source>')
        used += len(body)
    return "Sources:\n" + "\n\n".join(parts), len(parts)


def citations(hits) -> list[dict]:
    return [
        {
            "n": n,
            "source_type": hit.chunk.source_type,
            "source_id": str(hit.chunk.source_id),
            "room": str(hit.chunk.room_id),
            "title": hit.title,
            "score": round(hit.score, 4),
            "excerpt": hit.chunk.text[:EXCERPT_CHARS],
        }
        for n, hit in enumerate(hits, start=1)
    ]
