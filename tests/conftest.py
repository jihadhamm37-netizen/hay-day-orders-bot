"""Test fixtures — every test runs against a freshly migrated real PostgreSQL database.

Set TEST_DATABASE_URL, e.g. postgresql://postgres:postgres@localhost:5432/hdfarm_test
(the database's public schema is wiped before each test).
"""
from __future__ import annotations

import os

import pytest

from app.config import Config
from app.core import Core
from app.db import create_pool, migrate
from app.security import Vault, generate_fernet_key

DSN = os.environ.get("TEST_DATABASE_URL")
KEY = generate_fernet_key()


class FakeMessenger:
    def __init__(self):
        self.delivered: list[tuple[int, str, str]] = []
        self.summaries: list[dict] = []
        self.method_lists: list[tuple[dict, list]] = []
        self.customer_msgs: list[tuple[int, str, dict]] = []
        self.texts: list[tuple[int, str]] = []
        self.admin_msgs: list[str] = []
        self.codes: list[tuple[int, str]] = []
        self.fail_delivery = False

    async def send_order_summary(self, order):
        self.summaries.append(order)

    async def send_payment_methods(self, order, methods):
        self.method_lists.append((order, methods))

    async def send_payment_details(self, order, method):
        pass

    async def deliver_farms(self, order, items):
        if self.fail_delivery:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        for _, tok, pw in items:
            self.delivered.append((order["customer_id"], tok, pw))

    async def notify_customer(self, customer_id, key, **params):
        self.customer_msgs.append((customer_id, key, params))
        return True

    async def send_text(self, customer_id, text):
        self.texts.append((customer_id, text))
        return True

    async def notify_admins(self, text, *, perm="view", photo=None, reply_markup=None):
        self.admin_msgs.append(text)

    async def send_admin_code(self, telegram_id, code):
        self.codes.append((telegram_id, code))
        return True


@pytest.fixture
async def core():
    if not DSN:
        pytest.skip("TEST_DATABASE_URL not set")
    pool = await create_pool(DSN, max_size=40)
    await pool.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await migrate(pool)
    cfg = Config(bot_token="123:TEST", database_url=DSN, encryption_key=KEY,
                 jwt_secret="test-secret-for-jwt-signing-0123456789abcdef", owner_ids={999}, cookie_secure=False,
                 backup_dir="/tmp/hd-test-backups", anthropic_api_key="test-key")
    c = Core(pool, Vault(KEY), cfg, FakeMessenger())
    yield c
    await pool.close()


async def make_customer(core: Core, cid: int, lang: str = "ar") -> dict:
    from app.services import customers
    return await customers.touch(core, cid, f"user{cid}", f"User {cid}", lang)


async def add_farms(core: Core, n: int = 5, *, lvl: int = 100, price: str = "30", cost: str | None = "20",
                    prefix: str = "TOK") -> list[dict]:
    from app.services import farms
    out = []
    for i in range(n):
        out.append(await farms.create_farm(core, "test", {"lvl": lvl, "barn": 10000, "silo": 3000, "tools": 10000,
                                                         "price": price, "cost": cost, "token_id": f"{prefix}{lvl}-{i}",
                                                         "password": f"pw{i}"}))
    return out


async def offer_code(core: Core, lvl: int = 100) -> str:
    from app.services import farms
    offers = await farms.search_offers(core, min_level=lvl, max_level=lvl)
    return offers[0]["offer_code"]


async def method_id(core: Core) -> int:
    return await core.pool.fetchval("SELECT id FROM payment_methods ORDER BY id LIMIT 1")


async def paid_flow(core: Core, cid: int, qty: int = 1, lvl: int = 100, proof: str = "proof1", txid: str = "TX123456"):
    """Customer: prepare → confirm → choose method → screenshot → txid. Returns (order, payment)."""
    from app.services import orders, payments
    o = await orders.prepare(core, cid, await offer_code(core, lvl), qty)
    o = await orders.confirm(core, cid, o["id"])
    await payments.choose_method(core, cid, o["id"], await method_id(core))
    r = await payments.submit_proof(core, cid, "file-" + proof, proof)
    p = r["payment"]
    if r["need_txid"]:
        p = await payments.submit_txid(core, cid, p["id"], txid)
    return o, p
