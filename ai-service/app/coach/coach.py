"""Zuko AI Financial Coach.

The engine computes the facts (snapshot, pacing, affordability) first; the model only
explains them and recommends actions. If the model is unavailable, a template reply is
built from the same facts.
"""

import json
import re
from typing import Literal

from pydantic import BaseModel

from app.ai_client import structured_call
from app.config import get_settings
from app.insights import engine
from app.parsing import rules
from app.schemas import (
    AffordabilityResponse,
    BreakdownLine,
    CoachAction,
    CoachReply,
    CoachRequest,
    FinancialContext,
    InsightsResponse,
    RiskLevel,
)

SYSTEM_PROMPT = """You are Zuko, a friendly, sharp financial coach for Nigerian university students. Students live on a monthly allowance, side gigs and tight budgets; your job is to help them make the money last until the next allowance without borrowing.

Each user turn comes with a <ledger> block computed by Zuko's engine from the student's verified transactions, budgets and obligations. Treat it as the source of truth:
- Quote only numbers that appear in the ledger, or simple arithmetic on them. Never invent balances, prices, dates or obligations.
- If the student states a different balance than the ledger, gently point out the ledger figure and use it.
- If an <affordability> block is present, base your answer on it: its risk_level, remaining_after, daily_after and suggested_cap.
- If the ledger can't answer the question, say what's missing instead of guessing.

Style: warm, direct, practical. Use ₦ with thousands separators. Keep the reply to 2-4 short sentences; put numbers in `breakdown` rather than repeating them all in prose. Refer to campus realities (cafeteria, keke, data, handouts) where relevant, but don't lecture.

Return:
- reply: the conversational answer.
- breakdown: the key lines of the calculation (label, signed amount, optional note), or an empty list for non-numeric questions.
- risk_level: low | moderate | high | critical when judging a purchase or spending pace, else null.
- recommendation: one concrete next step, or null.
- actions: up to 3 one-tap actions the app can perform. action is one of set_budget, earmark, contribute_goal, log_expense, explain, none. Fill amount/category/target when they apply."""

SPEND_VERBS = re.compile(r"\b(spend|buy|afford|pay|get|deposit|save|put|send|lock|contribute|cost|costs)\b", re.I)
GOAL_VERBS = re.compile(r"\b(deposit|save|lock|contribute|put)\b.*\b(fund|goal|vault|savings)\b", re.I)


class _AIReply(BaseModel):
    reply: str
    breakdown: list[BreakdownLine]
    risk_level: Literal["low", "moderate", "high", "critical"] | None
    recommendation: str | None
    actions: list[CoachAction]


def purchase_amount(question: str) -> float | None:
    """The amount the student is asking about, e.g. ₦4,000 in "Can I spend ₦4,000 on the cinema?"."""
    matches = list(rules.AMOUNT_RE.finditer(question))
    if not matches:
        return None
    if len(matches) > 1:
        # Prefer the amount nearest after a spend verb; students often state their balance first.
        for verb in SPEND_VERBS.finditer(question):
            after = [m for m in matches if 0 <= m.start() - verb.end() <= 40]
            if after:
                return rules._to_amount(after[0])[0]
        return rules._to_amount(matches[-1])[0]
    return rules._to_amount(matches[0])[0]


def _purchase_label(question: str) -> str:
    m = re.search(r"\b(?:on|for|into|to)\s+(?:an?\s+|the\s+|my\s+)?([a-z][a-z \-']{2,40}?)(?:\s+with\b|\s+at\b|[?.!,]|$)", question, re.I)
    return m.group(1).strip() if m else "this purchase"


def _ledger(ctx: FinancialContext, insights: InsightsResponse) -> dict:
    snap = insights.snapshot
    return {
        "student": ctx.user_name,
        "today": snap.today.isoformat(),
        "balance": snap.balance,
        "days_until_next_allowance": snap.days_until_inflow,
        "next_allowance": ctx.next_inflow.model_dump(mode="json") if ctx.next_inflow else None,
        "obligations_due_before_allowance": [
            o.model_dump(mode="json") for o in ctx.obligations if not o.paid
        ],
        "committed_obligations_total": snap.committed_obligations,
        "emergency_cushion": snap.emergency_cushion,
        "uncommitted_cash": snap.discretionary,
        "safe_daily_spend": snap.safe_daily_spend,
        "spent_this_cycle": snap.spent_this_cycle,
        "income_this_cycle": snap.income_this_cycle,
        "category_pacing": [p.model_dump(mode="json") for p in insights.category_pacing],
        "top_categories": insights.top_categories,
        "last_7_days": [d.model_dump(mode="json") for d in insights.weekly_pattern],
        "alerts": [a.model_dump(mode="json") for a in insights.alerts],
        "goals": [g.model_dump(mode="json") for g in ctx.goals],
        "savings_advice": insights.savings_advice.model_dump(mode="json") if insights.savings_advice else None,
        "transaction_count": len(ctx.transactions),
    }


