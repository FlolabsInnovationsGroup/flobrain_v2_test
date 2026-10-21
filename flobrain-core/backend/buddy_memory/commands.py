"""Memory commands in a buddy chat, answered without a model call.

- "remember that ..." stores a fact (after the sensitivity filter); the person asked, so it is confirmed.
- "forget ..." deletes the person's memories that match; "forget everything" deletes them all.
  When nothing matches, the message goes to the buddy as usual ("forget the last answer").
- "what do you remember about me" lists what buddies know about the person and their teams.
- A plain "yes" or "no" right after the buddy asked "Should I remember this?" answers it.

English, Arabic, Turkish, French and Portuguese phrasings. Questions ("remember that meeting?")
are never treated as commands.
"""

import re
import unicodedata

from buddy_memory import filters, services
from buddy_memory.models import MemoryItem

F = re.IGNORECASE

REMEMBER = [
    re.compile(r"^\s*(?:please\s+|pls\s+)?(?:can you\s+|could you\s+)?remember(?:\s*:\s*|\s+that\s+|\s+this\s*:?\s*|\s+)(?P<fact>.{3,})$", F),
    re.compile(r"^\s*(?:من فضلك\s+|لو سمحت\s+)?(?:تذكر|تذكّر|افتكر|إفتكر)\s*(?:أن|ان|إن|إنّ|إني|اني|انى)?\s*(?P<fact>.{3,})$", F),
    re.compile(r"^\s*(?:souviens-toi|rappelle-toi|retiens|n'oublie pas)\s+(?:que\s+|qu'|de ça\s*:?\s*)?(?P<fact>.{3,})$", F),
    re.compile(r"^\s*(?:şunu\s+|sunu\s+)?(?:hatırla|hatirla|aklında tut|aklinda tut)\s*:?\s*(?P<fact>.{3,})$", F),
    re.compile(r"^\s*(?:por favor\s+)?(?:lembre-se|lembre|lembra|guarde)\s+(?:que|de que|disso\s*:)\s+(?P<fact>.{3,})$", F),
]
FORGET_ALL = re.compile(
    r"^\s*(?:please\s+)?(?:forget|delete|erase)\s+(?:everything|all)(?:\s+(?:about me|you know about me|you remember(?: about me)?|your memories))?\s*[.!]*\s*$"
    r"|^\s*(?:انس|انسى|إنسى|امسح)\s+(?:كل شيء|كل حاجة|كل حاجه)(?:\s+عني)?\s*[.!]*\s*$"
    r"|^\s*(?:oublie tout)(?:\s+sur moi)?\s*[.!]*\s*$"
    r"|^\s*(?:her şeyi unut|her seyi unut)\s*[.!]*\s*$"
    r"|^\s*(?:esqueça tudo|esqueca tudo|esquece tudo)(?:\s+sobre mim)?\s*[.!]*\s*$",
    F,
)
FORGET = [
    re.compile(r"^\s*(?:please\s+)?forget\s+(?:about\s+)?(?:that\s+)?(?P<q>.{2,})$", F),
    re.compile(r"^\s*(?:انس|انسى|إنسى|انسَ)\s+(?:أن|ان)?\s*(?P<q>.{2,})$", F),
    re.compile(r"^\s*oublie\s+(?:que\s+|qu')?(?P<q>.{2,})$", F),
    re.compile(r"^\s*(?P<q>.{2,}?)\s+(?:unut|kısmını unut)\s*[.!]*$", F),
    re.compile(r"^\s*(?:esqueça|esqueca|esquece)\s+(?:que\s+)?(?P<q>.{2,})$", F),
]
WHAT = re.compile(
    r"what (?:do|did) you (?:remember|know|recall) about me|what have you (?:remembered|saved|stored|kept) about me"
    r"|what do you have (?:on|about) me|show (?:me )?(?:my|your) memor(?:y|ies)|what(?:'s| is) in your memory about me"
    r"|(?:ماذا|ايش|إيش|ايه|إيه|شو|ما الذي)\s+(?:تتذكر|تعرف|تفتكر|تحفظ)\s+عني"
    r"|que (?:sais|retiens)-tu (?:de|sur) moi|qu'est-ce que tu (?:sais|retiens) (?:de|sur) moi"
    r"|(?:benim hakkımda|hakkımda|benim hakkimda|hakkimda) ne (?:hatırlıyorsun|hatirliyorsun|biliyorsun)"
    r"|o que (?:você|voce|vc|tu) (?:lembra|sabe) (?:de|sobre) mim",
    F,
)
YES = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|please do|do it|go ahead|remember it|save it|y"
    r"|نعم|أيوه|ايوه|ايوة|اه|آه|أجل|تمام|ماشي|احفظ|evet|olur|tamam|kaydet|oui|ouais|d'accord|vas-y|sim|claro|pode|pode sim)"
    r"(?:\s*[,.!]*\s*(?:please|thanks|thank you|شكرا|teşekkürler|merci|obrigad[oa]))?\s*[.!]*\s*$",
    F,
)
NO = re.compile(
    r"^\s*(?:no|nope|nah|n|don't|dont|do not|no thanks|no thank you|don't remember it|don't save it"
    r"|لا|لأ|لا شكرا|لا تحفظ|hayır|hayir|yok|istemiyorum|non|non merci|não|nao|não obrigad[oa])"
    r"(?:\s*[,.!]*\s*(?:thanks|thank you|شكرا|teşekkürler|merci|obrigad[oa]))?\s*[.!]*\s*$",
    F,
)
STOP = {"that", "this", "the", "about", "please", "you", "your", "and", "for", "with", "are", "was", "i'm", "its", "it's", "have", "has", "from", "what", "there", "them", "they"}

