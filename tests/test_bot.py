"""End-to-end chat flows through the real aiogram dispatcher, with a mocked Telegram API and a scripted AI model."""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.methods import (AnswerCallbackQuery, EditMessageCaption, EditMessageReplyMarkup, EditMessageText, GetMe,
                             SendChatAction, SendDocument, SendMessage, SendPhoto, TelegramMethod)
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User

from app.bot.setup import attach_messenger, create_bot, create_dispatcher
from app.services import ai, orders
from tests.conftest import add_farms, make_customer, paid_flow

NOW = datetime.now(timezone.utc)
_ids = itertools.count(1)
OWNER = 999


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        chat_id = getattr(method, "chat_id", None)
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Store", username="store_bot")
        if isinstance(method, (SendMessage, SendPhoto, SendDocument, EditMessageText, EditMessageCaption)):
            return Message(message_id=next(_ids), date=NOW, chat=Chat(id=chat_id or 1, type="private"),
                           text=getattr(method, "text", None), caption=getattr(method, "caption", None))
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        yield b""

    def sent_to(self, uid):
        return [c for c in self.calls if isinstance(c, (SendMessage, SendPhoto)) and c.chat_id == uid]

    def texts_to(self, uid):
        return [(c.text if isinstance(c, SendMessage) else c.caption) or "" for c in self.sent_to(uid)]


