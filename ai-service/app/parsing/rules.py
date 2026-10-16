"""Rule-based parser for conversational expense notes.

Handles inputs like:
    "I spent ₦2,000 on lunch at Moremi cafeteria and ₦1,500 on Keke transport today"
    "chop 1.5k, keke 200, mtn data 2k yesterday"
    "my papa send me 30k via kuda"

Used as the offline fallback when the AI model is unavailable, and to cross-check AI output.
"""

import re
from datetime import date, timedelta

from app.categories import Category, categorize, label
from app.schemas import ParsedItem

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
AMOUNT_RE = re.compile(
    rf"""
    (?:(?:₦|\bNGN\s?|\bN)\s?(?P<a1>{_NUM})\s?(?P<k1>k\b|K\b)?)          # ₦2,000 / N2k / NGN 500
    | (?:\b(?P<a2>{_NUM})\s?(?P<k2>k|K)\b)                              # 2k / 1.5K
    | (?:\b(?P<a3>{_NUM})\s?(?:naira|ngn)\b)                            # 2000 naira
    | (?:(?<!(?-i:[A-Z]{{2}})\s)(?<!(?-i:[A-Z]{{3}})\s)(?<!(?-i:[A-Z]{{4}})\s)(?<![:\d.,])\b(?P<a4>{_NUM})\b
         (?!\s?(?:gb|mb|kb|kg|g|ml|l|am|pm|%|x|th|st|nd|rd|days?|hrs?|hours?|mins?|minutes?|weeks?|months?|pieces?|pcs|plates?)\b)
         (?![:.]\d))                                                     # bare 1500 (lower confidence)
    """,
    re.I | re.X,
)

# A comma followed by three digits is a thousands separator ("₦2,000"), not a clause break.
SPLIT_RE = re.compile(r"\s*(?:,(?!\d{3})|;|\n|\band\b|\bthen\b|\bplus\b|\balso\b|&|\+)\s*", re.I)

PAYMENT_METHODS: list[tuple[str, str]] = [
    (r"\bcash\b|\bhand\s?to\s?hand\b", "cash"),
    (r"\bkuda\b", "kuda"),
    (r"\bopay\b", "opay"),
    (r"\bpalm\s?pay\b", "palmpay"),
    (r"\bmoniepoint\b", "moniepoint"),
    (r"\bbmoni\b", "bmoni"),
    (r"\bgt\s?bank\b|\bgtb\b|\bsquad\b", "gtbank"),
    (r"\bzenith\b", "zenith"),
    (r"\buba\b", "uba"),
    (r"\baccess\b", "access"),
    (r"\bfirst\s?bank\b", "firstbank"),
    (r"\bpos\b", "pos"),
    (r"\bcard\b", "card"),
    (r"\btransfer\b|\btrf\b|\bsent\b", "transfer"),
]

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DATE_WORDS_RE = re.compile(
    r"\b(today|this morning|this afternoon|this evening|tonight|yesterday|last night|"
    r"(\d+)\s+days?\s+ago|(?:on\s+|last\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.I,
)

FILLER_RE = re.compile(
    r"^\s*(?:i\s+)?(?:just\s+)?(?:spent|spend|paid|pay|bought|buy|used|use|gave|give|dropped|drop|"
    r"wasted|blew|chopped)?\s*(?:about|around|like|roughly)?\s*",
    re.I,
)
MERCHANT_RE = re.compile(
    r"\b(?:at|from|in|to)\s+((?:the\s+)?[A-Za-z0-9'&.\-]+(?:\s+(?!today\b|yesterday\b|for\b|on\b|with\b|via\b|using\b|by\b|last\b|this\b)[A-Za-z0-9'&.\-]+){0,3})",
    re.I,
)
STOP_TAIL_RE = re.compile(r"\b(?:today|yesterday|this \w+|last night|tonight|via \w+|with \w+|using \w+|by \w+)\b.*$", re.I)


