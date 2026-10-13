"""End-to-end bot flows through the real aiogram dispatcher with a mocked Telegram API."""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (AnswerCallbackQuery, EditMessageCaption, EditMessageText, GetMe, SendDocument,
                             SendMessage, SendPhoto, TelegramMethod)
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User

from app.bot.setup import attach_messenger, create_bot, create_dispatcher
from app.i18n import t as tr

BTN_BUY, BTN_TOPUP, BTN_WALLET = "🛒 " + tr("ar", "btn_buy"), "💳 " + tr("ar", "btn_topup"), "💼 " + tr("ar", "btn_wallet")
from app.services import deposits, wallet
from tests.conftest import make_type, make_user

NOW = datetime.now(timezone.utc)
_ids = itertools.count(1)


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.blocked: set[int] = set()

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        chat_id = getattr(method, "chat_id", None)
        if chat_id in self.blocked and isinstance(method, (SendMessage, SendPhoto)):
            from aiogram.exceptions import TelegramForbiddenError
            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Store", username="store_bot")
        if isinstance(method, (SendMessage, SendPhoto, SendDocument, EditMessageText, EditMessageCaption)):
            return Message(message_id=next(_ids), date=NOW, chat=Chat(id=chat_id or 1, type="private"),
                           text=getattr(method, "text", None))
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        yield b""

    def of(self, kind):
        return [c for c in self.calls if isinstance(c, kind)]


@pytest.fixture
async def env(core):
    session = MockSession()
    bot = create_bot("123456:TEST-TOKEN", session=session)
    attach_messenger(core, bot)
    dp = create_dispatcher(core, throttle=0)
    return core, bot, dp, session


def user(uid):
    return User(id=uid, is_bot=False, first_name=f"U{uid}", username=f"u{uid}")


async def send_text(dp, bot, uid, text):
    msg = Message(message_id=next(_ids), date=NOW, chat=Chat(id=uid, type="private"), from_user=user(uid), text=text)
    await dp.feed_update(bot, Update(update_id=next(_ids), message=msg))


async def send_photo(dp, bot, uid, unique):
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


async def test_buy_flow_delivers_credentials_with_copy_buttons(env):
    core, bot, dp, s = env
    t = await make_type(core, 3, price="10")
    await make_user(core, 42, "25")
    await send_text(dp, bot, 42, "/start")
    assert s.of(SendMessage)[-2].reply_markup.keyboard  # main reply keyboard
    assert any(b.callback_data == "c:lang:en" for b in buttons(s.of(SendMessage)[-1]))  # first visit: language picker
    await send_text(dp, bot, 42, BTN_BUY)
    assert any(b.callback_data == f"c:t:{t['id']}" for b in buttons(s.of(SendMessage)[-1]))
    await press(dp, bot, 42, f"c:t:{t['id']}")
    tier_btn = next(b for b in buttons(s.of(EditMessageText)[-1]) if b.callback_data and b.callback_data.startswith("c:bq:"))
    await press(dp, bot, 42, tier_btn.callback_data)
    qty_btns = [b.callback_data for b in buttons(s.of(EditMessageText)[-1]) if b.callback_data and b.callback_data.startswith("c:bp:")]
    assert qty_btns[0].endswith(":1") and len(qty_btns) == 3   # only 3 in stock → 1, 2, 3
    await press(dp, bot, 42, qty_btns[0])
    confirm = next(b for b in buttons(s.of(EditMessageText)[-1]) if b.callback_data and b.callback_data.startswith("c:bc:"))
    assert (await wallet.get_user(core, 42))["balance"] == Decimal("25")
    await press(dp, bot, 42, confirm.callback_data)
    await press(dp, bot, 42, confirm.callback_data)  # double tap
    cred_msgs = [m for m in s.of(SendMessage) if "Password" in (m.text or "")]
    assert len(cred_msgs) == 1
    copies = [b.copy_text.text for b in buttons(cred_msgs[0]) if b.copy_text]
    assert "farm70_0" in copies and "pw0" in copies and any("ID: farm70_0" in c for c in copies)
    assert (await wallet.get_user(core, 42))["balance"] == Decimal("15")
    assert "تم الشراء بنجاح" in s.of(EditMessageText)[-1].text  # second tap still shows success


async def test_blocked_user_order_goes_to_review(env):
    core, bot, dp, s = env
    t = await make_type(core, 1)
    await make_user(core, 43, "10")
    await press(dp, bot, 43, f"c:bp:{t['id']}:10.00")
    confirm = next(b for b in buttons(s.of(EditMessageText)[-1]) if b.callback_data.startswith("c:bc:"))
    s.blocked.add(43)
    await press(dp, bot, 43, confirm.callback_data)
    assert await core.pool.fetchval("SELECT status FROM orders WHERE user_id=43 AND account_id IS NOT NULL") == "needs_review"
    # owner (999) got an alert
    assert any(getattr(m, "chat_id", None) == 999 and "تعذر تسليم" in m.text for m in s.of(SendMessage))


