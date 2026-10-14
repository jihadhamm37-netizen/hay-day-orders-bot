"""HD Agent free assistant — the full sales conversation from the spec, in many phrasings and 4 languages."""
from __future__ import annotations

import pytest

from app.messenger import AppMessenger
from app.services import chat, customers, farms, orders, payments, rules


# ------------------------------------------------------------------ parsing
def test_parse():
    assert rules.parse("اريد 5 مزارع مستوى 50 مخزن 3000 ادوات ارض 3000") == {"lvl": 50, "barn": 3000, "tools": 3000, "qty": 5, "tool_type": "land"}
    assert rules.parse("ابي مزرعتين لفل ١٠٠ صومعة 2k") == {"lvl": 100, "silo": 2000, "qty": 2}
    assert rules.parse("I want 3 farms level 80 barn 10,000") == {"lvl": 80, "barn": 10000, "qty": 3}
    assert rules.parse("ابغى مزرعه مستوا 50") == {"lvl": 50, "qty": 1}
    assert rules.parse("tôi muốn mua 2 nông trại cấp 50") == {"lvl": 50, "qty": 2}
    assert rules.parse("我要三个农场") == {"qty": 3}
    assert rules.parse("بدي 2 مزارع مستوى 60 ادوات حظيرة") == {"tool_type": "barn", "lvl": 60, "qty": 2}
    assert rules.parse("اجعل عدد مزارع الارض 4") == {"tool_type": "land", "qty": 4}
    assert rules.bare_number("بدي 3") == 3 and rules.bare_number("مستوى 50") is None


def test_split_several_types():
    assert rules.split_lines("2 مزارع مستوى 50 مخزن 3000 ادوات ارض و 3 مزارع مستوى 50 مخزن 3000 ادوات حظيرة") == [
        {"lvl": 50, "barn": 3000, "tool_type": "land", "qty": 2}, {"lvl": 50, "barn": 3000, "tool_type": "barn", "qty": 3}]
    assert len(rules.split_lines("2 ادوات ارض\n3 ادوات صومعه مستوى 50")) == 2
    assert len(rules.split_lines("2 land tools and 3 barn tools level 50")) == 2
    assert len(rules.split_lines("我要两个农场 等级50 土地工具，三个农场 仓库工具")) == 2
    assert rules.split_lines("بدي 3 مزارع مستوى 50") == []


# ------------------------------------------------------------------ stock used by the conversations
@pytest.fixture
async def env(core):
    core.config.anthropic_api_key = ""          # free assistant, no AI subscription
    core.messenger = AppMessenger(core)
    base50 = {"lvl": 50, "barn": 3000, "silo": 2000, "tools": 3000}
    for t, price, n in (("land", "5", 10), ("barn", "6", 10), ("silo", "7", 5)):
        await farms.import_farms(core, "t", [{"line": i, "token_id": f"{t}50-{i}", "password": f"pw{i}"} for i in range(n)],
                                 defaults={**base50, "tool_type": t, "price": price})
    await farms.import_farms(core, "t", [{"line": i, "token_id": f"L100-{i}", "password": "p"} for i in range(6)],
                             defaults={"lvl": 100, "barn": 10000, "silo": 3000, "tools": 10000, "tool_type": "land", "price": "10"})
    return core


async def talk(core, msgs, lang="ar"):
    c = (await customers.create_codes(core, "t", 1, "x"))[0]
    await core.pool.execute("UPDATE customers SET lang=$2 WHERE id=$1", c["id"], lang)
    replies = []
    for m in msgs:
        last = await core.pool.fetchval("SELECT coalesce(max(id),0) FROM messages")
        await chat.handle_text(core, await customers.get(core, c["id"]), m)
        replies.append("\n".join(r["content"] for r in await core.pool.fetch(
            "SELECT content FROM messages WHERE customer_id=$1 AND id>$2 AND role<>'user' AND kind<>'internal' ORDER BY id",
            c["id"], last)))
    last_order = (await orders.customer_orders(core, c["id"], 1) or [None])[0]
    return replies, last_order, c["id"]


# 1) greeting
@pytest.mark.parametrize("hi", ["مرحبا", "السلام عليكم", "هلو", "كيف الحال", "hi", "مرحبااااا"])
async def test_welcome(env, hi):
    r, o, _ = await talk(env, [hi])
    assert ("أنا هنا لمساعدتك" in r[0]) or ("I'm here to help" in r[0])
    assert o is None


# 2-3) collect specs (only the missing ones), then the quantity
async def test_specs_then_quantity_step_by_step(env):
    r, o, _ = await talk(env, ["بدي مزارع", "مستوى 50", "حظيرة", "3", "نعم"])
    assert "ما مواصفات المزارع" in r[0]
    assert "1)" not in r[0] and "المتوفر الآن" not in r[0]              # stock list is never shown
    assert "متوفر 10" not in r[2] and "(متوفر" not in r[2]
    assert "ما نوع الأدوات" in r[1] and "أدوات حظيرة" in r[1]          # level known → asks only the tool type
    assert "كم مزرعة تحتاج من هذا النوع" in r[2]
    assert "ملخص الطلب" in r[3] and "18.00" in r[3] and "«نعم»" in r[3]   # 3 × 6
    assert "تم تأكيد طلبك" in r[4] and o["status"] == "awaiting_payment" and o["quantity"] == 3