CATEGORY_HINTS = [
    ("people", re.compile(r"\b(?:work(?:s|ing)? with|my (?:manager|lead|boss|team ?mate|colleague)|reports? to)\b", F)),
    ("project", re.compile(r"\b(?:lead(?:s|ing)?|own(?:s|ing)?|launch|project|release|migration|roadmap)\b", F)),
    ("preference", re.compile(r"\b(?:prefer|like|love|hate|always|never|rather|please use|in (?:arabic|english|french|turkish|portuguese))", F)),
    ("work_context", re.compile(r"\b(?:i'm an?|i am an?|work(?:s|ing)? (?:as|on|in)|my role|based in|time ?zone|hours|shift)\b", F)),
]

NEVER = (
    "I can't remember that. Buddies don't keep health, beliefs, politics, relationships, money, ID or card numbers, "
    "addresses, children's details, passwords or contact details. Nothing was saved."
)


def _clean(text):
    text = unicodedata.normalize("NFKC", text or "").strip()
    return " ".join(text.split())


def _fact(raw):
    fact = raw.strip().strip("\"“”'").rstrip(" .!")
    return fact[:1].upper() + fact[1:] if fact else fact


def guess_category(fact) -> str:
    for category, pattern in CATEGORY_HINTS:
        if pattern.search(fact):
            return category
    return "other"


def _words(q):
    return [w for w in re.findall(r"[\w']{3,}", filters.normalise(q)) if w not in STOP]


def matches(items, q):
    words = _words(q)
    norm_q = filters.normalise(q).strip(" .!")
    if not words:
        return []
    out = []
    for item in items:
        text = filters.normalise(item.text)
        if all(w in text for w in words) or (len(text) >= 8 and text.strip(" .!") in norm_q):
            out.append(item)
    return out


def _off_reply(user, org):
    row = services.rules(org)
    if not row.enabled:
        return "Your organization has turned buddy memory off, so I can't remember things right now."
    return "Memory is paused for you. Turn it back on on the Memory page if you want buddies to remember things."


def _list_reply(user, org):
    from organizations.models import TeamMembership

    mine = list(services.personal(user, org).filter(status=MemoryItem.STATUS_ACTIVE).order_by("-pinned", "-created_at")[:20])
    pending = services.personal(user, org).filter(status=MemoryItem.STATUS_PENDING).count()
    row = services.rules(org)
    team = []
    if row.team_memory:
        ids = TeamMembership.objects.filter(team__org=org, user=user).values_list("team_id", flat=True)
        team = list(services.live(MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_TEAM, team_id__in=list(ids), status=MemoryItem.STATUS_ACTIVE)).select_related("team")[:10])
    parts = []
    if mine:
        parts.append("Here is what I remember about you:\n" + "\n".join(f"- {i.text}" for i in mine))
    else:
        parts.append("I don't remember anything about you yet.")
    if team:
        parts.append("About your teams:\n" + "\n".join(f"- {i.team.name}: {i.text}" for i in team))
    if pending:
        parts.append(f"{pending} suggestion(s) are waiting for your yes or no on the Memory page.")
    if services.is_paused(user, org) or not row.enabled:
        parts.append("Memory is paused or off for you right now, so buddies don't use or save any of this.")
    parts.append("You can see, change or delete all of it on the Memory page.")
    return "\n\n".join(parts)


def handle(user, org, chat, buddy, text) -> str | None:
    """The reply text when ``text`` is a memory command, else None (the buddy answers as usual)."""
    if not services.feature_on(user, org):
        return None
    text = _clean(text)
    if not text or "\n" in text or len(text) > 400:
        return None
    asked = list(services.personal(user, org).filter(status=MemoryItem.STATUS_PENDING, asked_chat=chat)) if chat is not None else []
    if asked and YES.match(text):
        for item in asked:
            services.confirm(item)
        return "Saved. You can see, change or delete it on the Memory page." if len(asked) == 1 else f"Saved {len(asked)} memories. You can see, change or delete them on the Memory page."
    if asked and NO.match(text):
        services.delete_items(org, user, asked)
        return "OK, I won't remember that."
    if WHAT.search(text) and len(text) <= 120:
        return _list_reply(user, org)
    if FORGET_ALL.match(text):
        count = services.delete_items(org, user, services.personal(user, org))
        return f"Done. I deleted {count} memories about you." if count else "I don't remember anything about you."
    if text.rstrip().endswith("?"):
        return None
    for pattern in FORGET:
        m = pattern.match(text)
        if m:
            found = matches(services.personal(user, org), m.group("q"))
            if not found:
                return None  # not about memory ("forget the last answer"): the buddy answers
            services.delete_items(org, user, found)
            listed = "\n".join(f"- {i.text}" for i in found)
            return f"Forgotten:\n{listed}"
    for pattern in REMEMBER:
        m = pattern.match(text)
        if m:
            fact = _fact(m.group("fact"))
            row = services.working_for(user, org)
            if row is None:
                return _off_reply(user, org)
            if filters.check(fact):
                return NEVER
            try:
                item, new = services.add_personal(user, org, fact, guess_category(fact), MemoryItem.SOURCE_CHAT, row=row, confirmed=True, buddy=buddy)
            except services.MemoryInvalid as exc:
                return NEVER if exc.code == "sensitive" else exc.details
            if not new and item.status == MemoryItem.STATUS_PENDING:
                services.confirm(item)
            elif not new:
                return f"I already remember that: {item.text}"
            return f"Got it. I'll remember: {item.text}\nYou can change or delete it on the Memory page."
    return None
