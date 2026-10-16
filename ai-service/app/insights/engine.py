"""Deterministic financial insight calculations.

Every number the AI coach quotes comes from here, never from the model. That keeps
advice reproducible and auditable (the "Zero Hallucination Protocol" in the design).
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.categories import Category, label
from app.config import get_settings
from app.schemas import (
    AffordabilityResponse,
    Alert,
    BreakdownLine,
    CategoryPacing,
    DailySpend,
    FinancialContext,
    InsightsResponse,
    RiskLevel,
    RunwayImpact,
    SavingsAdvice,
    Snapshot,
    Transaction,
)

PACE_WINDOW_DAYS = 7
VELOCITY_ALERT_RATIO = 1.2  # alert when a category runs 20%+ above its planned daily allocation
DEFAULT_CYCLE_DAYS = 30


def _round(x: float) -> float:
    return float(round(x))


def _floor_to(x: float, step: int) -> float:
    return float(max(0, math.floor(x / step) * step))


def _days(n: float) -> str:
    n = max(1, round(n))
    return f"about {n} day" if n == 1 else f"about {n} days"


def today_of(ctx: FinancialContext) -> date:
    return ctx.today or date.today()


def cycle_bounds(ctx: FinancialContext) -> tuple[date, date]:
    """Start and (exclusive) end of the current allowance cycle."""
    today = today_of(ctx)
    start = ctx.cycle_start or today.replace(day=1)
    if ctx.next_inflow and ctx.next_inflow.date > today:
        end = ctx.next_inflow.date
    else:
        end = start + timedelta(days=DEFAULT_CYCLE_DAYS)
        if end <= today:
            end = today + timedelta(days=1)
    return start, end


def days_until_inflow(ctx: FinancialContext) -> int:
    _, end = cycle_bounds(ctx)
    return max(1, (end - today_of(ctx)).days)


def _in_cycle(ctx: FinancialContext) -> list[Transaction]:
    start, _ = cycle_bounds(ctx)
    today = today_of(ctx)
    return [t for t in ctx.transactions if start <= t.date <= today]


def committed_obligations(ctx: FinancialContext) -> float:
    _, end = cycle_bounds(ctx)
    return sum(o.amount for o in ctx.obligations if not o.paid and o.due_date <= end)


def cushion(ctx: FinancialContext) -> float:
    return ctx.emergency_cushion if ctx.emergency_cushion is not None else get_settings().default_cushion


def snapshot(ctx: FinancialContext) -> Snapshot:
    today = today_of(ctx)
    days = days_until_inflow(ctx)
    committed = committed_obligations(ctx)
    cush = cushion(ctx)
    discretionary = ctx.balance - committed - cush
    txs = _in_cycle(ctx)
    spent = sum(t.amount for t in txs if t.direction == "debit")
    income = sum(t.amount for t in txs if t.direction == "credit")
    total_budget = sum(b.limit for b in ctx.budgets)
    return Snapshot(
        today=today,
        balance=_round(ctx.balance),
        days_until_inflow=days,
        committed_obligations=_round(committed),
        emergency_cushion=_round(cush),
        discretionary=_round(discretionary),
        safe_daily_spend=_round(max(0.0, discretionary) / days),
        spent_this_cycle=_round(spent),
        income_this_cycle=_round(income),
        net_burn=_round(spent - income),
        total_budget=_round(total_budget),
        budget_used_percent=round(spent / total_budget * 100, 1) if total_budget else None,
    )


def daily_spend(ctx: FinancialContext, days: int = PACE_WINDOW_DAYS) -> list[DailySpend]:
    today = today_of(ctx)
    totals: dict[date, float] = defaultdict(float)
    for t in ctx.transactions:
        if t.direction == "debit":
            totals[t.date] += t.amount
    return [
        DailySpend(date=d, amount=_round(totals.get(d, 0.0)))
        for d in (today - timedelta(days=i) for i in range(days - 1, -1, -1))
    ]


def category_pacing(ctx: FinancialContext) -> list[CategoryPacing]:
    today = today_of(ctx)
    window_start = today - timedelta(days=PACE_WINDOW_DAYS - 1)
    cycle_spend: dict[Category, float] = defaultdict(float)
    window_spend: dict[Category, float] = defaultdict(float)
    for t in _in_cycle(ctx):
        if t.direction != "debit":
            continue
        cycle_spend[t.category] += t.amount
        if t.date >= window_start:
            window_spend[t.category] += t.amount

    out: list[CategoryPacing] = []
    for b in ctx.budgets:
        spent = cycle_spend.get(b.category, 0.0)
        remaining = max(0.0, b.limit - spent)
        pct = (spent / b.limit * 100) if b.limit else 0.0
        pace = window_spend.get(b.category, 0.0) / PACE_WINDOW_DAYS
        days_to_exhaust = round(remaining / pace, 1) if pace > 0 else None
        days_left = days_until_inflow(ctx)

        if spent == 0:
            status = "untouched"
        elif pct >= 100 or (days_to_exhaust is not None and days_to_exhaust < days_left * 0.5):
            status = "critical"
        elif pct >= 85 or (days_to_exhaust is not None and days_to_exhaust < days_left):
            status = "warning"
        elif pct >= 50:
            status = "on_track"
        else:
            status = "healthy"

        out.append(CategoryPacing(
            category=b.category, label=label(b.category), spent=_round(spent), limit=_round(b.limit),
            remaining=_round(remaining), percent_used=round(pct, 1), daily_pace=_round(pace),
            days_to_exhaust=days_to_exhaust, status=status,
        ))
    return out


def top_categories(ctx: FinancialContext, n: int = 5) -> list[dict]:
    totals: dict[Category, float] = defaultdict(float)
    for t in _in_cycle(ctx):
        if t.direction == "debit":
            totals[t.category] += t.amount
    total = sum(totals.values()) or 1.0
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return [
        {"category": c.value, "label": label(c), "amount": _round(a), "share_percent": round(a / total * 100, 1)}
        for c, a in ranked
    ]


def alerts(ctx: FinancialContext, snap: Snapshot, pacing: list[CategoryPacing]) -> list[Alert]:
    out: list[Alert] = []
    days_left = snap.days_until_inflow
    start, end = cycle_bounds(ctx)
    cycle_days = max(1, (end - start).days)
    floor = get_settings().min_daily_subsistence

    untouched = sorted((p for p in pacing if p.status in ("untouched", "healthy")), key=lambda p: -p.remaining)

    # Velocity: a category's recent daily pace vs. its planned daily allocation.
    for p in pacing:
        planned = p.limit / cycle_days if p.limit else 0
        if planned and p.daily_pace > planned * VELOCITY_ALERT_RATIO:
            over = (p.daily_pace / planned - 1) * 100
            message = (f"You've averaged ₦{p.daily_pace:,.0f}/day on {p.label.lower()} over the last "
                       f"{PACE_WINDOW_DAYS} days, {over:.0f}% above the ₦{planned:,.0f}/day your budget allows.")
            if p.remaining <= 0:
                message += f" The ₦{p.limit:,.0f} budget is already used up."
            elif p.days_to_exhaust is not None and p.days_to_exhaust < days_left:
                message += (f" At this pace it runs out in {_days(p.days_to_exhaust)}, "
                            f"{_days(days_left - p.days_to_exhaust)} before your next allowance.")
            target = _floor_to(p.remaining / days_left, 50) if days_left else 0
            if target >= 200:
                action = f"Cap {p.label.lower()} at ₦{target:,.0f}/day"
            elif untouched and untouched[0].category != p.category:
                donor = untouched[0]
                action = f"Move ₦{_floor_to(donor.remaining / 2, 500):,.0f} from {donor.label.lower()}"
            else:
                action = f"Pause non-essential {p.label.lower()} spending"
            out.append(Alert(
                kind="velocity", severity="critical" if p.status == "critical" else "warning",
                title=f"Your {p.label.lower()} spending is speeding up",
                message=message, category=p.category, suggested_action=action,
            ))
        elif p.percent_used >= 100:
            out.append(Alert(
                kind="budget", severity="critical", title=f"{p.label} budget exhausted",
                message=f"You've spent ₦{p.spent:,.0f} of a ₦{p.limit:,.0f} ceiling.",
                category=p.category, suggested_action="Reallocate from an untouched category",
            ))

    # Runway: not enough uncommitted cash to reach the next inflow at subsistence level.
    if snap.discretionary < 0:
        out.append(Alert(
            kind="runway", severity="critical", title="Commitments exceed your cash",
            message=(f"Upcoming obligations (₦{snap.committed_obligations:,.0f}) plus your safety cushion "
                     f"(₦{snap.emergency_cushion:,.0f}) are more than your ₦{snap.balance:,.0f} balance."),
            suggested_action="Pause non-essential spending and review obligations",
        ))
    elif snap.safe_daily_spend < floor:
        out.append(Alert(
            kind="subsistence", severity="warning", title="Daily runway below your survival floor",
            message=(f"You can safely spend ₦{snap.safe_daily_spend:,.0f}/day for {days_left} days, below the "
                     f"₦{floor:,.0f}/day minimum for meals and transport."),
            suggested_action="Cut leisure spending and lean on cheaper meal options",
        ))

    # Obligations due soon that are not yet earmarked.
    today = snap.today
    for o in ctx.obligations:
        if not o.paid and not o.earmarked and 0 <= (o.due_date - today).days <= 7:
            out.append(Alert(
                kind="obligation", severity="info", title=f"{o.name} due in {(o.due_date - today).days} days",
                message=f"₦{o.amount:,.0f} isn't earmarked yet. Locking it now keeps it out of daily spending.",
                suggested_action=f"Earmark ₦{o.amount:,.0f}",
            ))

    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda a: order[a.severity])


def savings_advice(ctx: FinancialContext, snap: Snapshot) -> SavingsAdvice | None:
    active = [g for g in ctx.goals if not g.paused and g.saved < g.target]
    if not active:
        return None
    if snap.discretionary <= 0:
        return SavingsAdvice(max_goal_contribution=0, keep_flexible=0,
                             message="Hold off on goal contributions until your next allowance lands.")
    needed = sum(g.target - g.saved for g in active)
    # Lock at most a third of discretionary cash; the rest stays flexible for surprises.
    max_lock = min(needed, _floor_to(snap.discretionary / 3, 500))
    keep = snap.discretionary - max_lock
    return SavingsAdvice(
        max_goal_contribution=max_lock,
        keep_flexible=_round(keep),
        message=(f"Lock no more than ₦{max_lock:,.0f} into goals before your next allowance, and keep "
                 f"₦{keep:,.0f} flexible for practicals, printing and emergencies."),
    )


def build_insights(ctx: FinancialContext) -> InsightsResponse:
    snap = snapshot(ctx)
    pacing = category_pacing(ctx)
    start, end = cycle_bounds(ctx)
    ceiling = _round(sum(b.limit for b in ctx.budgets) / max(1, (end - start).days)) if ctx.budgets else snap.safe_daily_spend
    return InsightsResponse(
        snapshot=snap,
        alerts=alerts(ctx, snap, pacing),
        category_pacing=pacing,
        weekly_pattern=daily_spend(ctx),
        safe_daily_ceiling=ceiling,
        top_categories=top_categories(ctx),
        savings_advice=savings_advice(ctx, snap),
        generated_at=datetime.now(timezone.utc),
    )


def affordability(ctx: FinancialContext, amount: float, what: str = "this purchase") -> AffordabilityResponse:
    snap = snapshot(ctx)
    days = snap.days_until_inflow
    uncommitted = snap.discretionary
    after = uncommitted - amount
    daily_before = max(0.0, uncommitted) / days
    daily_after = max(0.0, after) / days
    pct = (amount / uncommitted * 100) if uncommitted > 0 else 100.0
    floor = get_settings().min_daily_subsistence

    risk: RiskLevel
    if after < 0:
        risk = "critical"
    elif pct >= 75 or daily_after < floor * 0.5:
        risk = "high"
    elif pct >= 40 or daily_after < floor:
        risk = "moderate"
    else:
        risk = "low"

    # A cap that keeps half of uncommitted cash as a buffer and, where possible, the daily
    # spend at or above the subsistence floor.
    keeps_floor = uncommitted - floor * days
    cap = min(uncommitted / 2, keeps_floor) if keeps_floor > 0 else uncommitted / 2
    suggested = min(amount, _floor_to(cap, 100)) if uncommitted > 0 else 0.0
    cap_note = (f" Capping it at ₦{suggested:,.0f} keeps a healthier buffer." if 0 < suggested < amount else "")

    breakdown = [
        BreakdownLine(label="Available balance", amount=snap.balance),
        BreakdownLine(label="Obligations due before next allowance", amount=-snap.committed_obligations,
                      note=", ".join(o.name for o in ctx.obligations if not o.paid) or None),
        BreakdownLine(label="Emergency safety cushion", amount=-snap.emergency_cushion,
                      note="Reserve for emergency transport or medical"),
        BreakdownLine(label="True uncommitted cash", amount=_round(uncommitted)),
        BreakdownLine(label=what.capitalize(), amount=-_round(amount)),
        BreakdownLine(label="Left after purchase", amount=_round(after)),
    ]

    if after < 0:
        summary = (f"No. {what.capitalize()} (₦{amount:,.0f}) is more than your ₦{max(0, uncommitted):,.0f} of "
                   f"uncommitted cash. It would eat into money set aside for obligations or emergencies.")
    elif risk in ("high", "moderate"):
        summary = (f"You can, but it's tight: you'd have ₦{after:,.0f} left for {days} days "
                   f"(₦{daily_after:,.0f}/day, down from ₦{daily_before:,.0f}/day).{cap_note}")
    else:
        summary = (f"Yes. After ₦{amount:,.0f} you'd still have ₦{after:,.0f} uncommitted "
                   f"(₦{daily_after:,.0f}/day for {days} days).")

    return AffordabilityResponse(
        affordable=after >= 0, risk_level=risk, breakdown=breakdown,
        uncommitted_before=_round(uncommitted), remaining_after=_round(after), days_until_inflow=days,
        daily_after=_round(daily_after), daily_before=_round(daily_before),
        percent_of_uncommitted=round(pct, 1), suggested_cap=suggested, summary=summary,
    )


def runway_impact(ctx: FinancialContext, new_debits: float, new_credits: float = 0.0) -> RunwayImpact:
    """How logging a set of parsed expenses changes the safe daily spend."""
    before = snapshot(ctx)
    after_ctx = ctx.model_copy(update={"balance": ctx.balance - new_debits + new_credits})
    after = snapshot(after_ctx)
    floor = get_settings().min_daily_subsistence
    above = after.safe_daily_spend >= floor
    diff = after.safe_daily_spend - floor
    message = (f"Safe threshold maintained. You remain ₦{diff:,.0f}/day above your ₦{floor:,.0f}/day subsistence buffer."
               if above else
               f"Heads up: this drops you ₦{-diff:,.0f}/day below your ₦{floor:,.0f}/day subsistence buffer.")
    return RunwayImpact(
        days_left=after.days_until_inflow, balance_before=before.balance, balance_after=after.balance,
        safe_daily_before=before.safe_daily_spend, safe_daily_after=after.safe_daily_spend,
        subsistence_floor=floor, above_floor=above, message=message,
    )
