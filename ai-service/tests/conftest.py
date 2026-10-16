import os

# Tests are deterministic: no AI calls, mock BMONI, no service key.
os.environ["ZUKO_AI_ENABLED"] = "false"
os.environ["BMONI_MODE"] = "mock"
os.environ["ZUKO_SERVICE_KEY"] = ""
# Ignore any real BMONI settings in .env (empty = use code defaults).
for _var in ("BMONI_API_KEY", "BMONI_USER_ID", "BMONI_AUTH_SCHEME", "BMONI_AMOUNT_UNIT",
             "BMONI_PATH_WALLETS", "BMONI_PATH_BALANCE", "BMONI_PATH_TRANSACTIONS", "BMONI_NAIRA_CURRENCIES"):
    os.environ[_var] = ""

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

from app.schemas import FinancialContext  # noqa: E402

TODAY = date(2024, 10, 24)


def demo_context_dict() -> dict:
    """David Adeleke, UNILAG, day 18 of his allowance cycle (mirrors the Stitch designs)."""
    d = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
    return {
        "user_name": "David",
        "today": TODAY.isoformat(),
        "balance": 28500,
        "cycle_start": "2024-10-06",
        "emergency_cushion": 3000,
        "next_inflow": {"amount": 30000, "date": "2024-11-05", "source": "Parental support via Kuda"},
        "budgets": [
            {"category": "food", "limit": 14000},
            {"category": "data_airtime", "limit": 5000},
            {"category": "transport", "limit": 4500},
            {"category": "school_materials", "limit": 4000},
            {"category": "accommodation", "limit": 5000},
            {"category": "personal_leisure", "limit": 2500},
        ],
        "obligations": [
            {"name": "GST 201 course pack printing", "amount": 5000, "due_date": "2024-10-28", "earmarked": True},
            {"name": "Faculty dues & lab coat", "amount": 3000, "due_date": "2024-11-02"},
        ],
        "goals": [
            {"name": "ThinkPad Laptop Fund", "target": 150000, "saved": 65000},
            {"name": "Semester dues", "target": 80000, "saved": 48000},
        ],
        "transactions": [
            {"amount": 1800, "category": "food", "merchant": "Mama Cass", "date": d(0)},
            {"amount": 300, "category": "transport", "date": d(0)},
            {"amount": 2500, "category": "data_airtime", "date": d(1)},
            {"amount": 4200, "category": "school_materials", "date": d(1)},
            {"amount": 3400, "category": "food", "date": d(2)},
            {"amount": 15000, "direction": "credit", "category": "income", "date": d(3)},
            {"amount": 1900, "category": "food", "date": d(3)},
            {"amount": 2100, "category": "food", "date": d(4)},
            {"amount": 1700, "category": "food", "date": d(5)},
            {"amount": 3000, "category": "accommodation", "date": d(5)},
            {"amount": 2000, "category": "data_airtime", "date": d(8)},
            {"amount": 2200, "category": "food", "date": d(10)},
            {"amount": 3000, "category": "transport", "date": d(12)},
        ],
    }


@pytest.fixture
def ctx_dict() -> dict:
    return demo_context_dict()


@pytest.fixture
def ctx(ctx_dict) -> FinancialContext:
    return FinancialContext.model_validate(ctx_dict)
