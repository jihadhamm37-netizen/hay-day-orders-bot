"""Free built-in assistant (no AI key): understands requests and sells end to end."""
from __future__ import annotations

import pytest

from app.messenger import AppMessenger
from app.services import chat, customers, orders, rules
from tests.conftest import add_farms


def test_parse_specs_and_quantity():
    p = rules.parse("اريد 5 مزارع مستوى 50 مخزن 3000 ادوات ارض 3000")
    assert p == {"lvl": 50, "barn": 3000, "tools": 3000, "qty": 5}
    assert rules.parse("ابي مزرعتين لفل ١٠٠ صومعة 2k") == {"lvl": 100, "silo": 2000, "qty": 2}
    assert rules.parse("I want 3 farms level 80 barn 10,000") == {"lvl": 80, "barn": 10000, "qty": 3}
    assert rules.parse("مستوى 70 وحدة") == {"lvl": 70, "qty": 1}


@pytest.fixture
async def env(core):
    core.config.anthropic_api_key = ""          # no AI subscription
    core.messenger = AppMessenger(core)
    c = (await customers.create_codes(core, "t", 1, "Ali"))[0]
    return core, await customers.get(core, c["id"])


async def say(core, cust, text):
    await chat.handle_text(core, await customers.get(core, cust["id"]), text)
    r = await core.pool.fetchrow("SELECT content FROM messages WHERE customer_id=$1 AND role='assistant' ORDER BY id DESC LIMIT 1",
                                 cust["id"])
    return r["content"] if r else ""


async def test_full_sale_without_ai(env):
    core, cust = env
    await add_farms(core, 7, lvl=50, price="4", prefix="A")
    await core.pool.execute("UPDATE farms SET barn=3000, silo=2000, tools=3000")
    await add_farms(core, 3, lvl=100, price="30", prefix="B")
    reply = await say(core, cust, "اريد 5 مزارع مستوى 50 مخزن 3000 ادوات ارض 3000")
    assert "20.00" in reply and "متأكد" in reply
    o = (await orders.customer_orders(core, cust["id"]))[0]
    assert o["status"] == "pending_confirmation" and o["quantity"] == 5
    reply = await say(core, cust, "نعم")
    o = (await orders.customer_orders(core, cust["id"]))[0]
    assert o["status"] == "awaiting_payment"
    assert await core.pool.fetchval("SELECT count(*) FROM messages WHERE customer_id=$1 AND kind='pay_details'", cust["id"]) == 1


async def test_vague_request_lists_offers_then_pick_by_number(env):
    core, cust = env
    await add_farms(core, 2, lvl=50, price="4", prefix="A")
    await add_farms(core, 3, lvl=100, price="30", prefix="B")
    reply = await say(core, cust, "اريد مزارع")
    assert "1)" in reply and "2)" in reply and "مستوى 50" in reply and "مستوى 100" in reply
    reply = await say(core, cust, "2")
    assert "كم مزرعة" in reply
    reply = await say(core, cust, "3")
    assert "90.00" in reply
    await say(core, cust, "اي")
    assert (await orders.customer_orders(core, cust["id"]))[0]["status"] == "awaiting_payment"


async def test_more_than_stock_and_no_match(env):
    core, cust = env
    await add_farms(core, 2, lvl=50, price="4")
    reply = await say(core, cust, "اريد 5 مزارع مستوى 50")
    assert "المتوفر من هذا العرض 2" in reply
    reply = await say(core, cust, "اريد مزرعة مستوى 200")
    assert "أقرب" in reply


async def test_cancel_and_status_and_payment(env):
    core, cust = env
    await add_farms(core, 2, lvl=50, price="4")
    await say(core, cust, "اريد مزرعتين مستوى 50")
    reply = await say(core, cust, "لا")
    assert "تم إلغاء" in reply
    reply = await say(core, cust, "طلباتي")
    assert "ملغي" in reply or "الطلب ملغي" in reply
    reply = await say(core, cust, "كيف ادفع؟")
    assert "Binance Pay" in reply and "صورة التحويل" in reply


async def test_complaint_goes_to_staff_and_discount_does_not(env):
    core, cust = env
    await add_farms(core, 1)
    await say(core, cust, "المزرعة ما تشتغل عندي مشكلة")
    assert await core.pool.fetchval("SELECT ai_paused FROM customers WHERE id=$1", cust["id"])


async def test_english(env):
    core, cust = env
    await add_farms(core, 3, lvl=80, price="10")
    reply = await say(core, cust, "I want 2 farms level 80")
    assert "20.00" in reply and "sure" in reply