def _grounding(ctx: FinancialContext, insights: InsightsResponse) -> str:
    s = insights.snapshot
    nxt = f", next allowance {ctx.next_inflow.date:%b} {ctx.next_inflow.date.day}" if ctx.next_inflow else ""
    return (f"Verified against ₦{s.balance:,.0f} balance, ₦{s.committed_obligations:,.0f} earmarked obligations"
            f"{nxt}, {len(ctx.transactions)} transactions.")


def _rules_reply(ctx: FinancialContext, insights: InsightsResponse, question: str,
                 afford: AffordabilityResponse | None) -> _AIReply:
    s = insights.snapshot
    q = question.lower()
    if afford:
        actions = []
        asked = afford.uncommitted_before - afford.remaining_after
        if afford.risk_level != "low" and 0 < afford.suggested_cap < asked:
            actions.append(CoachAction(label=f"Set ₦{afford.suggested_cap:,.0f} budget", action="set_budget",
                                       amount=afford.suggested_cap))
        return _AIReply(reply=afford.summary, breakdown=afford.breakdown, risk_level=afford.risk_level,
                        recommendation=None, actions=actions)
    if re.search(r"per day|daily|each day|a day", q):
        return _AIReply(
            reply=(f"You can safely spend about ₦{s.safe_daily_spend:,.0f}/day for the next "
                   f"{s.days_until_inflow} days. That's after setting aside ₦{s.committed_obligations:,.0f} for "
                   f"obligations and a ₦{s.emergency_cushion:,.0f} cushion."),
            breakdown=[
                BreakdownLine(label="Balance", amount=s.balance),
                BreakdownLine(label="Obligations", amount=-s.committed_obligations),
                BreakdownLine(label="Safety cushion", amount=-s.emergency_cushion),
                BreakdownLine(label="Uncommitted", amount=s.discretionary),
            ],
            risk_level=None, recommendation=None, actions=[])
    if re.search(r"where|most|biggest|top", q) and insights.top_categories:
        top = insights.top_categories[0]
        return _AIReply(
            reply=(f"Most of your money this cycle went to {top['label'].lower()}: ₦{top['amount']:,.0f} "
                   f"({top['share_percent']:.0f}% of spending)."),
            breakdown=[BreakdownLine(label=t["label"], amount=-t["amount"], note=f"{t['share_percent']}%")
                       for t in insights.top_categories],
            risk_level=None, recommendation=None, actions=[])
    for p in insights.category_pacing:
        if p.category.value.split("_")[0] in q or p.label.lower().split()[0] in q:
            return _AIReply(
                reply=(f"You've used ₦{p.spent:,.0f} of your ₦{p.limit:,.0f} {p.label.lower()} budget "
                       f"({p.percent_used:.0f}%), spending about ₦{p.daily_pace:,.0f}/day lately."),
                breakdown=[BreakdownLine(label="Spent", amount=-p.spent), BreakdownLine(label="Remaining", amount=p.remaining)],
                risk_level="high" if p.status == "critical" else "moderate" if p.status == "warning" else "low",
                recommendation=None, actions=[])
    alert = insights.alerts[0].message if insights.alerts else "No warnings right now."
    return _AIReply(
        reply=(f"You have ₦{s.balance:,.0f} with {s.days_until_inflow} days until your next allowance, "
               f"about ₦{s.safe_daily_spend:,.0f}/day to spend safely. {alert}"),
        breakdown=[], risk_level=None, recommendation=None, actions=[])


def chat(req: CoachRequest) -> CoachReply:
    ctx = req.context
    insights = engine.build_insights(ctx)
    question = req.messages[-1].content
    amount = purchase_amount(question) if req.messages[-1].role == "user" else None
    afford = engine.affordability(ctx, amount, _purchase_label(question)) if amount else None
    grounding = _grounding(ctx, insights)

    ledger = json.dumps(_ledger(ctx, insights), default=str)
    latest = f"<ledger>\n{ledger}\n</ledger>\n"
    if afford:
        latest += f"<affordability>\n{afford.model_dump_json()}\n</affordability>\n"
    if GOAL_VERBS.search(question) and insights.savings_advice:
        latest += f"<savings_advice>\n{insights.savings_advice.model_dump_json()}\n</savings_advice>\n"
    latest += f"\n{question}"

    history = [{"role": m.role, "content": m.content} for m in req.messages[:-1]]
    # The API requires the conversation to start with a user turn.
    while history and history[0]["role"] != "user":
        history.pop(0)

    ai = structured_call(
        system=SYSTEM_PROMPT,
        messages=history + [{"role": "user", "content": latest}],
        output_model=_AIReply,
        effort=get_settings().coach_effort,
    )
    engine_used: Literal["openai", "rules"] = "openai"
    if ai is None:
        ai = _rules_reply(ctx, insights, question, afford)
        engine_used = "rules"

    risk: RiskLevel | None = ai.risk_level
    if afford and risk is None:
        risk = afford.risk_level
    return CoachReply(
        reply=ai.reply,
        breakdown=ai.breakdown or (afford.breakdown if afford else []),
        risk_level=risk,
        recommendation=ai.recommendation,
        actions=ai.actions[:3],
        grounding=grounding,
        engine=engine_used,
    )