@pytest.mark.parametrize("opening", ["أريد شراء مزارع", "بدي مزارع", "احتاج مزارع", "عندك مزارع؟", "هاتلي مزارع",
                                     "ابغى مزارع", "عايز مزارع", "عندكم فارمات", "I want to buy farms"])
async def test_many_ways_to_start(env, opening):
    r, _, _ = await talk(env, [opening])
    assert ("ما مواصفات" in r[0]) or ("Which farms do you need" in r[0])


async def test_everything_in_one_message(env):
    r, o, _ = await talk(env, ["أريد 10 مزارع مستوى 50 مخزن 3000 أدوات أرض"])
    assert "50.00" in r[0] and o["status"] == "pending_confirmation" and o["quantity"] == 10   # 10 × 5, no questions


async def test_quantity_first_then_specs(env):
    r, o, _ = await talk(env, ["بدي 3 مزارع", "مستوى 100"])
    assert "ما مواصفات" in r[0]
    assert "30.00" in r[1] and o["quantity"] == 3                       # quantity remembered, not asked again


# 4) real stock
async def test_shortage_asks_without_changing_quantity(env):
    r, o, cid = await talk(env, ["بدي 10 مزارع مستوى 100", "6", "نعم"])
    assert "طلبت 10 مزارع، والمتوفر في المخزون 6 مزارع فقط" in r[0]
    assert "60.00" in r[1]
    assert o["status"] == "awaiting_payment" and o["quantity"] == 6


