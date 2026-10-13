"""Test fixtures — every test runs against a freshly migrated real PostgreSQL database.

Set TEST_DATABASE_URL, e.g. postgresql://postgres:postgres@localhost:5432/hayday_test
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
        self.credentials: list[tuple[int, str, str]] = []
        self.user_msgs: list[tuple[int, str]] = []
        self.admin_msgs: list[str] = []
        self.codes: list[tuple[int, str]] = []
        self.fail_delivery = False

    async def send_credentials(self, user_id, order, login, password):
        if self.fail_delivery:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.credentials.append((user_id, login, password))

    async def notify_user(self, user_id, text=None, *, key=None, **params):
        from app.i18n import render
        self.user_msgs.append((user_id, text if key is None else render("ar", key, params)))
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
    cfg = Config(bot_token="123:TEST", database_url=DSN, encryption_key=KEY, jwt_secret="test-secret-for-jwt-signing-0123456789abcdef",
                 owner_ids={999}, cookie_secure=False, backup_dir="/tmp/hd-test-backups")
    c = Core(pool, Vault(KEY), cfg, FakeMessenger())
    yield c
    await pool.close()


async def make_user(core: Core, uid: int, balance: str = "0") -> None:
    from app.services import wallet
    await wallet.touch_user(core, uid, f"user{uid}", f"User {uid}")
    if balance != "0":
        await wallet.admin_adjust(core, "test", uid, balance, "رصيد اختبار")


async def make_type(core: Core, n_accounts: int = 5, price: str = "10", lvl: int = 70) -> dict:
    from app.services import catalog
    t = await catalog.create_type(core, "test", {"lvl": lvl, "barn": 4000, "silo": 3000, "price": price})
    items = [{"line": i + 1, "login": f"farm{lvl}_{i}", "password": f"pw{i}"} for i in range(n_accounts)]
    rep = await catalog.add_accounts(core, "test", t["id"], items)
    assert rep["inserted"] == n_accounts
    return t
