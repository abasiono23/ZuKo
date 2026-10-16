"""HTTP client for the BMONI Embedded API (https://embedded-dev.bmoni.com/docs).

Data model: partner (our API key) -> users -> smart wallets (CNGN = naira stablecoin,
USDB = dollar, ...) -> balance + transactions. Every partner endpoint authenticates
with the `x-api-key` header. Paths are configurable in .env.
With BMONI_MODE=mock, requests go in-process to `app.bmoni.mock`.
"""

import base64
from datetime import date
from typing import Any

import httpx

from app.bmoni import normalize
from app.config import Settings, get_settings
from app.schemas import Transaction


class BmoniError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _auth_headers(s: Settings) -> dict[str, str]:
    if not s.bmoni_api_key:
        return {}
    if s.bmoni_auth_scheme == "bearer":
        return {"Authorization": f"Bearer {s.bmoni_api_key}"}
    if s.bmoni_auth_scheme == "basic":
        token = base64.b64encode(f"{s.bmoni_api_key}:{s.bmoni_secret_key}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    return {"x-api-key": s.bmoni_api_key}


def build_http_client(s: Settings | None = None) -> httpx.AsyncClient:
    s = s or get_settings()
    headers = {"Accept": "application/json", "User-Agent": "zuko-ai-service/1.0", **_auth_headers(s)}
    if s.bmoni_mode == "mock":
        from app.bmoni.mock import mock_app
        headers.setdefault("x-api-key", "mock-key")
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://bmoni-mock",
                                 headers=headers, timeout=s.bmoni_timeout_s)
    if not s.bmoni_base_url:
        raise BmoniError("BMONI_BASE_URL is not set (or set BMONI_MODE=mock)")
    if not s.bmoni_api_key:
        raise BmoniError("BMONI_API_KEY is not set")
    return httpx.AsyncClient(base_url=s.bmoni_base_url, headers=headers, timeout=s.bmoni_timeout_s)


class BmoniClient:
    def __init__(self, settings: Settings | None = None, http: httpx.AsyncClient | None = None):
        self.s = settings or get_settings()
        self._http = http

    async def __aenter__(self) -> "BmoniClient":
        if self._http is None:
            self._http = build_http_client(self.s)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            await self._http.aclose()

    def user_id(self, user_id: str | None) -> str:
        uid = user_id or self.s.bmoni_user_id or ("mock-user-david" if self.s.bmoni_mode == "mock" else "")
        if not uid:
            raise BmoniError("No BMONI user id given (pass user_id or set BMONI_USER_ID)", 400)
        return uid

    async def _get(self, path: str, params: dict | None = None) -> Any:
        assert self._http is not None, "use `async with BmoniClient() as c:`"
        try:
            resp = await self._http.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        except httpx.HTTPError as exc:
            raise BmoniError(f"BMONI request failed: {exc}") from exc
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        if resp.status_code >= 400:
            message = body.get("message") if isinstance(body, dict) else None
            raise BmoniError(f"BMONI returned {resp.status_code}: {message or path}", resp.status_code, body)
        return body

    async def health(self) -> Any:
        return await self._get("/v1/health")

    async def wallets(self, user_id: str | None = None) -> list[dict]:
        uid = self.user_id(user_id)
        try:
            return normalize.as_list(await self._get(self.s.bmoni_path_wallets.format(user_id=uid)))
        except BmoniError as exc:
            # BMONI answers 400 "No embedded smart wallet group found" for users with no wallets yet.
            if exc.status_code == 400 and "wallet group" in str(exc.body):
                return []
            raise

    async def balance(self, wallet_id: str, user_id: str | None = None) -> dict:
        uid = self.user_id(user_id)
        raw = await self._get(self.s.bmoni_path_balance.format(user_id=uid, wallet_id=wallet_id))
        data = normalize.unwrap(raw)
        return {
            "wallet_id": wallet_id,
            "currency": data.get("currency") if isinstance(data, dict) else None,
            "balance": normalize.balance_of(raw),
        }

    async def transactions(self, wallet_id: str, user_id: str | None = None,
                           start: date | None = None, end: date | None = None) -> list[Transaction]:
        uid = self.user_id(user_id)
        raw = await self._get(self.s.bmoni_path_transactions.format(user_id=uid, wallet_id=wallet_id))
        txs = normalize.to_transactions(raw)
        # The endpoint returns the full history; filter the window client-side.
        return [t for t in txs if (start is None or t.date >= start) and (end is None or t.date <= end)]

    async def naira_wallet_ids(self, user_id: str | None = None) -> list[str]:
        """Active wallets whose currency is naira-denominated (CNGN by default)."""
        wallets = await self.wallets(user_id)
        return [str(w["id"]) for w in wallets
                if w.get("id") and w.get("isActive", True)
                and str(w.get("currency", "")).upper() in self.s.bmoni_naira_currencies]
