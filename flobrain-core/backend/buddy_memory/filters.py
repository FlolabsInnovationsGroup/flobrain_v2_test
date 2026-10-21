"""Refuse sensitive facts before anything is stored.

``check(text)`` returns ``""`` when a fact may be kept, or the blocked category. It is
conservative on purpose: a harmless fact that is refused costs little, a sensitive fact that is
kept costs a lot. Two layers:

1. ``platform_api.pii`` (always the regex detector at least): emails, phone numbers, card numbers
   (Luhn), IBANs, national ids.
2. Categories that are never kept: health, religion, politics, sexual orientation and private
   life, finances (salary, debt), government ids, card and bank details, precise home address,
   children's data, credentials, and other special categories (ethnicity, criminal record, union).

Text is normalised first (NFKC, lower case, zero-width characters removed, accents removed) and
checked again with common tricks undone (spaced letters, digit-for-letter swaps), so spellings
like "s a l a r y" or "p4ssport" are still caught.

The reason is used for counting only; neither the reason nor the text is logged or stored.
"""

import re
import unicodedata

SENSITIVE = (
    "health",
    "religion",
    "politics",
    "sexual_orientation",
    "finances",
    "government_id",
    "card_number",
    "home_address",
    "children",
    "credentials",
    "special_category",
)

ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\u00ad]")
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})


def fold(text: str) -> str:
    """Lower case without accents or Arabic diacritics, Arabic letter variants unified."""
    text = unicodedata.normalize("NFKC", text or "")
    text = ZERO_WIDTH.sub("", text).lower()
    decomposed = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text).translate(ARABIC_FOLD)


def _rx(*words):
    # Patterns are folded like the text, so "médic" and "medic" are the same pattern.
    return re.compile(r"(?<![\w])(?:" + "|".join(fold(w) for w in words) + r")", re.IGNORECASE)


