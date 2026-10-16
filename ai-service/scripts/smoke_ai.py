"""Live check of the AI-powered paths (needs OPENAI_API_KEY in .env).

    .venv/Scripts/python -X utf8 scripts/smoke_ai.py
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from conftest import demo_context_dict  # noqa: E402  (sets mock/no-AI env; undo the AI part below)
import os  # noqa: E402

os.environ["ZUKO_AI_ENABLED"] = "true"
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.coach.coach import chat  # noqa: E402
from app.parsing.ai import parse_expenses  # noqa: E402
from app.schemas import CoachRequest  # noqa: E402

notes = [
    "I spent ₦2,000 on lunch at Moremi cafeteria and ₦1,500 on Keke transport today",
    "abeg log am: chop 1.5k for buka, mtn data 2k yesterday, printed PHY 202 handout 800",
    "Credit Alert! Amt: NGN30,000.00 Desc: TRF FROM ADELEKE OLUSEGUN allowance",
]
for n in notes:
    items, extra, engine = parse_expenses(n, date(2024, 10, 24))
    print(f"\n[{engine}] {n}")
    for i in items:
        print(f"   ₦{i.amount:,.0f} {i.direction} {i.category.value} | {i.description} | {i.merchant} | {i.date} | conf {i.confidence}")
    for x in extra:
        print("   note:", x)

reply = chat(CoachRequest.model_validate({
    "context": demo_context_dict(),
    "messages": [{"role": "user", "content": "I have ₦15,000 left. Can I spend ₦4,000 on an outing with friends at the cinema?"}],
}))
print("\nCoach:", json.dumps(reply.model_dump(mode="json"), indent=1, ensure_ascii=False))
