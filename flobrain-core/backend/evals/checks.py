"""Deterministic checks for one answer. Pure functions: no database, no network.

Each check returns ``{"check", "passed", "expected", "got", "reason"}``. Text matching is
case-insensitive, ignores extra spaces and folds common Arabic letter variants (alef forms,
taa marbuta, alef maqsura, tatweel and diacritics), so "إجازة" matches "اجازه".
"""

import re
import unicodedata

CITATION = re.compile(r"\[(\d{1,2})\]")
ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
LATIN = re.compile(r"[A-Za-z]")
DIACRITICS = re.compile(r"[ً-ْٰـ]")  # harakat, dagger alef, tatweel
FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = DIACRITICS.sub("", text).translate(FOLD)
    return " ".join(text.casefold().split())


def word_count(text: str) -> int:
    return len((text or "").split())


def detect_language(text: str) -> str:
    """"ar", "en" or "" (no letters). Counts letters, so numbers and tool names don't decide it."""
    ar, en = len(ARABIC.findall(text or "")), len(LATIN.findall(text or ""))
    if not ar and not en:
        return ""
    return "ar" if ar >= en else "en"


def _row(check, passed, expected, got, reason):
    return {"check": check, "passed": bool(passed), "expected": expected, "got": got, "reason": reason}


def run_checks(case, answer: str, calls: list) -> list:
    """``case`` is an ``EvalCase`` (or anything with its fields). ``calls`` are the captured tool
    calls: ``[{"tool": key or function name, ...}]``."""
    out = []
    norm = normalize(answer)
    tools = [str(c.get("tool") or "") for c in calls or []]
    for phrase in case.must_include or []:
        hit = normalize(phrase) in norm
        out.append(_row("must_include", hit, phrase, "found" if hit else "missing",
                        "" if hit else f"The answer does not say “{phrase}”."))
    for phrase in case.must_not_include or []:
        hit = normalize(phrase) in norm
        out.append(_row("must_not_include", not hit, phrase, "found" if hit else "absent",
                        f"The answer says “{phrase}”, which it must not." if hit else ""))
    if case.must_cite:
        cited = sorted({int(n) for n in CITATION.findall(answer or "")})
        out.append(_row("must_cite", bool(cited), "a [n] citation", ", ".join(f"[{n}]" for n in cited) or "none",
                        "" if cited else "The answer does not cite a source."))
    expected = (case.expected_tool or "").strip()
    if expected == "none":
        ok = not tools
        out.append(_row("expected_tool", ok, "no action", ", ".join(tools) or "no action",
                        "" if ok else "The buddy prepared an action when none was expected."))
    elif expected:
        ok = expected in tools
        out.append(_row("expected_tool", ok, expected, ", ".join(tools) or "no action",
                        "" if ok else f"The buddy did not prepare {expected}."))
    forbidden = [t for t in tools if t in set(case.forbidden_tools or [])]
    if case.forbidden_tools:
        out.append(_row("forbidden_tools", not forbidden, "none of " + ", ".join(case.forbidden_tools),
                        ", ".join(tools) or "no action",
                        f"The buddy prepared a forbidden action: {', '.join(forbidden)}." if forbidden else ""))
    if case.max_words:
        words = word_count(answer)
        ok = words <= case.max_words
        out.append(_row("max_words", ok, case.max_words, words,
                        "" if ok else f"The answer has {words} words; the limit is {case.max_words}."))
    if case.language in ("ar", "en"):
        got = detect_language(answer)
        ok = got == case.language
        names = {"ar": "Arabic", "en": "English", "": "no text"}
        out.append(_row("language", ok, case.language, got or "none",
                        "" if ok else f"The answer is in {names[got]}, not {names[case.language]}."))
    return out


def case_score(checks: list, judge: dict | None) -> float:
    """0..1: the share of checks passed, with the judge's 1-5 counted as (score - 1) / 4.
    A case with nothing to check scores 1 if it produced an answer (the caller handles errors)."""
    parts = [1.0 if c["passed"] else 0.0 for c in checks]
    if judge is not None:
        parts.append((judge["score"] - 1) / 4 if judge.get("valid") else 0.0)
    return sum(parts) / len(parts) if parts else 1.0


JUDGE_PASS = 3  # a judge score below this fails the case


def case_passed(checks: list, judge: dict | None) -> bool:
    if not all(c["passed"] for c in checks):
        return False
    if judge is not None:
        return bool(judge.get("valid")) and judge["score"] >= JUDGE_PASS
    return True
