"""Create Zuko's demo student and naira (CNGN) wallet in the BMONI sandbox.

    .venv/Scripts/python -X utf8 scripts/bmoni_setup_demo.py

Idempotent: reuses BMONI_USER_ID / BMONI_DEMO_OWNER_PRIVATE_KEY from .env when present and
skips wallet creation if the user already has a CNGN wallet. Writes the ids back to .env.
The persona is fictional test data (example.com email, random phone number).
"""

import asyncio
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

from app.bmoni.client import BmoniClient, BmoniError  # noqa: E402
from app.config import get_settings  # noqa: E402

ENV_FILE = ROOT / ".env"
CURRENCY = "CNGN"


def env_set(name: str, value: str) -> None:
    """Set NAME=value in .env, replacing an existing line or appending one."""
    text = ENV_FILE.read_text(encoding="utf-8")
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, re.M):
        text = re.sub(rf"^{name}=.*$", lambda _: line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def env_get(name: str) -> str:
    m = re.search(rf"^{name}=(.*)$", ENV_FILE.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


async def post(c: BmoniClient, path: str, body: dict) -> dict:
    resp = await c._http.post(path, json=body)
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        raise BmoniError(f"POST {path} -> {resp.status_code}: {data.get('message')}", resp.status_code, data)
    return data


async def main() -> None:
    s = get_settings()
    if s.bmoni_mode != "sandbox":
        sys.exit("Set BMONI_MODE=sandbox in .env first.")

    async with BmoniClient() as c:
        # 1. Demo student
        user_id = env_get("BMONI_USER_ID")
        if user_id:
            print(f"Using existing BMONI user {user_id}")
        else:
            for _ in range(5):
                tag = random.randint(10_000, 99_999)
                body = {
                    "firstName": "David", "lastName": "Adeleke",
                    "email": f"zuko.demo.david.{tag}@example.com",
                    "phoneNumber": f"+234810{random.randint(1_000_000, 9_999_999)}",
                    "occupation": "Student", "employerName": "University of Lagos",
                    "addressCity": "Lagos", "addressState": "Lagos", "addressCountry": "Nigeria",
                }
                try:
                    user = (await post(c, "/v1/users", body))["user"]
                    break
                except BmoniError as exc:
                    if exc.status_code != 409:
                        raise
                    print("Email/phone already taken, retrying with new test values…")
            else:
                sys.exit("Could not create a unique demo user.")
            # Every /v1/users/{userId}/... path takes the bmoniUserId, not the record id.
            user_id = user["bmoniUserId"]
            env_set("BMONI_USER_ID", user_id)
            print(f"Created demo student {user['firstName']} {user.get('lastName', '')}: {user_id} ({user['email']})")

        # 2. Existing naira wallet?
        try:
            wallets = await c.wallets(user_id)
        except BmoniError as exc:
            if exc.status_code != 400:  # 400 = "No embedded smart wallet group found" (no wallets yet)
                raise
            wallets = []
        existing = [w for w in wallets if str(w.get("currency")).upper() == CURRENCY]
        if existing:
            wallet = existing[0]
            print(f"User already has a {CURRENCY} wallet: {wallet['id']}")
        else:
            # 3. Owner key (test-only, kept in .env) + signed ownership proof
            key = env_get("BMONI_DEMO_OWNER_PRIVATE_KEY")
            account = Account.from_key(key) if key else Account.create()
            if not key:
                env_set("BMONI_DEMO_OWNER_PRIVATE_KEY", account.key.hex())
            print(f"Wallet owner address: {account.address}")

            challenge = await post(c, f"/v1/users/{user_id}/smart-wallets/owner-proof-challenges",
                                   {"currency": CURRENCY, "userOwnerAddress": account.address})
            signature = account.sign_message(encode_defunct(text=challenge["message"])).signature.hex()
            if not signature.startswith("0x"):
                signature = "0x" + signature

            # 4. Create the CNGN wallet
            wallet = await post(c, f"/v1/users/{user_id}/smart-wallets/create-managed", {
                "currency": CURRENCY,
                "userOwnerAddress": account.address,
                "ownerProofChallengeId": challenge["challengeId"],
                "ownerProofSignature": signature,
            })
            print(f"Created {CURRENCY} wallet {wallet['id']} at {wallet.get('walletAddress')} (active={wallet.get('isActive')})")

        env_set("BMONI_DEMO_WALLET_ID", wallet["id"])
        bal = await c.balance(wallet["id"], user_id)
        txs = await c.transactions(wallet["id"], user_id)
        print(f"Balance: {bal['balance']} {bal['currency']}   Transactions: {len(txs)}")
        print("\nSaved BMONI_USER_ID and BMONI_DEMO_WALLET_ID to .env")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BmoniError as exc:
        print(f"BMONI error: {exc}\n{exc.body}")
        sys.exit(1)
