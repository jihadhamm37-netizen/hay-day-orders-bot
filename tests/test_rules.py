"""Free built-in assistant v2 (no AI key): context-aware conversations in many phrasings and 4 languages."""
from __future__ import annotations

import pytest

from app.messenger import AppMessenger
from app.services import chat, customers, farms, orders, rules


def test_parse():
    assert rules.parse("اريد 5 مزارع مستوى 50 مخزن 3000 ادوات ارض 3000") == {"lvl": 50, "barn": 3000, "tools": 3000, "qty": 5, "tool_type": "land"}
    assert rules.parse("ابي مزرعتين لفل ١٠٠ صومعة 2k") == {"lvl": 100, "silo": 2000, "qty": 2}
    assert rules.parse("I want 3 farms level 80 barn 10,000") == {"lvl": 80, "barn": 10000, "qty": 3}
    assert rules.parse("ابغى مزرعه مستوا 50") == {"lvl": 50, "qty": 1}
    assert rules.parse("tôi muốn mua 2 nông trại cấp 50") == {"lvl": 50, "qty": 2}
    assert rules.parse("我要三个农场") == {"qty": 3}
    assert rules.bare_number("بدي 3") == 3 and rules.bare_number("مستوى 50") is None


@pytest.fixture
async def env(core):
    core.config.anthropic_api_key = ""
    core.messenger = AppMessenger(core)
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"A{i}", "password": "p"} for i in range(20)],
                             defaults={"lvl": 50, "barn": 3000, "silo": 2000, "tools": 3000, "price": "4"})
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"B{i}", "password": "p"} for i in range(20)],
                             defaults={"lvl": 100, "barn": 10000, "silo": 3000, "tools": 10000, "price": "10"})
    return core


async def talk(core, msgs, lang="ar"):
    c = (await customers.create_codes(core, "t", 1, "x"))[0]
    await core.pool.execute("UPDATE customers SET lang=$2 WHERE id=$1", c["id"], lang)
    replies = []
    for m in msgs:
        await chat.handle_text(core, await customers.get(core, c["id"]), m)
        replies.append(await core.pool.fetchval(
            "SELECT content FROM messages WHERE customer_id=$1 AND role='assistant' ORDER BY id DESC LIMIT 1", c["id"]) or "")
    last = (await orders.customer_orders(core, c["id"], 1) or [None])[0]
    return replies, last, c["id"]


# the exact conversation from the brief
async def test_brief_conversation(env):
    r, o, _ = await talk(env, ["مرحبا", "بدي مزارع.", "بدي 3 مزارع.", "1", "نعم"])
    assert "أهلاً وسهلاً" in r[0] and "كيف أقدر أساعدك" in r[0]
    assert "كم مزرعة" in r[1]
    assert "ما نوع المزارع" in r[2] and "1)" in r[2]
    assert "3 مزارع" in r[3] and "4.00" in r[3] and "12.00" in r[3] and "تؤكد" in r[3]
    assert o["status"] == "awaiting_payment" and o["quantity"] == 3


@pytest.mark.parametrize("opening", ["أريد مزارع", "بدي مزارع", "احتاج مزارع", "عندك مزارع؟", "هاتلي مزارع", "ابغى مزارع",
                                     "عايز مزارع", "عندكم فارمات", "اريد اشتري مزارع"])
async def test_many_ways_to_ask(env, opening):
    r, o, _ = await talk(env, [opening, "بدي 3", "الثاني", "اكيد"])
    assert "كم مزرعة" in r[0]
    assert "ما نوع" in r[1]
    assert "30.00" in r[2]
    assert o["status"] == "awaiting_payment" and o["quantity"] == 3 and o["offer"]["lvl"] == 100


async def test_one_message_with_everything(env):
    r, o, _ = await talk(env, ["أريد ثلاث مزارع مستوى 50 مخزن 3000 أدوات أرض 3000", "تمام"])
    assert "12.00" in r[0]
    assert o["status"] == "awaiting_payment"


async def test_change_quantity_and_type_recalculates(env):
    r, o, cid = await talk(env, ["هاتلي ثلاث مزارع لفل ١٠٠", "لا خليها 2", "لا بدي مستوى 50", "زين"])
    assert "30.00" in r[0]
    assert "20.00" in r[1]
    assert "8.00" in r[2]
    assert o["status"] == "awaiting_payment" and o["quantity"] == 2 and o["offer"]["lvl"] == 50
    # older unconfirmed quotes were replaced, never reserved
    assert await env.pool.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1 AND status='awaiting_payment'", cid) == 1


