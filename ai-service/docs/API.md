# Zuko AI Service: API contract

Base URL (local): `http://localhost:8000`. Swagger UI: `/docs`.

**Auth:** send `X-Service-Key: <ZUKO_SERVICE_KEY>` on every `/v1/*` call. It's a server-to-server secret; call this service from the Node backend, not the browser.

**Money:** plain numbers in Naira. Amounts are always positive, and `direction` is `debit` or `credit`.

**Categories:** `food`, `transport`, `data_airtime`, `school_materials`, `dues`, `accommodation`, `personal_leisure`, `income`, `other`.

---

## Shared object: `FinancialContext`

The Node backend builds this from Supabase and sends it with insight and coach calls.

```json
{
  "user_name": "David",
  "today": "2024-10-24",               // optional, defaults to server date
  "balance": 28500,                     // liquid cash across wallets + cash in pocket
  "cycle_start": "2024-10-06",          // optional, defaults to the 1st of the month
  "emergency_cushion": 3000,            // optional, defaults to ZUKO_DEFAULT_CUSHION
  "next_inflow": {"amount": 30000, "date": "2024-11-05", "source": "Parental support via Kuda"},
  "budgets": [{"category": "food", "limit": 14000}],
  "obligations": [{"name": "GST 201 printing", "amount": 5000, "due_date": "2024-10-28", "earmarked": true, "paid": false}],
  "goals": [{"name": "ThinkPad Laptop Fund", "target": 150000, "saved": 65000, "due_date": null, "paused": false}],
  "transactions": [
    {"id": "uuid", "amount": 1800, "direction": "debit", "category": "food", "merchant": "Mama Cass",
     "description": "Rice & protein", "date": "2024-10-24", "source": "manual", "payment_method": "cash"}
  ]
}
```

---

## `POST /v1/expenses/parse`

Add Expense → **Parse with Zuko AI**.

```json
// request
{"text": "I spent ₦2,000 on lunch at Moremi cafeteria and ₦1,500 on Keke transport today",
 "reference_date": "2024-10-24",       // optional
 "context": { ...FinancialContext }}    // optional; when given, runway_impact is returned
```

```json
// response
{
  "items": [
    {"amount": 2000, "direction": "debit", "category": "food", "category_label": "Food & Chow",
     "merchant": "Moremi Cafeteria", "description": "Lunch at Moremi Cafeteria", "date": "2024-10-24",
     "payment_method": null, "confidence": 0.95},
    {"amount": 1500, "direction": "debit", "category": "transport", "category_label": "Campus Transport",
     "merchant": null, "description": "Keke transport", "date": "2024-10-24", "payment_method": null, "confidence": 0.95}
  ],
  "total_debit": 3500, "total_credit": 0,
  "engine": "openai",                    // or "rules" when the AI is unavailable
  "notes": [],                           // e.g. "Double-check ₦X…"
  "runway_impact": {
    "days_left": 12, "balance_before": 28500, "balance_after": 25000,
    "safe_daily_before": 1458, "safe_daily_after": 1167, "subsistence_floor": 1200, "above_floor": false,
    "message": "Heads up: this drops you ₦33/day below your ₦1,200/day subsistence buffer."
  }
}
```

The frontend shows `items` for review. The user confirms, and then Node saves them to Supabase. **This service never writes data.**

---

## `POST /v1/insights`

Body: `FinancialContext`. Feeds the Overview dashboard and the Budgets page.

```json
{
  "snapshot": {"today": "2024-10-24", "balance": 28500, "days_until_inflow": 12, "committed_obligations": 8000,
               "emergency_cushion": 3000, "discretionary": 17500, "safe_daily_spend": 1458,
               "spent_this_cycle": 28100, "income_this_cycle": 15000, "net_burn": 13100,
               "total_budget": 35000, "budget_used_percent": 80.3},
  "alerts": [{"kind": "velocity", "severity": "critical", "title": "Your food & chow spending is speeding up",
              "message": "You've averaged ₦1,557/day on food & chow…", "category": "food",
              "suggested_action": "Move ₦1,000 from personal & leisure"}],
  "category_pacing": [{"category": "food", "label": "Food & Chow", "spent": 13100, "limit": 14000, "remaining": 900,
                       "percent_used": 93.6, "daily_pace": 1557, "days_to_exhaust": 0.6, "status": "critical"}],
  "weekly_pattern": [{"date": "2024-10-18", "amount": 0}, "... 7 days, oldest first"],
  "safe_daily_ceiling": 1167,
  "top_categories": [{"category": "food", "label": "Food & Chow", "amount": 13100, "share_percent": 46.6}],
  "savings_advice": {"max_goal_contribution": 5500, "keep_flexible": 12000, "message": "Lock no more than ₦5,500…"},
  "generated_at": "2026-10-16T08:00:00Z"
}
```

