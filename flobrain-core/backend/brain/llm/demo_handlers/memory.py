"""Demo model answers for buddy memory capture (growth round M4).

Only for the capture prompt (``[flo:memory-capture]``). It returns candidate facts for typical
work sentences ("I prefer short answers", "I'm leading the Android launch") and nothing for
sensitive ones (the real filter still checks every candidate after this).
"""

import json
import re

MARK = "[flo:memory-capture]"
MESSAGE = re.compile(r"<message>\s*(.*?)\s*</message>", re.DOTALL)
F = re.IGNORECASE

RULES = [
    (re.compile(r"\bi(?:'d)? (?:really )?(?:prefer|like|love|want)\s+(?P<x>[^.!?\n]{3,120})", F), "preference", "Prefers {x}"),
    (re.compile(r"\b(?:please )?(?:always|never)\s+(?P<x>[^.!?\n]{3,120})", F), "preference", "{w} {x}"),
    (re.compile(r"\bi(?:'m| am) (?:leading|running|in charge of|responsible for)\s+(?P<x>[^.!?\n]{3,120})", F), "project", "Leads {x}"),
    (re.compile(r"\bi (?:lead|own|run)\s+(?P<x>[^.!?\n]{3,120})", F), "project", "Leads {x}"),
    (re.compile(r"\bi(?:'m| am) (?:working on|building|focused on)\s+(?P<x>[^.!?\n]{3,120})", F), "work_context", "Works on {x}"),
    (re.compile(r"\bi work (?:closely )?with\s+(?P<x>[^.!?\n]{3,120})", F), "people", "Works with {x}"),
    (re.compile(r"\bi(?:'m| am) (?:an? |the )(?P<x>[^.!?\n]{3,80}?(?:engineer|developer|designer|manager|lead|analyst|intern|writer|marketer|founder))\b", F), "work_context", "Works as {a} {x}"),
    (re.compile(r"(?:أفضل|افضل|بفضل)\s+(?P<x>[^.!؟\n]{3,120})", F), "preference", "يفضل {x}"),
]


def _result(text):
    from brain.llm.demo_ai import _result as make

    return make(text)


def facts_for(sentence: str) -> list[dict]:
    from buddy_memory.filters import check

    out = []
    for part in re.split(r"(?<=[.!?؟])\s+|\n+", sentence or ""):
        if not part.strip() or check(part):
            continue  # sensitive: the demo model proposes nothing for it
        for pattern, category, template in RULES:
            m = pattern.search(part)
            if not m:
                continue
            x = m.group("x").strip(" ,.;")
            article = "an" if x[:1].lower() in "aeiou" else "a"
            word = "Always" if "always" in m.group(0).lower() else "Never"
            fact = template.format(x=x, a=article, w=word)
            fact = fact[:1].upper() + fact[1:]
            if not check(fact) and all(f["text"] != fact for f in out):
                out.append({"text": fact[:200], "category": category})
            break
        if len(out) >= 3:
            break
    return out


def handle(system, user, messages, tools):
    if MARK not in (system or ""):
        return None
    m = MESSAGE.search(user or "")
    text = (m.group(1) if m else user or "").replace("‹", "<").replace("›", ">")
    return _result(json.dumps({"facts": facts_for(text)}, ensure_ascii=False))