# Word-start patterns on the normalised text (English, Arabic, Turkish, French, Portuguese).
PATTERNS = {
    "health": _rx(
        r"health", r"diagnos", r"medicat", r"medicine", r"prescri", r"therap", r"psychiat", r"psycholog", r"doctor",
        r"hospital", r"clinic\b", r"surgery", r"illness", r"sick", r"disease", r"disorder", r"symptom",
        r"pregnan", r"miscarr", r"ivf\b", r"fertility", r"cancer", r"tumou?r", r"diabet", r"insulin", r"asthma",
        r"epilep", r"hiv\b", r"aids\b", r"std\b", r"depress", r"anxiety", r"panic attack", r"bipolar", r"adhd",
        r"autis", r"ocd\b", r"ptsd", r"schizo", r"suicid", r"self[- ]harm", r"eating disorder", r"anorex", r"bulim",
        r"rehab", r"addict", r"alcoholi", r"sober", r"disabilit", r"disabled", r"wheelchair", r"blind\b", r"deaf\b",
        r"allerg", r"migraine", r"chronic", r"blood pressure", r"cholesterol", r"vaccin", r"covid", r"infection",
        r"injur", r"mental", r"burn ?out", r"weight loss", r"diet pill", r"menstru", r"period pain", r"menopaus",
        r"مرض", r"مريض", r"دواء", r"أدوية", r"علاج", r"طبيب", r"مستشفى", r"حامل", r"حمل\b", r"اكتئاب", r"قلق", r"سكري", r"سرطان", r"نفسي",
        r"hastal", r"ilaç", r"ilac", r"doktor", r"hastane", r"hamile", r"depresyon", r"kaygı",
        r"malad", r"médic", r"medic", r"hôpital", r"enceinte", r"dépress", r"santé",
        r"doença", r"doenca", r"remédio", r"remedio", r"grávida", r"gravida", r"depressão", r"saúde", r"saude",
    ),
    "religion": _rx(
        r"religio", r"muslim", r"moslem", r"islam", r"christian", r"catholic", r"protestant", r"orthodox", r"evangel",
        r"jew(?:s|ish)?\b", r"juda", r"hindu", r"buddhis", r"sikh", r"atheis", r"agnostic", r"church", r"mosque", r"synagogue",
        r"temple", r"pray", r"ramadan", r"fasting", r"halal", r"kosher", r"bible", r"quran", r"koran",
        r"torah", r"\bgod\b", r"allah", r"faith", r"spiritual", r"hijab", r"niqab", r"sabbath", r"easter", r"\beid\b",
        r"diwali", r"converted to", r"مسلم", r"مسيحي", r"قبطي", r"يهود", r"دين", r"صلاة", r"أصلي", r"اصلي", r"صيام", r"صايم", r"رمضان", r"مسجد", r"كنيسة", r"حجاب",
        r"namaz", r"oruç", r"oruc", r"cami(?:ye|de)?\b", r"kilise", r"müslüman", r"musluman", r"hristiyan",
        r"prière", r"priere", r"mosquée", r"église", r"eglise", r"musulman", r"chrétien", r"juif",
        r"oração", r"oracao", r"igreja", r"mesquita", r"cristão", r"cristao", r"judeu",
    ),
    "politics": _rx(
        r"politic", r"vote", r"voting", r"voter", r"election", r"ballot", r"democrat", r"republican", r"liberal",
        r"conservative", r"socialis", r"communis", r"fascis", r"left[- ]wing", r"right[- ]wing", r"labour party",
        r"labor party", r"tory", r"maga\b", r"party member", r"activis", r"protest", r"campaign for", r"union member",
        r"trade union", r"سياس", r"انتخاب", r"حزب", r"أصوت", r"اصوت", r"seçim", r"secim", r"parti\b", r"siyas",
        r"politique", r"élection", r"parti politique", r"syndicat", r"eleição", r"eleicao", r"partido", r"sindicato",
    ),
    "sexual_orientation": _rx(
        r"gay\b", r"lesbian", r"bisexual", r"queer", r"homosexual", r"heterosexual", r"lgbt",
        r"transgender", r"\btrans\b", r"non[- ]binary", r"nonbinary", r"asexual", r"pansexual", r"sexual", r"\bsex\b",
        r"coming out", r"came out", r"boyfriend", r"girlfriend", r"husband", r"\bwife\b", r"spouse", r"partner'?s? (?:name|is)",
        r"divorc", r"dating", r"tinder", r"affair", r"pronoun", r"مثلي", r"جنس", r"زوجي", r"زوجتي", r"خطيب", r"طلاق",
        r"eşcinsel", r"escinsel", r"kocam", r"karım", r"karim\b", r"sevgilim", r"boşan",
        r"homosexuel", r"mon mari", r"ma femme", r"petit ami", r"petite amie", r"divorce",
        r"meu marido", r"minha esposa", r"namorad", r"divórcio", r"divorcio",
    ),
    "finances": _rx(
        r"salar", r"\bpay\b", r"paid\b", r"\bpaycheck", r"wage", r"income", r"earn(?:s|ed|ing|ings)?\b", r"bonus", r"pay ?rise", r"net worth",
        r"debt", r"loan", r"mortgage", r"overdraft", r"credit score", r"credit rating", r"bankrupt", r"savings",
        r"\brent\b", r"invest(?:ment|ments|or|ors|ing|ed)?\b", r"stock option", r"crypto(?:currency|currencies)?\b", r"bitcoin", r"tax return", r"inheritance", r"pension",
        r"bank account", r"account number", r"routing number", r"sort code", r"iban\b", r"swift code",
        r"راتب", r"مرتب", r"دخل", r"قرض", r"دين\b", r"ديون", r"حساب بنك", r"maaş", r"maas", r"borç", r"borc", r"kredi",
        r"salaire", r"revenu", r"prêt", r"dette", r"hypoth", r"salário", r"salario", r"empréstimo", r"emprestimo", r"dívida", r"divida",
    ),
    "government_id": _rx(
        r"passport", r"national id", r"national identity", r"id number", r"id card", r"identity card", r"identity number",
        r"social security", r"\bssn\b", r"\bsin\b number", r"tax id", r"tax number", r"\btin\b", r"\bnin\b",
        r"driver'?s licen", r"driving licen", r"licen[cs]e number", r"visa status", r"residence permit", r"residency",
        r"green card", r"work permit", r"immigra", r"asylum", r"refugee", r"citizenship", r"undocumented",
        r"جواز", r"رقم قومي", r"الرقم القومي", r"بطاقة شخصية", r"هوية", r"إقامة", r"اقامة", r"تأشيرة", r"لجوء",
        r"pasaport", r"kimlik", r"tc no", r"oturma izni", r"passeport", r"carte d'identit", r"titre de séjour",
        r"passaporte", r"\bcpf\b", r"\brg\b", r"identidade",
    ),
    "card_number": _rx(r"card number", r"credit card", r"debit card", r"\bcvv", r"\bcvc", r"card expiry", r"pin (?:code|number)", r"my pin\b", r"بطاقة ائتمان", r"kart numara", r"numéro de carte", r"cartão de crédito", r"cartao de credito"),
    "home_address": _rx(
        r"home address", r"my address", r"i live (?:at|on)", r"i live in (?:apartment|flat|building|street|\d)",
        r"\d+\s+\w+\s+(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|boulevard|blvd)\b", r"apartment \d", r"flat \d",
        r"apt\.? \d", r"floor \d", r"zip code", r"postcode", r"post code", r"postal code", r"عنواني", r"أسكن في شارع", r"اسكن في شارع",
        r"شقة", r"adresim", r"ev adres", r"mon adresse", r"j'habite au", r"meu endereço", r"meu endereco", r"moro na rua",
    ),
    "children": _rx(
        r"my (?:son|daughter|kid|kids|child|children|baby|babies|toddler|boy|girl|twins|stepson|stepdaughter)",
        r"(?:son|daughter|kid|child)'?s? (?:school|name|birthday|age|teacher|doctor)", r"years? old\b", r"nursery",
        r"kindergarten", r"daycare", r"pick(?:ing)? up the kids", r"school run", r"custody", r"babysit", r"nanny",
        r"ابني", r"بنتي", r"ابنتي", r"أولادي", r"اولادي", r"أطفالي", r"اطفالي", r"طفلي", r"oğlum", r"oglum", r"kızım", r"kizim", r"çocuğum", r"cocugum", r"çocuklarım",
        r"mon fils", r"ma fille", r"mes enfants", r"meu filho", r"minha filha", r"meus filhos",
    ),
    "credentials": _rx(r"password", r"passcode", r"passphrase", r"api key", r"secret key", r"access token", r"private key", r"\botp\b", r"2fa code", r"كلمة السر", r"كلمة المرور", r"şifre", r"sifre", r"mot de passe", r"senha"),
    "special_category": _rx(
        r"ethnic", r"race\b(?! condition)", r"racial", r"skin colou?r", r"caste", r"criminal", r"convict", r"arrest", r"prison",
        r"jail", r"probation", r"lawsuit against me", r"sued", r"genetic", r"biometric", r"fingerprint", r"dna\b",
        r"عرق", r"سجن", r"قبيلة", r"etnik", r"sabıka", r"sabika", r"cezaev", r"origine ethnique", r"casier judiciaire", r"prisão", r"prisao",
    ),
}