async def test_topup_flow_and_admin_approval_in_telegram(env):
    core, bot, dp, s = env
    await send_text(dp, bot, 50, "/start")
    await send_text(dp, bot, 50, BTN_TOPUP)
    await send_text(dp, bot, 50, "20")
    pay_msg = s.of(SendMessage)[-1]
    assert "1127859028" in pay_msg.text
    assert any(b.copy_text and b.copy_text.text == "1127859028" for b in buttons(pay_msg))
    await send_photo(dp, bot, 50, "PROOF1")
    assert "Order ID" in s.of(SendMessage)[-1].text
    await send_text(dp, bot, 50, "M_P_88776655")
    d = (await deposits.list_deposits(core, user_id=50))[0]
    assert d["status"] == "under_review"
    admin_card = [p for p in s.of(SendPhoto) if p.chat_id == 999][-1]
    approve = next(b for b in buttons(admin_card) if b.callback_data == f"a:da:{d['id']}")
    await press(dp, bot, 12345, approve.callback_data)  # not an admin
    assert (await wallet.get_user(core, 50))["balance"] == Decimal("0")
    await press(dp, bot, 999, approve.callback_data)
    await press(dp, bot, 999, approve.callback_data)  # second tap does nothing
    assert (await wallet.get_user(core, 50))["balance"] == Decimal("20")
    assert any(m.chat_id == 50 and "تم قبول" in m.text for m in s.of(SendMessage))
    # reusing the same screenshot for a new top-up is refused
    await send_text(dp, bot, 50, BTN_TOPUP)
    await send_text(dp, bot, 50, "5")
    await send_photo(dp, bot, 50, "PROOF1")
    assert "مستخدم مسبقاً" in s.of(SendMessage)[-1].text


async def test_admin_adds_type_and_accounts_from_telegram(env):
    core, bot, dp, s = env
    await send_text(dp, bot, 999, "/admin")
    await press(dp, bot, 999, "a:tnew")
    await send_text(dp, bot, 999, "70 4000 3000 10")
    tid = await core.pool.fetchval("SELECT id FROM farm_types")
    assert tid
    await press(dp, bot, 999, f"a:ta:{tid}")
    await send_text(dp, bot, 999, "acc1:p1\nacc2:p2\nacc1:p3\nbadline")
    preview = s.of(SendMessage)[-1].text
    assert "صالح للحفظ: <b>2</b>" in preview
    await press(dp, bot, 999, "a:imp:ok")
    assert await core.pool.fetchval("SELECT count(*) FROM farm_accounts WHERE type_id=$1", tid) == 2
    # the admin's message with plaintext passwords was deleted from the chat
    from aiogram.methods import DeleteMessage
    assert s.of(DeleteMessage)


async def test_wallet_view_and_non_admin_cannot_open_admin(env):
    core, bot, dp, s = env
    await make_user(core, 60, "7.5")
    await send_text(dp, bot, 60, BTN_WALLET)
    assert "7.50" in s.of(SendMessage)[-1].text
    await press(dp, bot, 60, "a:menu")
    assert s.of(AnswerCallbackQuery)[-1].text == "غير مصرح."


async def test_claim_owner_links_telegram(env):
    core, bot, dp, s = env
    from app.services import admins
    core.config.setup_code = "SETUP-abc12345"
    await admins.create_admin(core, "system", "owner", "StrongPass123", "owner")
    await send_text(dp, bot, 77, "/claim wrong")
    assert "غير صحيح" in s.of(SendMessage)[-1].text
    await send_text(dp, bot, 77, "/claim SETUP-abc12345")
    assert await admins.telegram_role(core, 77) == "owner"
    await send_text(dp, bot, 78, "/claim SETUP-abc12345")
    assert await admins.telegram_role(core, 78) is None


