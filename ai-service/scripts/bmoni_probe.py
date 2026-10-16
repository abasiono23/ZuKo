"""Check the BMONI sandbox connection and show what Zuko would sync (read-only calls only).

Usage (from ai-service/, with BMONI_MODE=sandbox and BMONI_API_KEY set in .env):
    .venv/Scripts/python -X utf8 scripts/bmoni_probe.py [bmoni_user_id]

Without a user id it uses BMONI_USER_ID. The partner key is shared by every hackathon team,
so this script never prints other users' details, only a count.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bmoni.client import BmoniClient, BmoniError  # noqa: E402
from app.config import get_settings  # noqa: E402


async def main(user_id: str | None) -> None:
    s = get_settings()
    print(f"Mode: {s.bmoni_mode}   Base URL: {s.bmoni_base_url or '(mock)'}   Auth: {s.bmoni_auth_scheme}\n")
    async with BmoniClient() as c:
        print("Health:", await c.health())
        users = await c._get("/v1/users", {"limit": 1})
        print(f"API key accepted. Users under this partner key: {users.get('total')}")
        print("Naira wallet currencies:", ", ".join(s.bmoni_naira_currencies))

        uid = user_id or s.bmoni_user_id
        if not uid and s.bmoni_mode != "mock":
            print("\nNo user id given. Set BMONI_USER_ID (or pass one) to check wallets and transactions.")
            return
        try:
            wallets = await c.wallets(uid)
        except BmoniError as exc:
            print(f"\nWallets for user failed: {exc} {exc.body}")
            return
        print(f"\nWallets ({len(wallets)}):")
        for w in wallets:
            print(f"  {w.get('id')}  {w.get('currency')}  active={w.get('isActive')}")
        for w in wallets:
            bal = await c.balance(str(w["id"]), uid)
            txs = await c.transactions(str(w["id"]), uid)
            print(f"\n{w.get('currency')} wallet {w['id']}: balance {bal['balance']}, {len(txs)} usable transactions")
            for t in txs[:5]:
                print(f"   {t.date} {t.direction:6} {t.amount:>10,.2f} {t.category.value:16} {t.merchant or ''} | {t.description or ''}")


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
    except BmoniError as exc:
        print(f"BMONI error: {exc}\n{exc.body}")
        sys.exit(1)
