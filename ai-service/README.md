# Zuko AI Service (Python)

AI expense parsing, financial insights, the AI coach, and the BMONI sandbox integration for **Zuko: Student Financial Intelligence**.

This is the Python half of the backend. The Node.js backend owns Supabase, auth and storing transactions; it calls this service over HTTP for anything "smart".

```
Frontend (Next/React) ──► Node.js API (Supabase, auth, CRUD) ──► Zuko AI Service (this repo)
                                                                     ├─ OpenAI (parsing + coach)
                                                                     └─ BMONI sandbox (wallets, transactions)
```

## Quick start

```powershell
cd ai-service
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env        # then fill in OPENAI_API_KEY and BMONI_*
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for interactive Swagger docs.

Run the tests (offline: no AI calls, mock BMONI):

```powershell
.venv\Scripts\python -X utf8 -m pytest -q
```

## What it does

| Screen (Stitch design) | Endpoint | What you get |
|---|---|---|
| Add Expense → "Parse with Zuko AI" | `POST /v1/expenses/parse` | Items extracted from free text (English, Pidgin, slang, bank SMS), plus the "Allowance Reality Check" runway preview |
| Overview: AI Intelligence card, weekly chart, categories | `POST /v1/insights` | Safe daily spend, velocity alerts, category pacing, 7-day pattern, top categories, savings advice |
| Budgets & Goals: Reality Check | `POST /v1/insights` (`savings_advice`) | How much can safely be locked into goals |
| AI Assistant | `POST /v1/coach/chat` | A grounded reply with a calculation breakdown, risk level and one-tap actions |
| "Can I afford this?" | `POST /v1/insights/affordability` | A deterministic affordability check |
| Transactions: live feeds / Data Sync | `GET /v1/bmoni/...`, `POST /v1/bmoni/insights` | BMONI wallets, balances and transactions, normalized to Zuko's schema |

The full request and response contract is in [docs/API.md](docs/API.md). The BMONI findings and open questions are in [docs/BMONI_INVESTIGATION.md](docs/BMONI_INVESTIGATION.md).

## Design principles

- **Numbers come from code, not the model.** `app/insights/engine.py` computes every figure. The model explains them and recommends actions, but it never invents balances. Every coach reply carries a `grounding` line showing what it was checked against.
- **Works without AI.** If the AI is unavailable (no key, rate limit, outage), parsing falls back to `app/parsing/rules.py` and the coach falls back to template answers. Each response has an `engine` field (`openai` or `rules`).
- **AI output is checked.** Parsed amounts that don't appear in the user's text get their confidence lowered and a note added.
- **Real BMONI sandbox.** The client follows the BMONI Embedded API (`https://embedded-dev.bmoni.com/docs`): `x-api-key` auth, users → smart wallets (`CNGN` = naira) → balance and transactions. Set `BMONI_MODE=mock` to work offline against an identical mock.
- **Privacy.** Only test data is used. Request bodies are not logged. The Node backend authenticates with `X-Service-Key`.

## Layout

```
app/
  main.py              FastAPI routes
  config.py            env settings
  schemas.py           request/response models (the API contract)
  categories.py        categories + English/Pidgin/slang keyword rules
  ai_client.py         OpenAI client: structured outputs (Responses API), error handling
  parsing/rules.py     offline natural-language expense parser
  parsing/ai.py        AI parser with rules fallback
  insights/engine.py   safe-to-spend, pacing, velocity alerts, affordability, runway, savings advice
  coach/coach.py       AI financial coach
  bmoni/client.py      BMONI HTTP client
  bmoni/normalize.py   BMONI payload → Zuko Transaction
  bmoni/mock.py        in-process mock sandbox (BMONI_MODE=mock)
scripts/
  bmoni_probe.py       check the sandbox connection and preview a user's wallets/transactions
  smoke_ai.py          live AI check
  bmoni_setup_demo.py  create the demo student + CNGN wallet in the BMONI sandbox
tests/                 pytest suite (32 tests)
```

## AI configuration

- Provider: OpenAI, using the Responses API with Pydantic structured outputs (`client.responses.parse`).
- Model: `gpt-5.5` by default. Change it with `ZUKO_AI_MODEL` (e.g. `gpt-5.4-mini` for lower cost).
- Reasoning effort: `low` for parsing (fast), `medium` for the coach (`ZUKO_PARSE_EFFORT`, `ZUKO_COACH_EFFORT`).
- The key comes from `OPENAI_API_KEY` in `.env`. Run `.venv\Scripts\python -X utf8 scripts\smoke_ai.py` to check the live paths.

## BMONI demo student

`scripts/bmoni_setup_demo.py` creates a fictional student ("David Adeleke", `example.com` email) and a CNGN wallet in the sandbox, then saves `BMONI_USER_ID`, `BMONI_DEMO_WALLET_ID` and the test wallet-owner key to `.env`. It's safe to re-run: steps that are already done are skipped.