async def test_buy_quantity_three_farms_one_confirmation(env):
    core, bot, dp, s = env
    t = await make_type(core, 5, price="10")
    await make_user(core, 44, "35")
    await press(dp, bot, 44, f"c:bq:{t['id']}:10.00")
    await press(dp, bot, 44, f"c:bp:{t['id']}:10.00:3")
    conf = s.of(EditMessageText)[-1]
    assert "30.00" in conf.text and "<b>3</b>" in conf.text
    confirm = next(b for b in buttons(conf) if b.callback_data.startswith("c:bc:"))
    await press(dp, bot, 44, confirm.callback_data)
    await press(dp, bot, 44, confirm.callback_data)
    cred_msgs = [m for m in s.of(SendMessage) if m.chat_id == 44 and "Password" in (m.text or "")]
    assert len(cred_msgs) == 1                     # all 3 farms in ONE message
    body = cred_msgs[0].text
    assert body.count("ID: farm70_") == 3 and body.count("Password: pw") == 3 and "<pre>" in body
    assert "ID: farm70_0\nPassword: pw0\nID: farm70_1\nPassword: pw1" in body
    copy = [b.copy_text.text for b in buttons(cred_msgs[0]) if b.copy_text]
    assert copy and copy[0].startswith("ID: farm70_0\nPassword: pw0")
    # view again from "My orders"
    oid = await core.pool.fetchval("SELECT min(id) FROM orders WHERE user_id=44 AND status='completed'")
    await press(dp, bot, 44, f"c:ob:{oid}")
    assert s.of(SendMessage)[-1].text.count("ID: farm70_") == 3
    assert (await wallet.get_user(core, 44))["balance"] == Decimal("5")
    assert await core.pool.fetchval("SELECT count(*) FROM farm_accounts WHERE status='sold'") == 3
    # more than the balance allows → offered to top up, nothing charged
    await press(dp, bot, 44, f"c:bp:{t['id']}:10.00:2")
    assert "لا يكفي" in s.of(EditMessageText)[-1].text
    assert (await wallet.get_user(core, 44))["balance"] == Decimal("5")


async def test_typed_quantity_and_stock_limit(env):
    core, bot, dp, s = env
    t = await make_type(core, 2, price="4")
    await make_user(core, 45, "100")
    await press(dp, bot, 45, f"c:bo:{t['id']}:4.00")
    await send_text(dp, bot, 45, "abc")
    assert "1" in s.of(SendMessage)[-1].text and "20" in s.of(SendMessage)[-1].text
    await send_text(dp, bot, 45, "5")
    assert "المتوفر بهذا السعر 2" in s.of(SendMessage)[-1].text


async def test_english_language(env):
    core, bot, dp, s = env
    t = await make_type(core, 1, price="10")
    await make_user(core, 46, "10")
    await press(dp, bot, 46, "c:lang:en")
    assert s.of(SendMessage)[-1].text == tr("en", "lang_set")
    kbd = s.of(SendMessage)[-1].reply_markup.keyboard
    assert kbd[0][0].text.endswith("Buy farms") and kbd[0][0].style == "success"
    await send_text(dp, bot, 46, "🛒 Buy farms")
    assert "Choose a farm type" in s.of(SendMessage)[-1].text
    await press(dp, bot, 46, f"c:bp:{t['id']}:10.00:1")
    confirm = next(b for b in buttons(s.of(EditMessageText)[-1]) if b.callback_data.startswith("c:bc:"))
    await press(dp, bot, 46, confirm.callback_data)
    creds = [m for m in s.of(SendMessage) if m.chat_id == 46 and "Password" in (m.text or "")][-1]
    assert "Your farm is ready" in creds.text
    assert any(b.text == "Copy ID" for b in buttons(creds))
    # English notification from a service
    await wallet.admin_adjust(core, "test", 46, "3", "bonus")
    assert "Your balance was adjusted" in [m for m in s.of(SendMessage) if m.chat_id == 46][-1].text


async def test_type_photo_shown_and_sent_with_credentials(env):
    core, bot, dp, s = env
    from app.services import catalog
    t = await make_type(core, 1, price="10")
    await catalog.set_type_photo(core, "test", t["id"], "PHOTO_TYPE_1")
    await make_user(core, 47, "10")
    await press(dp, bot, 47, f"c:t:{t['id']}")
    assert s.of(SendPhoto)[-1].photo == "PHOTO_TYPE_1"   # text message replaced by a photo card
    await press(dp, bot, 47, f"c:bp:{t['id']}:10.00:1")
    confirm = next(b for b in buttons(s.of(EditMessageText)[-1]) if b.callback_data.startswith("c:bc:"))
    await press(dp, bot, 47, confirm.callback_data)
    cred = [p for p in s.of(SendPhoto) if p.chat_id == 47][-1]
    assert cred.photo == "PHOTO_TYPE_1" and "Password" in cred.caption


async def test_farm_card_shows_tools_in_post_format(env):
    core, bot, dp, s = env
    await send_text(dp, bot, 999, "/admin")
    await press(dp, bot, 999, "a:tnew")
    await send_text(dp, bot, 999, "100 4000 1000 4000 10")
    tp = await core.pool.fetchrow("SELECT * FROM farm_types")
    assert (tp["lvl"], tp["barn"], tp["silo"], tp["tools"], str(tp["price"])) == (100, 4000, 1000, 4000, "10.00")
    from app.services import catalog
    await catalog.add_accounts(core, "test", tp["id"], [{"line": 1, "login": "a", "password": "b"}])
    await make_user(core, 48, "0")
    await press(dp, bot, 48, f"c:t:{tp['id']}")
    card = s.of(EditMessageText)[-1].text
    assert card == "المستوى: 100\nالمخزن: 4000\nالصومعة: 1000\nالأدوات: 4000\nالسعر: 10.00 USDT\nالمتوفر: 1"