MONEY = re.compile(
    r"(?:[$€£¥₺]|\b(?:usd|eur|gbp|egp|sar|aed|tl|tnd|brl|r\$|le)\b|جنيه|ريال|درهم|دولار|lira|euros?|reais|dinars?)\s?\d"
    r"|\d[\d,.]*\s?(?:k|m|bn)?\s?(?:[$€£₺]|usd\b|eur\b|gbp\b|egp\b|sar\b|aed\b|tl\b|tnd\b|brl\b|dollars?|pounds?|euros?|lira|reais|dinars?|جنيه|ريال|درهم|دولار)"
    r"|\d+\s?k\s?(?:a|per|/)\s?(?:year|yr|month|mo)",
    re.IGNORECASE,
)
LONG_NUMBER = re.compile(r"\d[\d\s-]{6,}\d")  # 8+ digits in a row (ids, accounts), spaces or dashes allowed
DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{4}")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip()


SPACED = re.compile(r"(?<![\w'’])(?:\w[\s.\-_*]){2,}\w(?!\w)")


def deobfuscate(norm: str) -> str:
    """Undo common tricks: spaced letters ("s a l a r y"), dotted letters, digit-for-letter swaps
    inside words ("p4ssport"). Used only for checking."""
    text = SPACED.sub(lambda m: re.sub(r"[\s.\-_*]", "", m.group(0)), norm)
    return re.sub(r"\w*\d\w*", lambda m: m.group(0).translate(LEET) if re.search(r"[a-z]", m.group(0)) else m.group(0), text)


def _pii(text: str) -> bool:
    from platform_api import pii

    detector = pii.get_detector() or pii.RegexDetector()
    try:
        return bool(detector.find(text))
    except Exception:  # noqa: BLE001 - a broken custom detector must not let text through
        return True


def check(text: str) -> str:
    """``""`` when the fact may be kept, else the sensitive category that blocks it."""
    if not text or not text.strip():
        return "empty"
    norm = normalise(text)
    if _pii(text) or _pii(norm):
        return "pii"
    if any(not DATE.fullmatch(m.group(0).strip()) for m in LONG_NUMBER.finditer(norm)):
        return "government_id"
    if MONEY.search(norm):
        return "finances"
    plain = deobfuscate(norm)
    for candidate in (norm, plain) if plain != norm else (norm,):
        for category, pattern in PATTERNS.items():
            if pattern.search(candidate):
                return category
    # Spaced letters may swallow a neighbouring word ("a s a l a r y" reads "asalary"): try every start.
    for run in SPACED.finditer(norm):
        joined = re.sub(r"[\s.\-_*]", "", run.group(0)).translate(LEET)
        for start in range(1, len(joined) - 2):
            for category, pattern in PATTERNS.items():
                if pattern.match(joined[start:]):
                    return category
    return ""


def is_sensitive(text: str) -> bool:
    return bool(check(text))