class FakeModel:
    """Scripted Claude: each step receives the API payload and returns content blocks."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.payloads: list[dict] = []

    async def __call__(self, core, payload):
        self.payloads.append(json.loads(json.dumps(payload, default=str)))
        step = self.steps.pop(0)
        return {"content": step(payload) if callable(step) else step}


def tool(name, **inp):
    return {"type": "tool_use", "id": f"tu_{next(_ids)}", "name": name, "input": inp}


def text(t):
    return {"type": "text", "text": t}


def last_tool_result(payload) -> dict:
    return json.loads(payload["messages"][-1]["content"][-1]["content"])


@pytest.fixture
async def env(core, monkeypatch):
    session = MockSession()
    bot = create_bot("123456:TEST-TOKEN", session=session)
    attach_messenger(core, bot)
    dp = create_dispatcher(core, throttle=0)
    model = FakeModel()
    monkeypatch.setattr(ai, "call_api", model)
    return core, bot, dp, session, model


def user(uid):
    return User(id=uid, is_bot=False, first_name=f"U{uid}", username=f"u{uid}", language_code="ar")


async def say(dp, bot, uid, t, reply_to: Message | None = None):
    msg = Message(message_id=next(_ids), date=NOW, chat=Chat(id=uid, type="private"), from_user=user(uid), text=t,
                  reply_to_message=reply_to)
    await dp.feed_update(bot, Update(update_id=next(_ids), message=msg))


async def photo(dp, bot, uid, unique):
    msg = Message(message_id=next(_ids), date=NOW, chat=Chat(id=uid, type="private"), from_user=user(uid),
                  photo=[PhotoSize(file_id="FILE" + unique, file_unique_id=unique, width=100, height=100)])
    await dp.feed_update(bot, Update(update_id=next(_ids), message=msg))


async def press(dp, bot, uid, data):
    msg = Message(message_id=next(_ids), date=NOW, chat=Chat(id=uid, type="private"), text="x",
                  from_user=User(id=1, is_bot=True, first_name="bot"))
    cb = CallbackQuery(id=str(next(_ids)), from_user=user(uid), chat_instance="ci", message=msg, data=data)
    await dp.feed_update(bot, Update(update_id=next(_ids), callback_query=cb))


def buttons(method):
    mk = getattr(method, "reply_markup", None)
    return [b for row in (mk.inline_keyboard if mk and hasattr(mk, "inline_keyboard") else []) for b in row]


def all_buttons(session, uid):
    return [b for c in session.sent_to(uid) for b in buttons(c)]


# ------------------------------------------------------------------ tests
async def test_full_ai_sale_to_delivery(env):
    core, bot, dp, s, model = env
    await add_farms(core, 3)
    model.steps += [
        [text("ثانية أدورلك"), tool("search_farms", min_level=100)],
        lambda p: [tool("prepare_order", offer_code=last_tool_result(p)["offers"][0]["offer_code"], quantity=2)],
        [text("جهزتلك الطلب، أكد من الزر.")],
    ]
    await say(dp, bot, 10, "اريد مزرعتين لفل 100")
    texts = s.texts_to(10)
    assert any("جهزتلك الطلب" in t for t in texts)
    # the system (not the model) shows the official summary with the real total
    confirm = [b for b in all_buttons(s, 10) if b.callback_data and b.callback_data.startswith("o:c:")]
    assert confirm and any("60.00" in t for t in texts)
    # the model saw only tool data — never credentials
    assert "TOK100" not in json.dumps(model.payloads) and "pw0" not in json.dumps(model.payloads)

    # customer answers "yes" in text → model confirms → system sends payment details (single method: no choice step)
    model.steps += [[tool("confirm_order")], [text("تمام، حوّل المبلغ وأرسل صورة التحويل.")]]
    await say(dp, bot, 10, "نعم")
    assert any("1127859028" in t and "60.00" in t for t in s.texts_to(10))
    await photo(dp, bot, 10, "proofA")   # screenshot only, no transaction number
    o = (await orders.customer_orders(core, 10))[0]
    assert o["status"] == "payment_review"

    review = [c for c in s.sent_to(OWNER) if any((b.callback_data or "").startswith("a:pa:") for b in buttons(c))]
    assert review, "admin must receive the proof with approve/reject buttons"
    approve = [b for b in buttons(review[-1]) if b.callback_data.startswith("a:pa:")][0]
    await press(dp, bot, OWNER, approve.callback_data)
    o = (await orders.customer_orders(core, 10))[0]
    assert o["status"] == "delivered"
    creds = [t for t in s.texts_to(10) if "TOK100-0" in t]
    assert creds and "TOK100-1" in creds[0] and "pw1" in creds[0]   # one list with all farms
    # credentials never stored in the chat log
    logged = " ".join(r["content"] for r in await core.pool.fetch("SELECT content FROM messages"))
    assert "TOK100-0" not in logged and "pw0" not in logged


async def test_customer_cannot_approve_payment(env):
    core, bot, dp, s, model = env
    await add_farms(core, 1)
    await make_customer(core, 10)
    o, p = await paid_flow(core, 10)
    await press(dp, bot, 10, f"a:pa:{p['id']}")
    assert (await orders.get_order(core, o["id"]))["status"] == "payment_review"
    assert core.pool and not [t for t in s.texts_to(10) if "TOK100" in t]


async def test_handoff_pauses_ai_and_staff_reply_relays(env):
    core, bot, dp, s, model = env
    model.steps += [[tool("handoff_to_human", reason="العميل يطلب خصم")], [text("راح يرد عليك أحد من الإدارة قريباً.")]]
    await say(dp, bot, 11, "سويلي خصم")
    c = await core.pool.fetchrow("SELECT ai_paused FROM customers WHERE id=11")
    assert c["ai_paused"]
    staff = [c for c in s.sent_to(OWNER) if "#c11" in (c.text or c.caption or "")]
    assert staff
    # next customer message goes to staff, not to the model
    n = len(model.payloads)
    await say(dp, bot, 11, "وينكم؟")
    assert len(model.payloads) == n
    assert sum("#c11" in (c.text or "") for c in s.sent_to(OWNER)) >= 2
    # staff answers with Reply → relayed to the customer
    fwd = Message(message_id=5, date=NOW, chat=Chat(id=OWNER, type="private"), text=staff[-1].text,
                  from_user=User(id=1, is_bot=True, first_name="bot"))
    await say(dp, bot, OWNER, "أهلاً، شلون أكدر أساعدك؟", reply_to=fwd)
    assert any("شلون أكدر أساعدك" in t for t in s.texts_to(11))
    assert await core.pool.fetchval("SELECT count(*) FROM messages WHERE customer_id=11 AND role='admin'") == 1


async def test_ai_error_hands_off(env, monkeypatch):
    core, bot, dp, s, model = env

    async def boom(core, payload):
        raise RuntimeError("API 529 overloaded")
    monkeypatch.setattr(ai, "call_api", boom)
    await say(dp, bot, 12, "hello")
    assert await core.pool.fetchval("SELECT ai_paused FROM customers WHERE id=12")
    assert s.texts_to(12)
    assert await core.pool.fetchval("SELECT count(*) FROM alerts WHERE kind='ai_error'") == 1


async def test_no_api_key_forwards_to_staff(env):
    core, bot, dp, s, model = env
    core.config.anthropic_api_key = ""
    await say(dp, bot, 13, "مرحبا")
    assert model.payloads == []
    assert any("#c13" in (c.text or "") for c in s.sent_to(OWNER))
    assert s.texts_to(13)


async def test_tool_errors_reach_model_not_customer(env):
    """Asking for more than the stock: the model gets the real numbers from the tool error."""
    core, bot, dp, s, model = env
    await add_farms(core, 1)
    seen = {}
    model.steps += [
        [tool("search_farms")],
        lambda p: [tool("prepare_order", offer_code=last_tool_result(p)["offers"][0]["offer_code"], quantity=5)],
        lambda p: seen.update(last_tool_result(p)) or [text("للأسف المتوفر مزرعة وحدة بس.")],
    ]
    await say(dp, bot, 14, "ابي 5 مزارع")
    assert seen["error"] == "out_of_stock" and seen["available"] == 1
    assert not [b for b in all_buttons(s, 14) if (b.callback_data or "").startswith("o:c:")]


async def test_no_emojis_in_system_texts():
    import re
    from app.bot import texts
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅❌]")
    for k, d in texts.T.items():
        for lang, v in d.items():
            assert not emoji.search(v), (lang, k)


async def test_welcome_text_is_editable(env):
    core, bot, dp, s, model = env
    from app.services import system
    await system.update_settings(core, "t", {"welcome_text": "أهلاً بك في متجرنا"})
    await say(dp, bot, 21, "/start")
    assert any("أهلاً بك في متجرنا" in t for t in s.texts_to(21))


async def test_handed_off_chat_returns_to_ai_after_silence(env):
    core, bot, dp, s, model = env
    await say(dp, bot, 22, "/start")
    await core.pool.execute("UPDATE customers SET ai_paused=TRUE WHERE id=22")
    await core.pool.execute("UPDATE customers SET ai_paused_at=now() - interval '2 hours' WHERE id=22")
    model.steps.append([text("أهلاً، كيف أساعدك؟")])
    await say(dp, bot, 22, "مرحبا")
    assert any("كيف أساعدك" in t for t in s.texts_to(22))
    assert not await core.pool.fetchval("SELECT ai_paused FROM customers WHERE id=22")


async def test_recent_staff_reply_keeps_chat_with_staff(env):
    core, bot, dp, s, model = env
    await say(dp, bot, 23, "/start")
    await core.pool.execute("UPDATE customers SET ai_paused=TRUE WHERE id=23")
    await core.pool.execute("UPDATE customers SET ai_paused_at=now() - interval '2 hours' WHERE id=23")
    await core.pool.execute("INSERT INTO messages(customer_id, role, content) VALUES(23, 'admin', 'معك الدعم')")
    n = len(model.payloads)
    await say(dp, bot, 23, "مرحبا")
    assert len(model.payloads) == n


async def test_confirm_button_still_works(env):
    core, bot, dp, s, model = env
    await add_farms(core, 1)
    model.steps += [[tool("search_farms")],
                    lambda p: [tool("prepare_order", offer_code=last_tool_result(p)["offers"][0]["offer_code"], quantity=1)],
                    [text("متأكد تريد تشتري؟")]]
    await say(dp, bot, 30, "اريد مزرعة")
    confirm = [b for b in all_buttons(s, 30) if (b.callback_data or "").startswith("o:c:")]
    await press(dp, bot, 30, confirm[0].callback_data)
    assert any("1127859028" in t for t in s.texts_to(30))
    assert (await orders.customer_orders(core, 30))[0]["status"] == "awaiting_payment"


async def test_confirm_without_prepared_order_is_refused(env):
    core, bot, dp, s, model = env
    seen = {}
    model.steps += [[tool("confirm_order")], lambda p: seen.update(last_tool_result(p)) or [text("ما عندك طلب.")]]
    await say(dp, bot, 31, "نعم")
    assert seen["error"] == "no_pending_order"