async def test_no_order_without_explicit_yes(env):
    r, o, cid = await talk(env, ["بدي 2 مزارع مستوى 50", "شكد السعر؟", "كيف ادفع"])
    assert o["status"] == "pending_confirmation"
    assert await env.pool.fetchval("SELECT count(*) FROM farms WHERE status='reserved'") == 0


async def test_cancel(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 50", "لا"])
    assert "إلغاء" in r[1] and o["status"] == "cancelled"


async def test_typos_and_dialects(env):
    r, o, _ = await talk(env, ["مرحبااااا", "ابغى مزرعه مستوا 50", "يس"])
    assert "أهلاً" in r[0] and "4.00" in r[1] and o["status"] == "awaiting_payment"


async def test_unclear_asks_simple_question(env):
    r, _, _ = await talk(env, ["ششش"])
    assert "تقصد تشتري مزارع" in r[0]


async def test_complaint_goes_to_staff(env):
    _, _, cid = await talk(env, ["المزرعة ما تشتغل"])
    assert await env.pool.fetchval("SELECT ai_paused FROM customers WHERE id=$1", cid)


async def test_discount_is_not_a_complaint(env):
    r, _, cid = await talk(env, ["سويلي خصم"])
    assert "ثابتة" in r[0] and not await env.pool.fetchval("SELECT ai_paused FROM customers WHERE id=$1", cid)


async def test_more_than_stock(env):
    r, _, _ = await talk(env, ["بدي 50 مزرعة مستوى 50"])
    assert "20" in r[0] and "فقط" in r[0]


async def test_english(env):
    r, o, _ = await talk(env, ["hi", "i need some farms", "3", "level 100", "yes"], "en")
    assert "Welcome" in r[0] and "How many" in r[1] and "30.00" in r[3] and o["status"] == "awaiting_payment"


async def test_vietnamese(env):
    r, o, _ = await talk(env, ["xin chào", "tôi muốn mua 2 nông trại cấp 50", "có"], "vi")
    assert "Chào mừng" in r[0] and "8.00" in r[1] and o["status"] == "awaiting_payment"


async def test_chinese(env):
    r, o, _ = await talk(env, ["你好", "我要三个农场", "1", "确认"], "zh")
    assert "欢迎" in r[0] and "12.00" in r[2] and o["status"] == "awaiting_payment"


async def test_same_specs_different_tool_types(core):
    core.config.anthropic_api_key = ""
    core.messenger = AppMessenger(core)
    base = {"lvl": 60, "barn": 3000, "silo": 3000, "tools": 3000, "price": "5"}
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"L{i}", "password": "p"} for i in range(3)], defaults={**base, "tool_type": "land"})
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"B{i}", "password": "p"} for i in range(3)], defaults={**base, "tool_type": "barn"})
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"S{i}", "password": "p"} for i in range(3)], defaults={**base, "tool_type": "silo"})
    offers = await farms.search_offers(core)
    assert sorted(o["tool_type"] for o in offers) == ["barn", "land", "silo"]
    # asking without the tool type → the assistant lists the 3 types
    r, _, _ = await talk(core, ["بدي 2 مزارع مستوى 60"])
    assert "أدوات أرض" in r[0] and "أدوات حظيرة" in r[0] and "أدوات صومعة" in r[0]
    # asking with the tool type → exact farms get reserved
    r, o, _ = await talk(core, ["بدي 2 مزارع مستوى 60 ادوات حظيرة", "نعم"])
    assert "أدوات حظيرة" in r[0] and o["status"] == "awaiting_payment"
    ids = [x["farm_id"] for x in (await orders.get_order(core, o["id"]))["items"]]
    toks = await core.pool.fetch("SELECT tool_type FROM farms WHERE id = ANY($1::bigint[])", ids)
    assert {t["tool_type"] for t in toks} == {"barn"}
    # follow-up by type word only
    r, o, _ = await talk(core, ["بدي 1 مستوى 60", "صومعه", "اي"])
    assert "أدوات صومعة" in r[1] and o["status"] == "awaiting_payment"


