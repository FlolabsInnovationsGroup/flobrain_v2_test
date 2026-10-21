"""PII redaction detectors (Phase 17a, Q25).

A detector finds spans of personal data in text; ``redact`` replaces them with a label such as
``[email removed]``. Choose one with ``PII_DETECTOR``:

- ``""`` (default outside demo mode): no detector, so the org setting cannot be turned on.
- ``"regex"`` (default in demo mode): ``RegexDetector`` below. **Basic**: emails, phone
  numbers, card-like numbers (Luhn checked), IBANs, US SSNs, Egyptian national IDs and
  Turkish identity numbers (checksum). It knows nothing about names, addresses or context,
  misses unusual formats and may remove some harmless numbers. Use it as a demo and a
  fallback, not as the production detector.
- ``"some.module.ClassName"``: a real detector (for example an adapter for a self-hosted
  Presidio analyzer). The class takes no arguments and has ``name``, ``basic`` and
  ``find(text) -> list[(start, end, kind)]``.

``redact_for(org, text)`` applies the org's ``pii_redaction`` policy for content that leaves
FloBrain (external agents today). Callers that send text to external models can use it too.
"""

import importlib
import re
from functools import lru_cache

from django.conf import settings

LABELS = {"email": "[email removed]", "phone": "[phone removed]", "card": "[card removed]", "id": "[id removed]", "iban": "[iban removed]"}


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def _tckn(digits: str) -> bool:
    if len(digits) != 11 or digits[0] == "0":
        return False
    d = [int(c) for c in digits]
    return (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


class RegexDetector:
    """Basic, pattern-only detector. See the module docstring for what it does not catch."""

    name = "regex"
    basic = True

    EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")
    IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
    CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
    SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    LONG_ID = re.compile(r"(?<!\d)\d{11}(?!\d)|(?<!\d)[23]\d{13}(?!\d)")
    DATE = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}")
    PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d\s().-]{6,18}\d(?!\w)")

    def find(self, text: str) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []

        def free(start, end):
            return all(end <= s or start >= e for s, e, _ in spans)

        def add(pattern, kind, check=None):
            for m in pattern.finditer(text):
                if free(m.start(), m.end()) and (check is None or check(m.group(0))):
                    spans.append((m.start(), m.end(), kind))

        digits = lambda s: re.sub(r"\D", "", s)  # noqa: E731
        add(self.EMAIL, "email")
        add(self.IBAN, "iban")
        add(self.CARD, "card", lambda s: 13 <= len(digits(s)) <= 19 and _luhn(digits(s)))
        add(self.SSN, "id")
        add(self.LONG_ID, "id", lambda s: len(s) == 14 or _tckn(s))
        add(self.PHONE, "phone", lambda s: 8 <= len(digits(s)) <= 15 and not self.DATE.fullmatch(s.strip()))
        return sorted(spans)


@lru_cache(maxsize=4)
def _load(spec: str):
    if spec == "regex":
        return RegexDetector()
    module, _, cls = spec.rpartition(".")
    if not module:
        return None
    return getattr(importlib.import_module(module), cls)()


def detector_spec() -> str:
    spec = getattr(settings, "PII_DETECTOR", None)
    if spec is None or spec == "":
        return "regex" if getattr(settings, "DEMO_MODE", False) else ""
    return str(spec)


def get_detector():
    spec = detector_spec()
    return _load(spec) if spec else None


def describe() -> dict | None:
    d = get_detector()
    return {"name": d.name, "basic": bool(getattr(d, "basic", False))} if d else None


def redact(text: str, detector=None) -> tuple[str, int]:
    """Returns (text with PII replaced, number of replacements)."""
    detector = detector or get_detector()
    if detector is None or not text:
        return text, 0
    out, last, n = [], 0, 0
    for start, end, kind in detector.find(text):
        if start < last:
            continue
        out.append(text[last:start])
        out.append(LABELS.get(kind, "[removed]"))
        last, n = end, n + 1
    out.append(text[last:])
    return "".join(out), n


def policy_for(org) -> str:
    from organizations.models import OrgPolicy

    policy = OrgPolicy.objects.filter(org=org).only("pii_redaction").first() if org is not None else None
    return policy.pii_redaction if policy else "off"


def redact_for(org, text: str) -> tuple[str, int]:
    """Content leaving FloBrain: redacted when the org's policy is ``external_only`` or ``always``."""
    if policy_for(org) == "off":
        return text, 0
    return redact(text)


def redact_value(org, value):
    """``redact_for`` over every string inside a JSON-like value. Returns (value, count)."""
    if policy_for(org) == "off":
        return value, 0
    detector = get_detector()
    count = 0

    def walk(v):
        nonlocal count
        if isinstance(v, str):
            out, n = redact(v, detector)
            count += n
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    return walk(value), count
