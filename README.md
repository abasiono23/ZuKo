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

## Deployment (Render)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/abasiono23/ZuKo)

The AI service deploys from [`render.yaml`](render.yaml) as a free Render web service named `zuko-ai-service`.

1. Click the button (or Render dashboard → **New → Blueprint** → this repo).
2. When asked, paste the two secrets: `OPENAI_API_KEY` and `BMONI_API_KEY`.
3. Click **Apply**. The first build takes a few minutes. The service URL looks like `https://zuko-ai-service.onrender.com`.
4. Check `https://<service-url>/health`, then open `https://<service-url>/docs` for interactive API docs.
5. Copy the generated `ZUKO_SERVICE_KEY` from the service's **Environment** tab and send it privately to the backend developer. Every `/v1/*` call needs it in the `X-Service-Key` header.

Pushes to `main` redeploy automatically. On the free plan the service sleeps after about 15 minutes idle, so the first request after that takes around 50 seconds.
