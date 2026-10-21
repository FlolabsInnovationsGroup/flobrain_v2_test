"""Demo model answers for room AI, Ask the org and live translation (``DEMO_AI`` only).

- A question that comes with a ``Sources:`` block is answered by quoting the closest line of the
  most relevant source, with its citation ("[1]"). The reply says it comes from the demo model.
- A translation request returns a canned translation for the seeded demo messages (Arabic and
  English), so the live translation toggle shows real-looking text. Anything else passes on to
  the built-in demo translation.
"""

import html
import re

from brain.llm.demo_ai import TASK_WORDS, _question, _result

SOURCE = re.compile(r"<source\b([^>]*)>\n?(.*?)\n?</source>", re.DOTALL)
ATTR = re.compile(r'(\w+)="([^"]*)"')
WORD = re.compile(r"[\w؀-ۿ]+")
STOP = {
    "a", "an", "and", "are", "about", "at", "be", "by", "can", "did", "do", "does", "for", "from", "has",
    "have", "how", "i", "in", "is", "it", "me", "of", "on", "or", "our", "so", "tell", "that", "the",
    "this", "to", "us", "was", "we", "what", "when", "where", "which", "who", "why", "will", "with", "you",
}
LANGUAGE = re.compile(r"ISO code '([a-zA-Z-]{2,8})'")

# Seeded demo messages (demo/seed.py and demo/extras/20_rooms.py) → their translations.
TRANSLATIONS = {
    "ar": {
        "Morning team. Today: push notifications and the Android login bug.":
            "صباح الخير يا فريق. اليوم: الإشعارات الفورية وخلل تسجيل الدخول على أندرويد.",
        "I'm on the login timeout. I need the Android test device to reproduce it.":
            "أعمل على مهلة تسجيل الدخول. أحتاج جهاز اختبار أندرويد لأعيد إنتاج المشكلة.",
        "Omar is ordering one. Mark the task blocked until it arrives.":
            "عمر سيطلب جهازًا. ضع على المهمة علامة متوقفة حتى يصل.",
        "Onboarding screens v2 are in Figma. Feedback welcome before Thursday.":
            "شاشات التعريف بالإصدار الثاني موجودة على Figma. نرحب بملاحظاتكم قبل الخميس.",
        "Launch date is confirmed for the end of next month.": "تم تأكيد موعد الإطلاق في نهاية الشهر القادم.",
        "Screenshots need the final copy. Who owns the blog post?":
            "لقطات الشاشة تحتاج إلى النص النهائي. من المسؤول عن تدوينة الإطلاق؟",
        "I do. Draft by Monday.": "أنا. ستكون المسودة جاهزة يوم الاثنين.",
        "مرحبا! I'll share the release notes in Arabic too.": "مرحبا! سأشارك ملاحظات الإصدار بالعربية أيضًا.",
        "Can you pair with Sara on the onboarding API tomorrow?": "هل يمكنك العمل مع سارة على واجهة التعريف البرمجية غدًا؟",
        "Sure, 11:00 works.": "بالتأكيد، الساعة 11:00 مناسبة.",
        "@Youssef Adel can you check the crash reporting setup before Friday?":
            "@Youssef Adel هل يمكنك مراجعة إعداد تقارير الأعطال قبل الجمعة؟",
        "@Layla the push notifications API is ready for review.":
            "@Layla واجهة الإشعارات الفورية البرمجية جاهزة للمراجعة.",
        "Thanks! I'll review it after lunch.": "شكرًا! سأراجعها بعد الغداء.",
        "Here are the final onboarding illustrations. @Youssef can you add them to the build?":
            "هذه رسومات التعريف النهائية. @Youssef هل يمكنك إضافتها إلى النسخة؟",
    },
    "en": {
        "مرحبا! I'll share the release notes in Arabic too.": "Hello! I'll share the release notes in Arabic too.",
        "تمام، سأراجعه اليوم.": "OK, I'll review it today.",
        "النسخة التجريبية جاهزة للاختبار على أندرويد.": "The beta build is ready for testing on Android.",
        "سأضيفها اليوم، شكرًا يا سارة.": "I'll add them today, thanks Sara.",
    },
}


def _words(text):
    return {w.lower() for w in WORD.findall(text or "") if w.lower() not in STOP and len(w) > 1}


def _sources(block):
    out = []
    for attrs, body in SOURCE.findall(block):
        values = dict(ATTR.findall(attrs))
        out.append((values.get("id") or str(len(out) + 1), html.unescape(values.get("title") or ""), html.unescape(body.strip())))
    return out


def _best_line(body, question_words):
    lines = [re.sub(r"^\s*(?:#+|\d+[.)]|[-*])\s*", "", line).strip() for line in body.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    scored = [(len(_words(line) & question_words), -i, line) for i, line in enumerate(lines)]
    best = max(scored)
    line = best[2] if best[0] > 0 else lines[0]
    return line if len(line) <= 280 else line[:277].rstrip() + "..."


def _answer(user, messages, tools):
    question = _question(messages)
    if tools and TASK_WORDS.search(question):
        return None  # the built-in demo answer proposes the task
    sources = _sources(user)
    if not sources:
        return None
    asked = _words(question)
    # Retrieval order first, then the source that shares the most words with the question.
    ranked = sorted(enumerate(sources), key=lambda item: (-len(_words(item[1][1] + " " + item[1][2]) & asked), item[0]))
    _, (n, title, body) = ranked[0]
    line = _best_line(body, asked)
    if not line:
        return None
    where = f"In “{title}”" if title else "In your sources"
    return _result(
        f"{where} [{n}]: “{line}”\n\n"
        "(Answer from FloBrain's demo model: it quotes the closest source. A real model would write a full answer.)"
    )


def _translate(system, user):
    match = LANGUAGE.search(system)
    if not match:
        return None
    language = match.group(1).lower().split("-")[0]
    text = (user or "").strip()
    known = TRANSLATIONS.get(language, {})
    if text in known:
        return _result(known[text])
    for other in TRANSLATIONS.values():
        if text in other.values() and text not in known:
            # Already in the other language's form: find its source line.
            for source, translated in other.items():
                if translated == text and _is_language(source, language):
                    return _result(source)
    if _is_language(text, language):
        return _result(text)  # already in the reader's language
    return None


def _is_language(text, language):
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ")
    letters = sum(1 for ch in text if ch.isalpha()) or 1
    if language == "ar":
        return arabic / letters > 0.6
    if language == "en":
        return arabic == 0
    return False


def handle(system, user, messages, tools):
    if "translat" in (system or "").lower() and LANGUAGE.search(system or ""):
        return _translate(system, user)
    if (user or "").lstrip().startswith("Sources:"):
        return _answer(user, messages, tools)
    return None
