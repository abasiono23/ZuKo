"""Request / response contracts shared with the Node.js backend and the frontend.

All money values are Nigerian Naira (NGN) as plain numbers. Amounts are always
positive; `direction` says whether money left (debit) or arrived (credit).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.categories import Category

Direction = Literal["debit", "credit"]
RiskLevel = Literal["low", "moderate", "high", "critical"]


# ---------- Core data ----------

class Transaction(BaseModel):
    id: str | None = None
    amount: float = Field(gt=0)
    direction: Direction = "debit"
    category: Category = Category.OTHER
    merchant: str | None = None
    description: str | None = None
    date: date
    source: str = "manual"  # manual | bmoni | kuda_sync | ...
    payment_method: str | None = None


class Budget(BaseModel):
    category: Category
    limit: float = Field(ge=0)


class Obligation(BaseModel):
    name: str
    amount: float = Field(gt=0)
    due_date: date
    earmarked: bool = False
    paid: bool = False


class Inflow(BaseModel):
    amount: float = Field(ge=0)
    date: date
    source: str | None = None


class Goal(BaseModel):
    name: str
    target: float = Field(gt=0)
    saved: float = Field(ge=0, default=0)
    due_date: date | None = None
    paused: bool = False


class FinancialContext(BaseModel):
    """Everything the insight engine needs. The Node backend builds this from Supabase."""

    user_name: str | None = None
    today: date | None = None  # defaults to server date; set it for reproducible demos
    balance: float = Field(description="Liquid cash across linked wallets + cash in pocket")
    transactions: list[Transaction] = []
    budgets: list[Budget] = []
    obligations: list[Obligation] = []
    next_inflow: Inflow | None = None
    goals: list[Goal] = []
    cycle_start: date | None = None  # start of the current allowance cycle; defaults to 1st of month
    emergency_cushion: float | None = None


# ---------- Expense parsing ----------

class ParsedItem(BaseModel):
    amount: float
    direction: Direction = "debit"
    category: Category
    category_label: str
    merchant: str | None = None
    description: str
    date: date
    payment_method: str | None = None
    confidence: float = Field(ge=0, le=1)


class RunwayImpact(BaseModel):
    days_left: int
    balance_before: float
    balance_after: float
    safe_daily_before: float
    safe_daily_after: float
    subsistence_floor: float
    above_floor: bool
    message: str


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    reference_date: date | None = None
    context: FinancialContext | None = None  # when given, the response includes a runway impact preview


class ParseResponse(BaseModel):
    items: list[ParsedItem]
    total_debit: float
    total_credit: float
    engine: Literal["openai", "rules"]
    notes: list[str] = []
    runway_impact: RunwayImpact | None = None


# ---------- Insights ----------

class CategoryPacing(BaseModel):
    category: Category
    label: str
    spent: float
    limit: float
    remaining: float
    percent_used: float
    daily_pace: float  # average spend per day over the last 7 days
    days_to_exhaust: float | None  # at the current pace; None if pace is zero
    status: Literal["healthy", "on_track", "warning", "critical", "untouched"]


class DailySpend(BaseModel):
    date: date
    amount: float


class Alert(BaseModel):
    kind: Literal["velocity", "budget", "runway", "obligation", "subsistence"]
    severity: Literal["info", "warning", "critical"]
    title: str
    message: str
    category: Category | None = None
    suggested_action: str | None = None


class Snapshot(BaseModel):
    today: date
    balance: float
    days_until_inflow: int
    committed_obligations: float  # unpaid obligations due before the next inflow
    emergency_cushion: float
    discretionary: float  # balance - committed - cushion
    safe_daily_spend: float
    spent_this_cycle: float
    income_this_cycle: float
    net_burn: float
    total_budget: float
    budget_used_percent: float | None


class SavingsAdvice(BaseModel):
    max_goal_contribution: float
    keep_flexible: float
    message: str


class InsightsResponse(BaseModel):
    snapshot: Snapshot
    alerts: list[Alert]
    category_pacing: list[CategoryPacing]
    weekly_pattern: list[DailySpend]
    safe_daily_ceiling: float
    top_categories: list[dict]
    savings_advice: SavingsAdvice | None
    generated_at: datetime


class AffordabilityRequest(BaseModel):
    context: FinancialContext
    amount: float = Field(gt=0)
    label: str = "this purchase"


class BreakdownLine(BaseModel):
    label: str
    amount: float
    note: str | None = None


class AffordabilityResponse(BaseModel):
    affordable: bool
    risk_level: RiskLevel
    breakdown: list[BreakdownLine]
    uncommitted_before: float
    remaining_after: float
    days_until_inflow: int
    daily_after: float
    daily_before: float
    percent_of_uncommitted: float
    suggested_cap: float
    summary: str


# ---------- Coach ----------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class CoachRequest(BaseModel):
    context: FinancialContext
    messages: list[ChatMessage] = Field(min_length=1)


class CoachAction(BaseModel):
    label: str
    action: Literal["set_budget", "earmark", "contribute_goal", "log_expense", "explain", "none"]
    amount: float | None = None
    category: Category | None = None
    target: str | None = None


class CoachReply(BaseModel):
    reply: str
    breakdown: list[BreakdownLine] = []
    risk_level: RiskLevel | None = None
    recommendation: str | None = None
    actions: list[CoachAction] = []
    grounding: str
    engine: Literal["openai", "rules"]
