"""Runtime settings, read from environment variables (or a local .env file)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    # An empty value (e.g. "BMONI_PATH_WALLETS=") means "use the default".
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    # Shared secret the Node.js backend sends as X-Service-Key. Empty = auth disabled (local dev only).
    service_key: str
    cors_origins: list[str]

    # OpenAI. Reads OPENAI_API_KEY from the environment.
    ai_enabled: bool
    ai_model: str
    parse_effort: str
    coach_effort: str

    # BMONI. mode=mock serves built-in test data; mode=sandbox calls the real sandbox.
    bmoni_mode: str
    bmoni_base_url: str
    bmoni_api_key: str
    bmoni_secret_key: str
    bmoni_auth_scheme: str  # "x-api-key" (BMONI Embedded API) | "bearer" | "basic"
    bmoni_user_id: str  # default BMONI user for demos; per-student ids come from Supabase
    bmoni_naira_currencies: list[str]
    bmoni_path_wallets: str
    bmoni_path_balance: str
    bmoni_path_transactions: str
    bmoni_amount_unit: str  # "naira" | "kobo"
    bmoni_timeout_s: float

    # Student defaults used when the caller leaves them out.
    default_cushion: float
    min_daily_subsistence: float


@lru_cache
def get_settings() -> Settings:
    origins = _env("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    return Settings(
        service_key=_env("ZUKO_SERVICE_KEY"),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        ai_enabled=_env("ZUKO_AI_ENABLED", "true").lower() not in ("0", "false", "no"),
        ai_model=_env("ZUKO_AI_MODEL", "gpt-5.5"),
        parse_effort=_env("ZUKO_PARSE_EFFORT", "low"),
        coach_effort=_env("ZUKO_COACH_EFFORT", "medium"),
        bmoni_mode=_env("BMONI_MODE", "mock").lower(),
        bmoni_base_url=_env("BMONI_BASE_URL").rstrip("/"),
        bmoni_api_key=_env("BMONI_API_KEY"),
        bmoni_secret_key=_env("BMONI_SECRET_KEY"),
        bmoni_auth_scheme=_env("BMONI_AUTH_SCHEME", "x-api-key").lower(),
        bmoni_user_id=_env("BMONI_USER_ID"),
        bmoni_naira_currencies=[c.strip().upper() for c in _env("BMONI_NAIRA_CURRENCIES", "CNGN,NGN").split(",") if c.strip()],
        bmoni_path_wallets=_env("BMONI_PATH_WALLETS", "/v1/users/{user_id}/smart-wallets/account/wallets"),
        bmoni_path_balance=_env("BMONI_PATH_BALANCE", "/v1/users/{user_id}/smart-wallets/{wallet_id}/balance"),
        bmoni_path_transactions=_env("BMONI_PATH_TRANSACTIONS", "/v1/users/{user_id}/transactions/{wallet_id}"),
        bmoni_amount_unit=_env("BMONI_AMOUNT_UNIT", "naira").lower(),
        bmoni_timeout_s=float(_env("BMONI_TIMEOUT_S", "15")),
        default_cushion=float(_env("ZUKO_DEFAULT_CUSHION", "3000")),
        min_daily_subsistence=float(_env("ZUKO_MIN_DAILY_SUBSISTENCE", "1200")),
    )
