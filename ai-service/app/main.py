"""Zuko AI service: expense parsing, financial insights, AI coach and BMONI sandbox integration.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import hmac
import logging
from datetime import date, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.ai_client import get_client
from app.bmoni.client import BmoniClient, BmoniError
from app.coach.coach import chat
from app.config import get_settings
from app.insights import engine
from app.parsing.ai import parse_expenses
from app.schemas import (
    AffordabilityRequest,
    AffordabilityResponse,
    Budget,
    CoachReply,
    CoachRequest,
    FinancialContext,
    Goal,
    Inflow,
    InsightsResponse,
    Obligation,
    ParseRequest,
    ParseResponse,
    Transaction,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
app = FastAPI(
    title="Zuko AI Service",
    version="1.0.0",
    description="AI expense parsing, financial insights, coach and BMONI sandbox integration for Zuko.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Service-Key"],
)


def require_service_key(x_service_key: str | None = Header(default=None)) -> None:
    """The Node backend authenticates with a shared secret. Disabled when ZUKO_SERVICE_KEY is empty."""
    expected = get_settings().service_key
    if expected and not (x_service_key and hmac.compare_digest(x_service_key, expected)):
        raise HTTPException(401, "Invalid or missing X-Service-Key")


api = Depends(require_service_key)


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "Zuko AI Service",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "api_contract": "https://github.com/abasiono23/ZuKo/blob/main/ai-service/docs/API.md",
    }


@app.get("/health")
def health():
    s = get_settings()
    return {
        "status": "ok",
        "ai": {"enabled": get_client() is not None, "provider": "openai", "model": s.ai_model},
        "bmoni": {"mode": s.bmoni_mode, "base_url_configured": bool(s.bmoni_base_url)},
    }


# ---------- Expense parsing ----------

@app.post("/v1/expenses/parse", response_model=ParseResponse, dependencies=[api])
def parse(req: ParseRequest) -> ParseResponse:
    ref = req.reference_date or (req.context.today if req.context and req.context.today else date.today())
    items, notes, engine_used = parse_expenses(req.text, ref)
    debit = sum(i.amount for i in items if i.direction == "debit")
    credit = sum(i.amount for i in items if i.direction == "credit")
    impact = engine.runway_impact(req.context, debit, credit) if req.context and items else None
    return ParseResponse(items=items, total_debit=debit, total_credit=credit, engine=engine_used,
                         notes=notes, runway_impact=impact)


# ---------- Insights ----------

@app.post("/v1/insights", response_model=InsightsResponse, dependencies=[api])
def insights(ctx: FinancialContext) -> InsightsResponse:
    return engine.build_insights(ctx)


@app.post("/v1/insights/affordability", response_model=AffordabilityResponse, dependencies=[api])
def affordability(req: AffordabilityRequest) -> AffordabilityResponse:
    return engine.affordability(req.context, req.amount, req.label)


# ---------- Coach ----------

@app.post("/v1/coach/chat", response_model=CoachReply, dependencies=[api])
def coach(req: CoachRequest) -> CoachReply:
    return chat(req)


# ---------- BMONI ----------
# BMONI scopes everything by user: /v1/bmoni/users/{user_id}/... where user_id is the student's
# BMONI user id (stored in Supabase). Use "default" to fall back to BMONI_USER_ID.

def _bmoni_error(exc: BmoniError) -> HTTPException:
    status = 502 if exc.status_code is None or exc.status_code >= 500 else exc.status_code
    return HTTPException(status, {"message": str(exc), "upstream_status": exc.status_code, "upstream_body": exc.body})


def _uid(user_id: str) -> str | None:
    return None if user_id == "default" else user_id


@app.get("/v1/bmoni/health", dependencies=[api])
async def bmoni_health():
    try:
        async with BmoniClient() as c:
            return {"mode": get_settings().bmoni_mode, "upstream": await c.health()}
    except BmoniError as exc:
        raise _bmoni_error(exc)


@app.get("/v1/bmoni/users/{user_id}/wallets", dependencies=[api])
async def bmoni_wallets(user_id: str):
    try:
        async with BmoniClient() as c:
            return {"mode": get_settings().bmoni_mode, "wallets": await c.wallets(_uid(user_id))}
    except BmoniError as exc:
        raise _bmoni_error(exc)


@app.get("/v1/bmoni/users/{user_id}/wallets/{wallet_id}/balance", dependencies=[api])
async def bmoni_balance(user_id: str, wallet_id: str):
    try:
        async with BmoniClient() as c:
            return await c.balance(wallet_id, _uid(user_id))
    except BmoniError as exc:
        raise _bmoni_error(exc)


@app.get("/v1/bmoni/users/{user_id}/wallets/{wallet_id}/transactions", response_model=list[Transaction],
         dependencies=[api])
async def bmoni_transactions(user_id: str, wallet_id: str, start: date | None = None, end: date | None = None):
    try:
        async with BmoniClient() as c:
            return await c.transactions(wallet_id, _uid(user_id), start, end)
    except BmoniError as exc:
        raise _bmoni_error(exc)


class BmoniContextRequest(BaseModel):
    """Student settings stored in Supabase, combined with live BMONI wallet data."""

    user_id: str | None = None  # BMONI user id; default BMONI_USER_ID
    wallet_ids: list[str] | None = None  # default: every active naira (CNGN) wallet
    user_name: str | None = None
    today: date | None = None
    cash_in_pocket: float = 0
    manual_transactions: list[Transaction] = []
    budgets: list[Budget] = []
    obligations: list[Obligation] = []
    next_inflow: Inflow | None = None
    goals: list[Goal] = []
    cycle_start: date | None = None
    emergency_cushion: float | None = None
    lookback_days: int = 45


async def _context_from_bmoni(req: BmoniContextRequest) -> tuple[FinancialContext, dict]:
    today = req.today or date.today()
    async with BmoniClient() as c:
        wallet_ids = req.wallet_ids or await c.naira_wallet_ids(req.user_id)
        balances, txs = {}, []
        for wid in wallet_ids:
            balances[wid] = (await c.balance(wid, req.user_id))["balance"] or 0.0
            txs.extend(await c.transactions(wid, req.user_id, today - timedelta(days=req.lookback_days), today))
    ctx = FinancialContext(
        user_name=req.user_name, today=today,
        balance=sum(balances.values()) + req.cash_in_pocket,
        transactions=sorted(txs + req.manual_transactions, key=lambda t: t.date),
        budgets=req.budgets, obligations=req.obligations, next_inflow=req.next_inflow, goals=req.goals,
        cycle_start=req.cycle_start, emergency_cushion=req.emergency_cushion,
    )
    return ctx, {"wallet_balances": balances, "bmoni_transactions": len(txs),
                 "manual_transactions": len(req.manual_transactions)}


@app.post("/v1/bmoni/context", dependencies=[api])
async def bmoni_context(req: BmoniContextRequest):
    """Build a FinancialContext from BMONI wallets + the student's saved settings."""
    try:
        ctx, meta = await _context_from_bmoni(req)
    except BmoniError as exc:
        raise _bmoni_error(exc)
    return {"context": ctx.model_dump(mode="json"), "sync": meta}


@app.post("/v1/bmoni/insights", dependencies=[api])
async def bmoni_insights(req: BmoniContextRequest):
    """One call for the dashboard: pull BMONI data, then compute insights on it."""
    try:
        ctx, meta = await _context_from_bmoni(req)
    except BmoniError as exc:
        raise _bmoni_error(exc)
    return {"insights": engine.build_insights(ctx).model_dump(mode="json"), "sync": meta}
