"""Demo model answers for the customer buddy (``DEMO_AI`` only). It answers from the first quoted
source with a citation, labelled as demo output, and says ESCALATE when there is no source."""

import re

from brain.llm.demo_ai import _result

MARKER = "[flo:customer-buddy]"
SOURCE = re.compile(r'<source id="(\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)
WORD = re.compile(r"\w{3,}", re.UNICODE)


def _question(user):
    return user.rsplit("\n\nQuestion: ", 1)[1] if "\n\nQuestion: " in user else ""


def _best_sentence(body, question):
    terms = {w.lower() for w in WORD.findall(question)}
    sentences = [s.strip(" -#*\n") for s in re.split(r"(?<=[.!?؟])\s+|\n+", body) if len(s.strip(" -#*\n")) > 12]
    if not sentences:
        return ""
    return max(sentences, key=lambda s: len(terms & {w.lower() for w in WORD.findall(s)}))


def handle(system, user, messages, tools):
    if MARKER not in (system or ""):
        return None
    sources = SOURCE.findall(user or "")
    if not sources:
        return _result("ESCALATE")
    n, body = sources[0]
    sentence = _best_sentence(body, _question(user))
    if not sentence:
        return _result("ESCALATE")
    return _result(f"{sentence} [{n}] (Demo answer)")
