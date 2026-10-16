"""Natural-language expense parsing with OpenAI, falling back to the rule parser."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.ai_client import structured_call
from app.categories import Category, categorize, label
from app.config import get_settings
from app.parsing import rules
from app.schemas import ParsedItem

SYSTEM_PROMPT = """You extract money movements from short notes written by Nigerian university students for Zuko, a student budgeting app.

Notes may be in English, Nigerian Pidgin or campus slang, may mention several items at once, and are often pasted from WhatsApp or bank SMS alerts.

For every distinct amount of money spent or received, return one item:
- amount: the Naira value as a plain number. "2k" = 2000, "1.5k" = 1500, "N500"/"₦500"/"500 naira" = 500. Ignore numbers that are not money (course codes like "PHY 202", data sizes like "10GB", times, quantities).
- direction: "credit" for money received (allowance, "my papa send me", transfers in, gig payouts, refunds), otherwise "debit".
- category: one of food, transport, data_airtime, school_materials, dues, accommodation, personal_leisure, income, other.
  food = meals, snacks, drinks, groceries ("chop", "buka", "mama put", cafeteria). transport = keke, okada, bus, BRT, shuttle, Bolt/Uber, fuel. data_airtime = data bundles, airtime, MTN/Glo/Airtel/9mobile. school_materials = handouts, textbooks, printing, photocopies, lab manuals. dues = departmental/faculty/association dues, registration fees. accommodation = rent, hostel, generator/power, gas, toiletries. personal_leisure = outings, cinema, parties, subscriptions, grooming, clothes. income = any credit.
- merchant: the place or person paid, title-cased, if one is named; otherwise null.
- description: a short, clean label (3-6 words), e.g. "Lunch at Moremi Cafeteria".
- days_ago: 0 for today or no date given, 1 for yesterday/last night, N for "N days ago"; for a weekday name, the number of days back to the most recent such day relative to the reference date.
- payment_method: cash, transfer, card, pos, kuda, opay, palmpay, moniepoint, bmoni, gtbank, zenith, uba, access, firstbank, or null if not stated.
- confidence: 0-1, how sure you are about amount and category together.

If something is ambiguous (e.g. one amount covers two things), keep it as one item and say so in notes. Never invent amounts that are not in the text. If the text contains no money movement, return an empty items list and explain in notes."""


class _AIItem(BaseModel):
    amount: float = Field(gt=0)
    direction: Literal["debit", "credit"]
    category: Category
    merchant: str | None
    description: str
    days_ago: int = Field(ge=0, le=60)
    payment_method: str | None
    confidence: float = Field(ge=0, le=1)


class _AIParse(BaseModel):
    items: list[_AIItem]
    notes: list[str]


def _amounts_in(text: str) -> set[float]:
    found = set()
    for m in rules.AMOUNT_RE.finditer(text):
        value, _ = rules._to_amount(m)
        if value > 0:
            found.add(value)
    return found


def parse_with_ai(text: str, ref: date) -> tuple[list[ParsedItem], list[str]] | None:
    settings = get_settings()
    result = structured_call(
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Reference date: {ref.isoformat()} ({ref.strftime('%A')})\n\n<note>\n{text}\n</note>",
        }],
        output_model=_AIParse,
        effort=settings.parse_effort,
        max_tokens=4000,
    )
    if result is None:
        return None

    notes = list(result.notes)
    # Guard against invented numbers: every AI amount should appear in the text (allowing "2k"-style forms).
    seen = _amounts_in(text)
    items: list[ParsedItem] = []
    for it in result.items:
        conf = it.confidence
        if seen and it.amount not in seen:
            conf = min(conf, 0.4)
            notes.append(f"Double-check ₦{it.amount:,.0f}: it doesn't appear verbatim in your note.")
        category = Category.INCOME if it.direction == "credit" else it.category
        if category == Category.INCOME and it.direction == "debit":
            category = categorize(it.description)
        items.append(ParsedItem(
            amount=it.amount,
            direction=it.direction,
            category=category,
            category_label=label(category),
            merchant=it.merchant,
            description=it.description,
            date=date.fromordinal(ref.toordinal() - it.days_ago),
            payment_method=it.payment_method,
            confidence=round(conf, 2),
        ))
    return items, notes


def parse_expenses(text: str, ref: date | None = None) -> tuple[list[ParsedItem], list[str], str]:
    """Parse a note into items. Returns (items, notes, engine)."""
    ref = ref or date.today()
    ai = parse_with_ai(text, ref)
    if ai is not None:
        return ai[0], ai[1], "openai"
    items, notes = rules.parse(text, ref)
    return items, notes, "rules"
