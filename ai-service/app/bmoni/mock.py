"""A stand-in for the BMONI Embedded API, served in-process when BMONI_MODE=mock.

Paths and response shapes mirror the real sandbox (https://embedded-dev.bmoni.com/docs):
users -> smart wallets (CNGN = naira stablecoin, USDB = dollar) -> balance / transactions.
Dates are relative to today so demos always look current. Test data only.
"""

from datetime import date, datetime, time, timedelta

from fastapi import FastAPI, Header, HTTPException

mock_app = FastAPI(title="BMONI Embedded API (mock)")

USER_ID = "mock-user-david"
WALLETS = [
    {"id": "sw_cngn_001", "currency": "CNGN", "walletAddress": "0x00000000000000000000000000000000000c0ffe",
     "isActive": True, "createdAt": "2026-09-01T09:00:00.000Z", "updatedAt": "2026-09-01T09:00:00.000Z"},
    {"id": "sw_usdb_001", "currency": "USDB", "walletAddress": "0x00000000000000000000000000000000000c0ffe",
     "isActive": True, "createdAt": "2026-09-01T09:00:00.000Z", "updatedAt": "2026-09-01T09:00:00.000Z"},
]
BALANCES = {"sw_cngn_001": "24500.000000", "sw_usdb_001": "12.400000"}

# (days_ago, hour, amount, direction, narrationType, counterparty, purpose/note)
_CNGN_TX = [
    (0, 13, 1800, "outgoing", "send_to_bank", "Mama Cass Cafeteria", "Lunch - rice and chicken"),
    (0, 8, 300, "outgoing", "send_to_friend", "UNILAG Shuttle", "Campus shuttle gate to faculty"),
    (1, 21, 2500, "outgoing", "send_to_bank", "MTN Nigeria", "10GB data bundle"),
    (1, 14, 4200, "outgoing", "send_to_bank", "University Bookshop", "Lab manual"),
    (2, 19, 1900, "outgoing", "send_to_friend", "New Hall Buka", "Jollof rice dinner"),
    (3, 16, 15000, "incoming", "fund_bank", "UNILAG Tech Club", "Poster design gig payment"),
    (3, 19, 3400, "outgoing", "send_to_bank", "Chicken Republic Akoka", "Dinner after study group"),
    (4, 12, 2100, "outgoing", "send_to_bank", "Moremi Cafeteria", "Lunch"),
    (5, 18, 3000, "outgoing", "send_to_friend", "Hostel Exco", "Generator levy"),
    (5, 11, 1200, "outgoing", "send_to_bank", "Sub-campus Print Centre", "GST handout photocopy"),
    (6, 9, 400, "outgoing", "send_to_friend", "Keke Rider", "Keke to Yaba"),
    (6, 13, 1700, "outgoing", "send_to_friend", "Iya Basira Buka", "Amala and ewedu"),
    (9, 10, 30000, "incoming", "fund_bank", "Adeleke Olusegun", "Monthly allowance"),
    (10, 20, 1500, "outgoing", "send_to_bank", "Airtel", "Airtime recharge"),
    (12, 15, 2200, "outgoing", "send_to_friend", "Campus Grill", "Shawarma and drink"),
    (12, 15, 50, "outgoing", "service_fee", "BMONI", None),
]


def _check(user_id: str, key: str | None) -> None:
    if not key:
        raise HTTPException(401, {"statusCode": 401, "message": "Missing API key", "error": "Unauthorized"})
    if user_id != USER_ID:
        raise HTTPException(404, {"statusCode": 404, "message": "User not found", "error": "Not Found"})


@mock_app.get("/v1/health")
def health():
    return {"status": "ok"}


@mock_app.get("/v1/users")
def list_users(x_api_key: str | None = Header(None), page: int = 1, limit: int = 20):
    _check(USER_ID, x_api_key)
    user = {"id": USER_ID, "partnerName": "Zuko (mock)", "firstName": "David", "lastName": "Adeleke",
            "email": "david@example.com", "phoneNumber": "+2340000000000", "createdAt": "2026-09-01T09:00:00.000Z"}
    return {"users": [user], "total": 1, "page": page, "limit": limit}


@mock_app.get("/v1/users/{user_id}/smart-wallets/account/wallets")
def list_wallets(user_id: str, x_api_key: str | None = Header(None)):
    _check(user_id, x_api_key)
    return WALLETS


@mock_app.get("/v1/users/{user_id}/smart-wallets/{wallet_id}/balance")
def wallet_balance(user_id: str, wallet_id: str, x_api_key: str | None = Header(None)):
    _check(user_id, x_api_key)
    if wallet_id not in BALANCES:
        raise HTTPException(404, {"statusCode": 404, "message": "Smart wallet not found", "error": "Not Found"})
    currency = next(w["currency"] for w in WALLETS if w["id"] == wallet_id)
    return {"balance": BALANCES[wallet_id], "currency": currency, "smartWalletId": wallet_id}


@mock_app.get("/v1/users/{user_id}/transactions/{wallet_id}")
def wallet_transactions(user_id: str, wallet_id: str, x_api_key: str | None = Header(None)):
    _check(user_id, x_api_key)
    if wallet_id not in BALANCES:
        raise HTTPException(404, {"statusCode": 404, "message": "Smart wallet not found", "error": "Not Found"})
    if wallet_id != "sw_cngn_001":
        return {"transactions": [], "count": 0}
    today = date.today()
    rows = []
    for i, (days_ago, hour, amount, direction, narration, party, purpose) in enumerate(_CNGN_TX):
        when = datetime.combine(today - timedelta(days=days_ago), time(hour, 0))
        sign = "-" if direction == "outgoing" else ""
        rows.append({
            "id": f"txn_{i:04d}",
            "direction": direction,
            "delta": f"{sign}{amount:.2f}",
            "amount": f"{amount:.2f}",
            "currency": "CNGN",
            "status": "completed",
            "counterpartyType": "fee" if narration == "service_fee" else "bank" if narration.endswith("bank") else "wallet",
            "counterpartyName": party,
            "senderName": party if direction == "incoming" else "David Adeleke",
            "receiverName": "David Adeleke" if direction == "incoming" else party,
            "purpose": purpose,
            "note": purpose,
            "createdAt": when.isoformat() + ".000Z",
            "narrationType": narration,
        })
    rows.append({**rows[2], "id": "txn_failed", "status": "failed", "failureType": "PARTNER"})
    rows.sort(key=lambda r: r["createdAt"])
    return {"transactions": rows, "count": len(rows)}
