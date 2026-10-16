"""Turn BMONI sandbox payloads into Zuko transactions.

BMONI's sandbox docs aren't public, so this accepts the common shapes Nigerian
fintech APIs use (`{"status", "message", "data"}` envelopes, kobo or naira amounts,
DR/CR flags or signed amounts, several date/narration field names). Once the real
schema is confirmed, tighten the field lists below.
"""

from datetime import date, datetime
from typing import Any

from app.categories import Category, categorize
from app.config import get_settings
from app.schemas import Transaction

LIST_KEYS = ("items", "transactions", "records", "results", "content", "rows", "wallets", "accounts", "data")
AMOUNT_KEYS = ("amount", "value", "transactionAmount", "transaction_amount", "amountInKobo", "amount_in_kobo")
DIRECTION_KEYS = ("direction", "type", "transactionType", "transaction_type", "drCr", "dr_cr", "entryType", "entry_type")
DATE_KEYS = ("createdAt", "created_at", "transactionDate", "transaction_date", "date", "valueDate", "value_date", "timestamp", "paidAt", "paid_at")
NARRATION_KEYS = ("note", "purpose", "narration", "description", "remark", "remarks", "memo", "details")
MERCHANT_KEYS = ("counterpartyName", "merchant", "merchantName", "merchant_name", "counterparty", "beneficiaryName", "beneficiary_name", "recipientName", "senderName", "sender_name")
ID_KEYS = ("id", "reference", "transactionReference", "transaction_reference", "ref", "txRef", "tx_ref")
BALANCE_KEYS = ("availableBalance", "available_balance", "balance", "ledgerBalance", "ledger_balance", "amount")

DEBIT_WORDS = {"debit", "dr", "d", "withdrawal", "outflow", "out", "outgoing", "payment", "transfer_out", "purchase", "charge", "card_payment"}
CREDIT_WORDS = {"credit", "cr", "c", "deposit", "inflow", "in", "incoming", "transfer_in", "funding", "refund", "reversal"}

# BMONI transaction statuses that never moved money.
SKIP_STATUSES = {"failed", "cancelled", "canceled", "expired", "rejected"}
# BMONI narration types that are moves between the user's own wallets, not spending or income.
INTERNAL_NARRATIONS = {"swap_between_wallets", "fund_card", "send_to_card"}
FEE_NARRATIONS = {"service_fee", "card_transaction_charge", "card_monthly_maintenance", "card_pin_change_fee",
                  "stamp_duty_naira", "card_issuing"}


def unwrap(payload: Any) -> Any:
    """Strip `{"status", "data": ...}` envelopes."""
    while isinstance(payload, dict) and "data" in payload and len(payload) <= 6:
        payload = payload["data"]
    return payload


def as_list(payload: Any) -> list[dict]:
    payload = unwrap(payload)
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in LIST_KEYS:
            if isinstance(payload.get(key), list):
                return [p for p in payload[key] if isinstance(p, dict)]
        return [payload]
    return []


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _money(raw: Any, unit: str) -> float | None:
    if isinstance(raw, dict):  # {"amount": 1500, "currency": "NGN"}
        raw = _first(raw, ("amount", "value"))
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value / 100 if unit == "kobo" else value


def _date(raw: Any) -> date:
    if isinstance(raw, (int, float)):  # epoch seconds or ms
        return datetime.fromtimestamp(raw / 1000 if raw > 1e11 else raw).date()
    if isinstance(raw, str):
        text = raw.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y"):
                try:
                    return datetime.strptime(text[:11].strip(), fmt).date()
                except ValueError:
                    continue
    return date.today()


def balance_of(payload: Any) -> float | None:
    data = unwrap(payload)
    if isinstance(data, list):
        values = [balance_of(d) for d in data]
        return sum(v for v in values if v is not None) if any(v is not None for v in values) else None
    if not isinstance(data, dict):
        return None
    amount_unit = get_settings().bmoni_amount_unit
    if "balance" in data and isinstance(data["balance"], dict):
        return balance_of(data["balance"])
    return _money(_first(data, BALANCE_KEYS), amount_unit)


def to_transaction(raw: dict) -> Transaction | None:
    if str(raw.get("status", "")).lower() in SKIP_STATUSES:
        return None
    narration_type = str(raw.get("narrationType") or "").lower()
    if narration_type in INTERNAL_NARRATIONS:
        return None

    unit = get_settings().bmoni_amount_unit
    amount = _money(_first(raw, AMOUNT_KEYS), unit)
    if amount is None or amount == 0:
        return None
    delta = _money(raw.get("delta"), unit)

    flag = str(_first(raw, DIRECTION_KEYS) or "").strip().lower()
    if flag in CREDIT_WORDS or flag.startswith("credit"):
        direction = "credit"
    elif flag in DEBIT_WORDS or flag.startswith("debit"):
        direction = "debit"
    elif (delta if delta is not None else amount) < 0:
        direction = "debit"
    elif delta is not None and delta > 0:
        direction = "credit"
    else:
        direction = "credit" if raw.get("isCredit") or raw.get("is_credit") else "debit"

    narration = str(_first(raw, NARRATION_KEYS) or "")
    merchant = _first(raw, MERCHANT_KEYS)
    if isinstance(merchant, dict):
        merchant = _first(merchant, ("name", "displayName", "accountName"))
    if not narration and narration_type:
        narration = narration_type.replace("_", " ").capitalize()
    text = f"{narration} {merchant or ''}"
    if direction == "credit":
        category = Category.INCOME
    elif narration_type in FEE_NARRATIONS:
        category = Category.OTHER
        narration = narration or "BMONI fee"
    else:
        category = categorize(text)

    return Transaction(
        id=str(_first(raw, ID_KEYS)) if _first(raw, ID_KEYS) is not None else None,
        amount=abs(amount),
        direction=direction,
        category=category,
        merchant=str(merchant) if merchant else None,
        description=narration or None,
        date=_date(_first(raw, DATE_KEYS)),
        source="bmoni",
        payment_method="bmoni",
    )


def to_transactions(payload: Any) -> list[Transaction]:
    return [t for t in (to_transaction(r) for r in as_list(payload)) if t is not None]
