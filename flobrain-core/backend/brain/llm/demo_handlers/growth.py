"""Demo model answers for the Academy coach (``DEMO_AI`` only).

Handles only prompts carrying the coach marker. The answer is built from the lesson the person is
reading (or the lesson list) and the next-lesson line in the system prompt, in Arabic when the
question is in Arabic, and says it is demo output.
"""

import re

from brain.llm.demo_ai import _result

MARK = "[flo:academy-coach]"
ARABIC = re.compile("[\u0600-\u06ff]")
LESSON = re.compile(r'<lesson key="([a-z-]+)" title="([^"]+)">')
NEXT = re.compile(r'suggesting the next lesson: "([^"]+)"')
OFF = re.compile(r"Features off for them: ([^\n]*)\.")


def _question(user):
    found = re.search(r"<question>\s*(.*?)\s*</question>", user or "", re.DOTALL)
    return found.group(1) if found else ""


def handle(system, user, messages, tools):
    if MARK not in (system or ""):
        return None
    question = _question(user)
    lessons = LESSON.findall(user or "")
    nxt = NEXT.search(system)
    off = OFF.search(system)
    arabic = bool(ARABIC.search(question))
    topic = lessons[0][1] if len(lessons) == 1 else None
    if arabic:
        parts = [
            f"حسب درس \"{topic}\": ابدأ بخطوة صغيرة وجرّبها الآن من زر \"جرّبه\"." if topic else "ابدأ بالدرس الذي يناسب سؤالك، ثم جرّب الخطوة مباشرة في FloBrain.",
            "اكتب هدفك والسياق والشكل الذي تريده، وراجع المصادر قبل أن تعيد إرسال أي إجابة.",
        ]
        if nxt:
            parts.append(f"الدرس التالي المقترح: {nxt.group(1)}.")
        parts.append("(إجابة تجريبية من نموذج العرض في FloBrain.)")
    else:
        parts = [
            f"From the \"{topic}\" lesson: start small and use the Try it button to do it once now." if topic else "Pick the lesson closest to your question, then try the step right away in FloBrain.",
            "Say the goal, the context and the format you want, and check the sources before you forward an answer.",
        ]
        if off and off.group(1).strip() and off.group(1).strip() != "none":
            parts.append(f"Some features are off for you ({off.group(1).strip()}); an admin can ask to turn them on.")
        if nxt:
            parts.append(f"Next lesson: {nxt.group(1)}.")
        parts.append("(Demo answer from FloBrain's demo model.)")
    return _result(" ".join(parts))