async def test_type_not_available(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 70"])
    assert "غير متوفر حاليًا" in r[0] and "اكتب مواصفات نوع آخر" in r[0] and o is None
    assert "1)" not in r[0] and "5.00" not in r[0]


# 5-6) prices, several types, summary, confirmation, edits
async def test_two_types_price_31(env):
    r, o, cid = await talk(env, ["بدي مزرعتين مستوى 50 مخزن 3000 أدوات أرض، و3 مزارع مستوى 50 مخزن 3000 أدوات صومعة"])
    assert o["status"] == "pending_confirmation" and str(o["total"]) == "31.00" and o["quantity"] == 5
    card = await env.pool.fetchval("SELECT content FROM messages WHERE customer_id=$1 AND kind='order_summary' ORDER BY id DESC LIMIT 1", cid)
    assert "النوع الأول" in card and "النوع الثاني" in card and "إجمالي المزارع: 5 مزارع" in card and "31.00" in card
    assert await env.pool.fetchval("SELECT count(*) FROM farms WHERE status='reserved'") == 0


async def test_multi_shortage_then_fix(env):
    r, o, _ = await talk(env, ["2 ادوات ارض و 8 ادوات صومعه مستوى 50", "اجعل عدد مزارع الصومعة 5", "اوافق"])
    assert "طلبت 8 والمتوفر 5" in r[0]
    assert "45.00" in r[1]                                               # 2×5 + 5×7
    assert o["status"] == "awaiting_payment" and o["quantity"] == 7


async def test_edit_word_then_remove_a_type(env):
    r, o, _ = await talk(env, ["2 مزارع مستوى 50 ادوات ارض و 2 مزارع مستوى 50 ادوات حظيرة", "تعديل", "احذف مزارع الحظيرة"])
    assert "شو تحب تعدّل" in r[1]
    assert "10.00" in r[2] and o["status"] == "pending_confirmation" and o["quantity"] == 2


async def test_edit_quantity_recalculates(env):
    r, o, _ = await talk(env, ["هاتلي ثلاث مزارع لفل ١٠٠", "لا خليها 2"])
    assert "30.00" in r[0] and "20.00" in r[1] and o["quantity"] == 2


async def test_small_talk_is_not_a_confirmation(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 100", "شكرا", "مرحبا", "كيف الحال"])
    assert o["status"] == "pending_confirmation"
    assert await env.pool.fetchval("SELECT count(*) FROM farms WHERE status='reserved'") == 0


async def test_no_cancels(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 100", "لا"])
    assert "إلغاء" in r[1] and o["status"] == "cancelled"


async def test_dialects_and_typos(env):
    r, o, _ = await talk(env, ["ابغى مزرعه مستوا 100", "يس"])
    assert "10.00" in r[0] and o["status"] == "awaiting_payment"
    r, o, _ = await talk(env, ["شلونكم، عدكم مزارع لفل ١٠٠؟", "بدي 2", "اي"])
    assert "كم مزرعة" in r[0] and "20.00" in r[1] and o["status"] == "awaiting_payment"


# 8) proof in the chat — screenshot or typed transaction number
async def test_typed_transaction_number_goes_to_review(env):
    r, o, cid = await talk(env, ["بدي 2 مزارع مستوى 100", "نعم", "رقم العملية: 403829110293847"])
    assert "تم استلام إثبات الدفع بنجاح" in r[2] and "قيد مراجعة الدفع" in r[2]
    o = await orders.get_order(env, o["id"])
    assert o["status"] == "payment_review"
    assert "نجح" not in r[2] and "Password" not in r[2]


# 9) review → preparation → staff delivery, never twice
async def test_review_preparation_delivery(env):
    r, o, cid = await talk(env, ["2 ادوات ارض و 1 ادوات حظيره مستوى 50", "نعم"])
    res = await payments.submit_proof(env, cid, "db", "proof-xyz", image=b"\xff\xd8\xff1", mime="image/jpeg")
    assert (await orders.get_order(env, o["id"]))["status"] == "payment_review"
    await payments.approve(env, "admin", res["payment"]["id"])
    o2 = await orders.get_order(env, o["id"])
    assert o2["status"] == "processing"                                  # being prepared — nothing sent yet
    assert not await env.pool.fetchval("SELECT 1 FROM messages WHERE customer_id=$1 AND kind='delivered'", cid)
    assert await orders.deliver(env, o["id"], "admin")
    assert not await orders.deliver(env, o["id"], "admin")
    o3 = await orders.get_order(env, o["id"])
    assert o3["status"] == "delivered"
    rows = await env.pool.fetch("SELECT f.tool_type, f.status FROM order_items i JOIN farms f ON f.id=i.farm_id WHERE i.order_id=$1", o["id"])
    assert sorted(x["tool_type"] for x in rows) == ["barn", "land", "land"] and {x["status"] for x in rows} == {"sold"}
    assert await env.pool.fetchval("SELECT count(*) FROM messages WHERE customer_id=$1 AND kind='delivered'", cid) == 1


async def test_complaint_goes_to_staff_only_when_needed(env):
    _, _, cid = await talk(env, ["المزرعة ما تشتغل"])
    assert await env.pool.fetchval("SELECT ai_paused FROM customers WHERE id=$1", cid)
    r, _, cid = await talk(env, ["سويلي خصم"])
    assert "ثابتة" in r[0] and not await env.pool.fetchval("SELECT ai_paused FROM customers WHERE id=$1", cid)


async def test_unclear(env):
    r, _, _ = await talk(env, ["ششش"])
    assert "تقصد تشتري مزارع" in r[0]


# other languages
async def test_english(env):
    r, o, _ = await talk(env, ["hello", "i need farms", "level 100", "2", "yes"], "en")
    assert "Welcome" in r[0] and "Which farms" in r[1] and "How many" in r[2] and "Order summary" in r[3]
    assert o["status"] == "awaiting_payment" and str(o["total"]) == "20.00"


async def test_vietnamese(env):
    r, o, _ = await talk(env, ["xin chào", "tôi muốn mua 2 nông trại cấp 100", "có"], "vi")
    assert "Chào mừng" in r[0] and "20.00" in r[1] and o["status"] == "awaiting_payment"


async def test_chinese(env):
    r, o, _ = await talk(env, ["你好", "我要两个农场 等级100", "确认"], "zh")
    assert "欢迎" in r[0] and "20.00" in r[1] and o["status"] == "awaiting_payment"


async def test_memory_kept_for_customer_who_sent_a_proof_before(env):
    """Real chat from the phone: the customer had sent a payment proof earlier, and the assistant forgot
    every answer (asked the quantity again after «3 مزارع», then restarted on «مزرعه واحده»)."""
    c = (await customers.create_codes(env, "t", 1, "x"))[0]
    await env.pool.execute("UPDATE customers SET awaiting='txid:999' WHERE id=$1", c["id"])
    out = []
    for msg in ["بدي مزارع", "ليش", "3 مزارع مستوى 50", "ادوات حضيره", "مزرعه واحده"]:
        last = await env.pool.fetchval("SELECT coalesce(max(id),0) FROM messages")
        await chat.handle_text(env, await customers.get(env, c["id"]), msg)
        out.append("\n".join(x["content"] for x in await env.pool.fetch(
            "SELECT content FROM messages WHERE customer_id=$1 AND id>$2 AND role<>'user' AND kind<>'internal' ORDER BY id", c["id"], last)))
    assert "ما مواصفات" in out[0]
    assert "ما نوع الأدوات" in out[2]
    assert "18.00" in out[3]                                  # 3 remembered → 3 × 6 (barn tools)
    o = (await orders.customer_orders(env, c["id"], 1))[0]
    assert o["quantity"] == 1 and "6.00" in out[4]          # «مزرعه واحده» changes it to 1, no restart
    assert "ما مواصفات" not in out[4]


async def test_shortage_after_tool_type_answer(env):
    r, o, _ = await talk(env, ["8 مزارع مستوى 50", "صومعة"])
    assert "طلبت 8 مزارع، والمتوفر في المخزون 5 مزارع فقط" in r[1]