- `alerts[].kind`: `velocity`, `budget`, `runway`, `obligation` or `subsistence`. `severity`: `info`, `warning` or `critical`.
- `category_pacing[].status`: `healthy`, `on_track`, `warning`, `critical` or `untouched`.

## `POST /v1/insights/affordability`

```json
// request
{"context": { ...FinancialContext }, "amount": 4000, "label": "cinema outing"}
// response
{"affordable": true, "risk_level": "moderate",          // low | moderate | high | critical
 "breakdown": [{"label": "Available balance", "amount": 28500, "note": null}, "..."],
 "uncommitted_before": 17500, "remaining_after": 13500, "days_until_inflow": 12,
 "daily_before": 1458, "daily_after": 1125, "percent_of_uncommitted": 22.9, "suggested_cap": 3100,
 "summary": "You can, but it's tight: …"}
```

---

## `POST /v1/coach/chat`

The AI Assistant screen. Send the whole visible conversation each time, oldest first. The last message must be from the user.

```json
// request
{"context": { ...FinancialContext },
 "messages": [{"role": "user", "content": "Can I spend ₦4,000 on an outing with friends?"}]}
```

```json
// response
{
  "reply": "You can, but it'll squeeze you …",
  "breakdown": [{"label": "True uncommitted cash", "amount": 17500, "note": null}, "..."],
  "risk_level": "moderate",
  "recommendation": "Cap the outing at ₦3,100 …",
  "actions": [{"label": "Set ₦3,100 outing budget", "action": "set_budget", "amount": 3100, "category": "personal_leisure", "target": null}],
  "grounding": "Verified against ₦28,500 balance, ₦8,000 earmarked obligations, next allowance Nov 5, 13 transactions.",
  "engine": "openai"
}
```

`actions[].action` is one of `set_budget`, `earmark`, `contribute_goal`, `log_expense`, `explain` or `none`. These map to the "One-Tap Actionable Resolutions" buttons, and Node carries out the action.

---

## BMONI

These routes proxy the BMONI Embedded API (`x-api-key` auth, handled server-side). `{user_id}` is the student's **`bmoniUserId`** (not the user record's `id`), which Node stores in Supabase. Pass `default` to use `BMONI_USER_ID`. The naira wallet is the one with currency `CNGN`.

| Method | Path | Returns |
|---|---|---|
| GET | `/v1/bmoni/health` | `{"mode", "upstream": {"status": "ok"}}` |
| GET | `/v1/bmoni/users/{user_id}/wallets` | `{"mode", "wallets": [{"id", "currency", "walletAddress", "isActive", …}]}` |
| GET | `/v1/bmoni/users/{user_id}/wallets/{wallet_id}/balance` | `{"wallet_id", "currency", "balance"}` |
| GET | `/v1/bmoni/users/{user_id}/wallets/{wallet_id}/transactions?start=YYYY-MM-DD&end=YYYY-MM-DD` | `Transaction[]`, normalized with `source: "bmoni"` and auto-categorized; failed transfers and internal swaps dropped |
| POST | `/v1/bmoni/context` | `{"context": FinancialContext, "sync": {...}}` built from BMONI + saved settings |
| POST | `/v1/bmoni/insights` | `{"insights": InsightsResponse, "sync": {...}}`, one call for the dashboard |

Request body for `/v1/bmoni/context` and `/v1/bmoni/insights`:

```json
{"user_id": "bmoni-user-uuid",       // default: BMONI_USER_ID
 "wallet_ids": null,                 // default: all active CNGN wallets
 "user_name": "David", "cash_in_pocket": 4000,
 "manual_transactions": [],          // cash spends logged in Zuko
 "budgets": [], "obligations": [], "next_inflow": null, "goals": [],
 "cycle_start": null, "emergency_cushion": null, "lookback_days": 45}
```

Upstream BMONI errors come back as `502` (or BMONI's own 4xx, e.g. `404` for an unknown user or wallet) with `{"detail": {"message", "upstream_status", "upstream_body"}}`.

**Suggested sync flow for Node:** call `GET /v1/bmoni/users/{id}/wallets/{wallet}/transactions`, then upsert into Supabase keyed on `(source='bmoni', id)` so re-syncs don't create duplicates.

**Never expose the BMONI key to the browser.** It's a shared hackathon partner key that can read every team's users.

---

## `GET /health`

`{"status": "ok", "ai": {"enabled": true, "provider": "openai", "model": "gpt-5.5"}, "bmoni": {"mode": "mock", "base_url_configured": false}}`