@pytest.fixture
async def typed(core):
    core.config.anthropic_api_key = ""
    core.messenger = AppMessenger(core)
    base = {"lvl": 50, "barn": 3000, "silo": 2000, "tools": 3000}
    for t, price in (("land", "5"), ("barn", "6"), ("silo", "7")):
        await farms.import_farms(core, "t", [{"line": i, "token_id": f"{t}{i}", "password": "p"} for i in range(5)],
                                 defaults={**base, "tool_type": t, "price": price})
    return core


async def test_two_types_in_one_message(typed):
    core = typed
    r, o, cid = await talk(core, ["بدي 2 مزارع مستوى 50 مخزن 3000 ادوات ارض و 2 مزارع مستوى 50 مخزن 3000 ادوات حظيرة"])
    assert "ملخص" in r[0] or "جهزت" in r[0]
    assert o["status"] == "pending_confirmation" and o["quantity"] == 4 and str(o["total"]) == "22.00"   # 2×5 + 2×6
    card = await core.pool.fetchrow("SELECT content, payload FROM messages WHERE customer_id=$1 AND kind='order_summary' "
                                    "ORDER BY id DESC LIMIT 1", cid)
    assert "النوع الأول" in card["content"] and "النوع الثاني" in card["content"] and "أدوات حظيرة" in card["content"]
    assert [ln["tool_type"] for ln in card["payload"]["lines"]] == ["land", "barn"]
    assert await core.pool.fetchval("SELECT count(*) FROM farms WHERE status='reserved'") == 0      # nothing before yes


async def test_two_types_confirm_reserves_exact_farms(typed):
    core = typed
    r, o, cid = await talk(core, ["ابي 2 ادوات ارض و 3 ادوات صومعه مستوى 50", "نعم"])
    assert o["status"] == "awaiting_payment" and str(o["total"]) == "31.00"   # 2×5 + 3×7
    rows = await core.pool.fetch("SELECT f.tool_type, count(*) n FROM order_items i JOIN farms f ON f.id=i.farm_id "
                                 "WHERE i.order_id=$1 GROUP BY 1", o["id"])
    assert {x["tool_type"]: x["n"] for x in rows} == {"land": 2, "silo": 3}


async def test_edit_one_type_recalculates(typed):
    core = typed
    r, o, cid = await talk(core, ["2 land tools and 2 barn tools level 50", "خلي الحظيره 4", "احذف الارض", "yes"], "ar")
    assert "22.00" not in r[1]
    last = await core.pool.fetch("SELECT total, quantity, status FROM orders WHERE customer_id=$1 ORDER BY id", cid)
    assert str(last[1]["total"]) == "34.00"      # 2×5 + 4×6 after the change
    assert last[-1]["status"] == "awaiting_payment" and str(last[-1]["total"]) == "24.00" and last[-1]["quantity"] == 4


async def test_edit_button_then_change(typed):
    from app.services import chat as chat_svc
    core = typed
    r, o, cid = await talk(core, ["بدي 2 مزارع مستوى 50 ادوات ارض"])
    await chat_svc.edit_order(core, await customers.get(core, cid), o["id"])
    assert (await orders.get_order(core, o["id"]))["status"] == "cancelled"
    await chat.handle_text(core, await customers.get(core, cid), "خليها 3")
    o2 = (await orders.customer_orders(core, cid, 1))[0]
    assert o2["status"] == "pending_confirmation" and o2["quantity"] == 3 and str(o2["total"]) == "15.00"


async def test_multi_order_payment_and_delivery(typed):
    from app.services import payments
    core = typed
    r, o, cid = await talk(core, ["ابي 1 ادوات ارض و 1 ادوات حظيره مستوى 50", "اكيد"])
    res = await payments.submit_proof(core, cid, "db", "uniq-proof-1", image=b"\xff\xd8\xffx", mime="image/jpeg")
    assert (await orders.get_order(core, o["id"]))["status"] == "payment_review"     # waits for staff, no success yet
    msgs = " ".join(x["content"] for x in await core.pool.fetch("SELECT content FROM messages WHERE customer_id=$1", cid))
    assert "Password" not in msgs
    await payments.approve(core, "admin", res["payment"]["id"])
    assert (await orders.get_order(core, o["id"]))["status"] == "delivered"
