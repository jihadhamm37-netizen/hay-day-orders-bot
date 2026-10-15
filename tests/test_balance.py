"""Customer balance: staff top-up by access code, shown in the app, spent on orders, refunded on cancel."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import StoreError
from app.messenger import AppMessenger
from app.services import balance, chat, customers, farms, orders
from tests.test_app import AppUser, login
from app.api.app_api import app_login_limiter
from app.api.server import create_app, login_limiter
from tests.asgi_client import Client


@pytest.fixture
async def env(core):
    core.config.anthropic_api_key = ""
    core.messenger = AppMessenger(core)
    app_login_limiter.hits.clear()
    login_limiter.hits.clear()
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"B-{i}", "password": "p"} for i in range(5)],
                             defaults={"lvl": 50, "barn": 3000, "silo": 2000, "tools": 3000, "tool_type": "land", "price": "5"})
    return core


async def say(core, cid, *msgs):
    for m in msgs:
        await chat.handle_text(core, await customers.get(core, cid), m)


async def last_texts(core, cid, n=1):
    return [r["content"] for r in await core.pool.fetch(
        "SELECT content FROM messages WHERE customer_id=$1 AND role<>'user' AND kind<>'internal' ORDER BY id DESC LIMIT $2", cid, n)]


async def test_topup_by_code_and_deduct(env):
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    r = await balance.adjust(env, "admin", c["access_code"].lower().replace("hd-", "hd"), "20", "شحن")
    assert r["balance"] == "20.00" and await balance.get(env, c["id"]) == Decimal("20.00")
    assert "تمت إضافة \u2066$20.00\u2069" in (await last_texts(env, c["id"]))[0]
    await balance.adjust(env, "admin", c["access_code"], "-5")
    assert await balance.get(env, c["id"]) == Decimal("15.00")
    with pytest.raises(StoreError):
        await balance.adjust(env, "admin", c["access_code"], "-100")      # never below zero
    with pytest.raises(StoreError):
        await balance.adjust(env, "admin", "HD-NOPE0000", "5")
    assert [x["kind"] for x in await balance.history(env, c["id"])] == ["deduct", "topup"]


async def test_balance_purchase_is_delivered_without_staff(env):
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    await balance.adjust(env, "admin", c["access_code"], "12")
    await say(env, c["id"], "بدي 2 مزارع مستوى 50", "نعم")
    card = await env.pool.fetchrow("SELECT payload FROM messages WHERE customer_id=$1 AND kind='methods'", c["id"])
    assert card and card["payload"]["balance"] == "12.00"                 # balance offered as a way to pay
    await say(env, c["id"], "ادفع من الرصيد")
    o = (await orders.customer_orders(env, c["id"], 1))[0]
    assert o["status"] == "delivered" and await balance.get(env, c["id"]) == Decimal("2.00")
    assert await env.pool.fetchval("SELECT count(*) FROM messages WHERE customer_id=$1 AND kind='delivered'", c["id"]) == 1
    assert await env.pool.fetchval("SELECT count(*) FROM farms WHERE status='sold'") == 2
    assert not await env.pool.fetchval("SELECT 1 FROM payments WHERE order_id=$1", o["id"])   # nothing for staff to review
    with pytest.raises(StoreError):
        await balance.pay_order(env, c["id"], o["id"])                     # never twice
    assert await balance.get(env, c["id"]) == Decimal("2.00")
    assert await env.pool.fetchval("SELECT count(*) FROM balance_log WHERE customer_id=$1 AND kind='order'", c["id"]) == 1


async def test_failed_auto_delivery_waits_for_staff_and_refunds_on_cancel(env, monkeypatch):
    async def broken(*a, **k):
        return False
    monkeypatch.setattr(orders, "deliver", broken)
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    await balance.adjust(env, "admin", c["access_code"], "12")
    await say(env, c["id"], "بدي 2 مزارع مستوى 50", "نعم", "ادفع من الرصيد")
    o = (await orders.customer_orders(env, c["id"], 1))[0]
    assert o["status"] == "processing" and await balance.get(env, c["id"]) == Decimal("2.00")
    await orders.admin_cancel(env, "admin", o["id"], "نفد المخزون")
    assert await balance.get(env, c["id"]) == Decimal("12.00")              # refunded once
    assert await env.pool.fetchval("SELECT count(*) FROM farms WHERE status='available'") == 5
    with pytest.raises(StoreError):
        await orders.admin_cancel(env, "admin", o["id"], "مرة ثانية")
    assert await balance.get(env, c["id"]) == Decimal("12.00")


async def test_two_orders_cannot_spend_the_same_balance(env):
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    await balance.adjust(env, "admin", c["access_code"], "10")
    ids = []
    for _ in range(2):
        o = await orders.prepare(env, c["id"], (await farms.search_offers(env))[0]["offer_code"], 2)
        await orders.confirm(env, c["id"], o["id"])
        ids.append(o["id"])
    import asyncio
    res = await asyncio.gather(*(balance.pay_order(env, c["id"], i) for i in ids), return_exceptions=True)
    assert sum(isinstance(x, StoreError) for x in res) == 1                 # 10 covers only one 10.00 order
    assert await balance.get(env, c["id"]) == Decimal("0.00")


async def test_not_enough_balance(env):
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    await balance.adjust(env, "admin", c["access_code"], "3")
    await say(env, c["id"], "بدي 2 مزارع مستوى 50", "نعم")
    assert not await env.pool.fetchval("SELECT payload->>'balance' FROM messages WHERE customer_id=$1 AND kind IN ('methods','pay_details') LIMIT 1", c["id"])
    await say(env, c["id"], "ادفع من الرصيد")
    msg = (await last_texts(env, c["id"]))[0]
    assert "لا يكفي" in msg and "ينقصك $7.00" in msg
    assert await balance.get(env, c["id"]) == Decimal("3.00")
    assert (await orders.customer_orders(env, c["id"], 1))[0]["status"] == "awaiting_payment"


async def test_ask_balance_in_chat(env):
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    await balance.adjust(env, "admin", c["access_code"], "7.5")
    await say(env, c["id"], "كم رصيدي؟")
    assert "رصيدك المتوفر: \u2066$7.50\u2069" in (await last_texts(env, c["id"]))[0]


async def test_app_and_panel_endpoints(env):
    from app.services import admins
    client = Client(create_app(env))
    code = (await customers.create_codes(env, "t", 1, "x"))[0]["access_code"]
    user = AppUser(client, (await login(client, code)).json()["data"]["token"])
    assert (await user.get("/me")).json()["data"]["balance"] == "0.00"
    await admins.create_admin(env, "test", "boss", "StrongPass123", "owner")
    panel = Client(create_app(env))
    await panel.post("/api/auth/login", {"username": "boss", "password": "StrongPass123"}, csrf=False)
    r = await panel.post("/api/balance", {"code": code, "amount": "25", "note": "تحويل"})
    assert r.status_code == 200, r.text
    assert (await user.messages())["balance"] == "25.00"
    b = (await user.get("/balance")).json()["data"]
    assert b["balance"] == "25.00" and b["items"][0]["kind"] == "topup"
    await user.post("/messages", {"text": "بدي 3 مزارع مستوى 50"})
    await user.post("/messages", {"text": "نعم"})
    oid = (await orders.customer_orders(env, (await env.pool.fetchval("SELECT id FROM customers WHERE access_code=$1", code)), 1))[0]["id"]
    r = await user.post(f"/orders/{oid}/pay-balance")
    assert r.status_code == 200 and r.json()["data"]["balance"] == "10.00"
    assert (await user.post(f"/orders/{oid}/pay-balance")).status_code == 400
