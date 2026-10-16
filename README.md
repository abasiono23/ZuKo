# Zuko: Student Financial Intelligence

AI-powered budgeting for Nigerian university students, built for the NITHUB × BMONI hackathon.

## Repository layout

| Folder | Owner | What's inside |
|---|---|---|
| [`ai-service/`](ai-service/) | Ono (Python) | AI expense parsing, financial insights, AI coach, BMONI sandbox integration (FastAPI) |
| `backend/` | Node.js full-stack | Supabase setup, auth, transaction data *(to be added)* |
| `frontend/` | Frontend team | Dashboard, budgets & goals, add expense, transactions, AI chat *(to be added)* |
| `stitch_zuko_student_financial_intelligence.zip` | Design | Stitch UI designs (screens + Emerald Ledger design system) |

Start with [ai-service/README.md](ai-service/README.md), the API contract in [ai-service/docs/API.md](ai-service/docs/API.md), and the BMONI notes in [ai-service/docs/BMONI_INVESTIGATION.md](ai-service/docs/BMONI_INVESTIGATION.md).

## Secrets

API keys live only in local `.env` files, which are git-ignored. Copy `ai-service/.env.example` to `ai-service/.env` and fill it in. Never commit keys: the BMONI partner key is shared across hackathon teams.