def _to_amount(m: re.Match[str]) -> tuple[float, float]:
    """Return (amount, confidence) for an AMOUNT_RE match."""
    for g, k, conf in (("a1", "k1", 0.95), ("a2", "k2", 0.9), ("a3", None, 0.95), ("a4", None, 0.7)):
        raw = m.group(g)
        if raw:
            value = float(raw.replace(",", ""))
            if k and m.group(k):
                value *= 1000
            return value, conf
    return 0.0, 0.0


def resolve_date(text: str, ref: date) -> date | None:
    m = DATE_WORDS_RE.search(text)
    if not m:
        return None
    word = m.group(1).lower()
    if word in ("yesterday", "last night"):
        return ref - timedelta(days=1)
    if m.group(2):
        return ref - timedelta(days=int(m.group(2)))
    if m.group(3):
        target = WEEKDAYS.index(m.group(3).lower())
        delta = (ref.weekday() - target) % 7
        return ref - timedelta(days=delta or 7) if "last" in word else ref - timedelta(days=delta)
    return ref


def payment_method(text: str) -> str | None:
    for pattern, name in PAYMENT_METHODS:
        if re.search(pattern, text, re.I):
            return name
    return None


def merchant_of(text: str) -> str | None:
    m = MERCHANT_RE.search(text)
    if not m:
        return None
    name = STOP_TAIL_RE.sub("", m.group(1)).strip(" .,-")
    name = re.sub(r"^the\s+", "", name, flags=re.I)
    if not name or AMOUNT_RE.fullmatch(name) or payment_method(name):
        return None
    return " ".join(w if w.isupper() else w.capitalize() for w in name.split())


def describe(clause: str) -> str:
    text = AMOUNT_RE.sub(" ", clause)
    text = DATE_WORDS_RE.sub(" ", text)
    for pattern, _ in PAYMENT_METHODS:
        text = re.sub(
            rf"(?:\b(?:via|with|using|by|through|on|in|from)\s+(?:my\s+)?)?(?:{pattern})(?:\s+(?:card|account|wallet|app|bank))?",
            " ", text, flags=re.I,
        )
    text = FILLER_RE.sub("", text)
    text = re.sub(r"^\s*(?:on|for|naira)\b\s*", "", text, flags=re.I)
    # Drop prepositions left dangling once the amount/date/payment words are removed ("data for").
    text = re.sub(r"\s+(?:for|on|at|to|of|in)(?=\s+(?:for|on|at|to|of|in)\b|\s*$)", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    return (text[:1].upper() + text[1:]) if text else "Expense"


def parse(text: str, ref: date | None = None) -> tuple[list[ParsedItem], list[str]]:
    ref = ref or date.today()
    notes: list[str] = []
    global_date = resolve_date(text, ref)
    global_method = payment_method(text)

    # Clauses without an amount ("rice and beans 1500") are glued onto the next clause.
    chunks: list[str] = []
    pending = ""
    for part in (p for p in SPLIT_RE.split(text) if p and p.strip()):
        candidate = f"{pending} {part}".strip() if pending else part
        if AMOUNT_RE.search(part):
            chunks.append(candidate)
            pending = ""
        else:
            pending = candidate
    if pending:
        if chunks:
            chunks[-1] = f"{chunks[-1]} {pending}"
        else:
            notes.append("No amount found. Try something like '₦1,500 on lunch'.")

    items: list[ParsedItem] = []
    for clause in chunks:
        matches = list(AMOUNT_RE.finditer(clause))
        amount, conf = _to_amount(matches[0])
        if len(matches) > 1:
            notes.append(f"'{clause}' has more than one number; used ₦{amount:,.0f}.")
        if amount <= 0:
            continue
        cat = categorize(clause)
        if cat == Category.OTHER:
            conf = min(conf, 0.6)
        direction = "credit" if cat == Category.INCOME else "debit"
        items.append(ParsedItem(
            amount=amount,
            direction=direction,
            category=cat,
            category_label=label(cat),
            merchant=merchant_of(clause),
            description=describe(clause),
            date=resolve_date(clause, ref) or global_date or ref,
            payment_method=payment_method(clause) or global_method,
            confidence=round(conf, 2),
        ))
    return items, notes
