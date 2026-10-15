"""Every way a customer asks to buy, and growing one order with more types across messages."""
import pytest

from app.messenger import AppMessenger
from app.services import farms
from tests.test_rules import talk

ASK = "ما مواصفات"


@pytest.fixture
async def env(core):
    core.config.anthropic_api_key = ""
    core.messenger = AppMessenger(core)
    for t in ("land", "barn"):
        await farms.import_farms(core, "t", [{"line": i, "token_id": f"{t}-{i}", "password": "p"} for i in range(4)],
                                 defaults={"lvl": 50, "barn": 3000, "silo": 1000, "tools": 3000, "tool_type": t, "price": "5"})
    await farms.import_farms(core, "t", [{"line": 0, "token_id": "s-0", "password": "p"}],
                             defaults={"lvl": 50, "barn": 5000, "silo": 2000, "tools": 5000, "tool_type": "silo", "price": "7"})
    return core


@pytest.mark.parametrize("msg,n", [("بدي مزرعه واحدة", "مزرعة واحدة"), ("بدي 1 مزرعه", "مزرعة واحدة"), ("اريد مزرعة", "مزرعة واحدة"),
                                   ("ممكن مزرعة", "مزرعة واحدة"), ("مزرعة وحدة لو سمحت", "مزرعة واحدة"),
                                   ("بدي مزرعتين", "مزرعتان"), ("بدي ثلاث مزارع", "3 مزارع"), ("حابب اشتري مزرعة", "مزرعة واحدة")])
async def test_quantity_is_understood_and_repeated_back(env, msg, n):
    r, _, _ = await talk(env, [msg])
    assert f"تمام، {n} 👍 ما مواصفاتها" in r[0]


@pytest.mark.parametrize("msg", ["بدي مزارع", "بدي شراء مزارع", "بدي اشتري مزارع", "عندكم مزارع للبيع؟", "شراء", "ابي اشتري",
                                 "بدي اشتري", "مزارع", "اريد شراء مزارع", "ودي اشتري مزارع"])
async def test_buy_intent(env, msg):
    r, _, _ = await talk(env, [msg])
    assert ASK in r[0]


@pytest.mark.parametrize("msg", ["بكم المزرعة", "السعر", "كم سعر المزارع"])
async def test_price_question_asks_for_specs(env, msg):
    r, _, _ = await talk(env, [msg])
    assert "السعر يعتمد على مواصفات المزرعة" in r[0]


async def test_bare_number_after_specs_question_is_the_level(env):
    r, o, _ = await talk(env, ["بدي مزرعه واحدة", "50", "حظيرة"])
    assert "ما نوع الأدوات" in r[1]
    assert o["status"] == "pending_confirmation" and o["quantity"] == 1 and str(o["total"]) == "5.00"


@pytest.mark.parametrize("answer,qty", [("2", 2), ("اثنين", 2), ("وحدة", 1), ("2 مزارع", 2), ("ثلاث", 3)])
async def test_quantity_answers(env, answer, qty):
    r, o, _ = await talk(env, ["بدي مزارع", "مستوى 50 ادوات ارض", answer])
    assert "كم مزرعة" in r[1] and o["quantity"] == qty


@pytest.mark.parametrize("first,second", [
    ("بدي 2 مزارع مستوى 50 ادوات ارض", "وكمان 1 ادوات حظيرة"),
    ("بدي 2 مزارع مستوى 50 ادوات ارض", "واضف 1 حظيرة"),
    ("بدي 2 مزارع مستوى 50 ادوات ارض", "بدي كمان مزرعة حظيرة"),
    ("بدي 2 مزارع مستوى 50 ادوات ارض", "ضيف مزرعة حظيرة للطلب"),
])
async def test_add_a_type_to_the_order(env, first, second):
    r, o, cid = await talk(env, [first, second])
    assert o["quantity"] == 3 and str(o["total"]) == "15.00"
    assert sorted(ln["offer"]["tool_type"] for ln in o["lines"]) == ["barn", "land"]
    assert await env.pool.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1 AND status='pending_confirmation'", cid) == 1


async def test_add_a_type_with_other_capacities(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 50 ادوات ارض", "وكمان مزرعة صومعة"])
    assert str(o["total"]) == "17.00" and o["quantity"] == 3          # 2×5 + 1×7 (silo type has its own barn size)


async def test_add_without_number_asks_how_many(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 50 ادوات ارض", "كمان حظيرة", "2", "نعم"])
    assert "كم مزرعة تضيف من أدوات حظيرة" in r[1]
    assert o["status"] == "awaiting_payment" and o["quantity"] == 4 and str(o["total"]) == "20.00"


async def test_add_more_of_the_same_type(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 50 ادوات ارض", "زيد 1 ارض"])
    assert o["quantity"] == 3 and len(o["lines"]) == 1


async def test_add_more_than_stock(env):
    r, o, _ = await talk(env, ["بدي 2 مزارع مستوى 50 ادوات ارض", "وكمان 9 حظيرة"])
    assert "طلبت 9 والمتوفر 4" in r[1]
    assert o["quantity"] == 2                                          # the order on the table is kept


@pytest.mark.parametrize("msg", ["بدي 2 ارض و 1 حظيرة مستوى 50", "بدي مزرعتين ارض ومزرعة حظيرة مستوى 50", "2 ارض 1 حظيرة",
                                 "2 land 1 barn", "مزرعتين ارض، مزرعة حظيرة"])
async def test_several_types_in_one_message(env, msg):
    r, o, _ = await talk(env, [msg])
    assert o["quantity"] == 3 and str(o["total"]) == "15.00"


async def test_english_add(env):
    r, o, _ = await talk(env, ["i want 2 farms level 50 land tools", "also 1 barn"], "en")
    assert o["quantity"] == 3
