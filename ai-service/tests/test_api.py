from fastapi.testclient import TestClient

from app.bmoni import normalize
from app.coach.coach import purchase_amount
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["bmoni"]["mode"] == "mock"


def test_parse_with_runway_impact(ctx_dict):
    r = client.post("/v1/expenses/parse", json={
        "text": "I spent ₦2,000 on lunch at Moremi cafeteria and ₦1,500 on Keke transport today",
        "context": ctx_dict,
    })
    body = r.json()
    assert r.status_code == 200, body
    assert body["engine"] == "rules" and body["total_debit"] == 3500
    assert body["runway_impact"]["balance_after"] == 25000


def test_insights_endpoint(ctx_dict):
    r = client.post("/v1/insights", json=ctx_dict)
    assert r.status_code == 200
    assert r.json()["snapshot"]["safe_daily_spend"] > 0


def test_coach_affordability_offline(ctx_dict):
    r = client.post("/v1/coach/chat", json={
        "context": ctx_dict,
        "messages": [{"role": "user", "content": "I have ₦15,000 left. Can I spend ₦4,000 on an outing with friends?"}],
    })
    body = r.json()
    assert r.status_code == 200, body
    assert body["engine"] == "rules" and body["risk_level"] in ("low", "moderate", "high")
    assert any(line["amount"] == -4000 for line in body["breakdown"])
    assert "28,500" in body["grounding"]


def test_purchase_amount_prefers_spend_verb():
    assert purchase_amount("I have ₦15,000 left. Can I spend ₦4,000 on the cinema?") == 4000
    assert purchase_amount("Deposit ₦5,000 into Laptop fund?") == 5000
    assert purchase_amount("Where did my money go?") is None


def test_bmoni_mock_flow():
    wallets = client.get("/v1/bmoni/users/default/wallets").json()["wallets"]
    assert {w["currency"] for w in wallets} == {"CNGN", "USDB"}
    bal = client.get("/v1/bmoni/users/default/wallets/sw_cngn_001/balance").json()
    assert bal == {"wallet_id": "sw_cngn_001", "currency": "CNGN", "balance": 24500}
    txs = client.get("/v1/bmoni/users/default/wallets/sw_cngn_001/transactions").json()
    assert txs and all(t["source"] == "bmoni" for t in txs)
    assert not any(t["id"] == "txn_failed" for t in txs)  # failed transfers are dropped
    assert {t["category"] for t in txs} >= {"food", "transport", "income", "data_airtime"}


def test_bmoni_insights(ctx_dict):
    r = client.post("/v1/bmoni/insights", json={
        "cash_in_pocket": 4000, "budgets": ctx_dict["budgets"], "obligations": [],
    })
    body = r.json()
    assert r.status_code == 200, body
    assert body["sync"]["wallet_balances"] == {"sw_cngn_001": 24500}  # only the naira (CNGN) wallet
    assert body["insights"]["snapshot"]["balance"] == 28500


def test_bmoni_unknown_wallet_is_404():
    assert client.get("/v1/bmoni/users/default/wallets/nope/balance").status_code == 404


def test_bmoni_unknown_user_is_404():
    assert client.get("/v1/bmoni/users/someone-else/wallets").status_code == 404


def test_normalizer_real_bmoni_shape():
    """Shape from the BMONI Embedded API spec: GET /v1/users/{userId}/transactions/{smartWalletId}."""
    raw = {"transactions": [
        {"id": "t1", "direction": "outgoing", "delta": "-1800.00", "amount": "1800.00", "currency": "CNGN",
         "status": "completed", "counterpartyName": "Mama Cass Cafeteria", "purpose": "Lunch",
         "note": None, "createdAt": "2026-10-16T13:00:00.000Z", "narrationType": "send_to_bank"},
        {"id": "t2", "direction": "incoming", "delta": "30000.00", "amount": "30000.00", "currency": "CNGN",
         "status": "completed", "counterpartyName": "Dad", "createdAt": "2026-10-10T09:00:00.000Z",
         "narrationType": "fund_bank"},
        {"id": "t3", "direction": "outgoing", "amount": "50.00", "status": "completed",
         "createdAt": "2026-10-10T09:00:00.000Z", "narrationType": "service_fee"},
        {"id": "t4", "direction": "outgoing", "amount": "500.00", "status": "failed",
         "createdAt": "2026-10-10T09:00:00.000Z", "narrationType": "send_to_bank"},
        {"id": "t5", "direction": "outgoing", "amount": "10.00", "status": "completed",
         "createdAt": "2026-10-10T09:00:00.000Z", "narrationType": "swap_between_wallets"},
    ], "count": 5}
    txs = normalize.to_transactions(raw)
    assert [(t.id, t.amount, t.direction, t.category.value) for t in txs] == [
        ("t1", 1800, "debit", "food"), ("t2", 30000, "credit", "income"), ("t3", 50, "debit", "other")]
    assert txs[0].merchant == "Mama Cass Cafeteria" and txs[2].description == "Service fee"


def test_normalizer_handles_kobo_and_drcr(monkeypatch):
    from dataclasses import replace

    from app.config import get_settings
    kobo = replace(get_settings(), bmoni_amount_unit="kobo")
    monkeypatch.setattr(normalize, "get_settings", lambda: kobo)
    raw = {"status": True, "data": {"records": [
        {"reference": "R1", "amountInKobo": 150000, "drCr": "DR", "remarks": "Keke to Yaba", "transactionDate": "24/10/2024"},
        {"reference": "R2", "amount": "3,000,000", "drCr": "CR", "remarks": "Allowance", "transactionDate": 1729728000},
    ]}}
    txs = normalize.to_transactions(raw)
    assert [(t.amount, t.direction, t.category.value) for t in txs] == [
        (1500, "debit", "transport"), (30000, "credit", "income")]
