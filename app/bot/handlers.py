"""Customer chat: free text goes to the AI; the system handles confirmations, payments and delivery."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..core import Core, StoreError
from ..services import ai as ai_svc
from ..services import customers as cust_svc
from ..services import orders as orders_svc
from ..services import payments as pay_svc
from ..services.system import get_settings, setting
from .texts import tt

log = logging.getLogger(__name__)
router = Router(name="customer")
CID_TAG = re.compile(r"#c(\d+)")
_locks: dict[int, asyncio.Lock] = {}


def _lock(cid: int) -> asyncio.Lock:
    if len(_locks) > 20000:
        _locks.clear()
    return _locks.setdefault(cid, asyncio.Lock())


def _esc(s) -> str:
    return escape(str(s or ""))


async def forward_to_staff(core: Core, customer: dict, text: str, photo: str | None = None) -> None:
    """Customer message while the chat is handled by humans (or AI is off)."""
    if not core.messenger:
        return
    who = f"@{_esc(customer.get('username'))}" if customer.get("username") else _esc(customer.get("first_name"))
    body = (f"<b>رسالة من عميل</b> {who}  #c{customer['id']}\n\n{_esc(text)[:3000]}\n\n"
            "رُد على هذه الرسالة (Reply) لإرسال ردك للعميل، أو استخدم لوحة التحكم.")
    await core.messenger.notify_admins(body, perm="chat", photo=photo)


async def do_handoff(core: Core, customer: dict, reason: str, lang: str, tell_customer: bool = True) -> None:
    await core.pool.execute("UPDATE customers SET ai_paused=TRUE WHERE id=$1", customer["id"])
    if core.messenger:
        who = f"@{_esc(customer.get('username'))}" if customer.get("username") else str(customer["id"])
        last = await cust_svc.history(core, customer["id"], 6)
        convo = "\n".join(f"{'العميل' if m['role'] == 'user' else 'البوت'}: {_esc(m['content'])[:300]}" for m in last)
        await core.messenger.notify_admins(
            f"<b>تحويل محادثة إلى الإدارة</b> {who}  #c{customer['id']}\nالسبب: {_esc(reason)}\n\n{convo}\n\n"
            "رُد على هذه الرسالة للتحدث مع العميل. لإعادة الرد الآلي استخدم لوحة التحكم.", perm="chat")
    if tell_customer:
        text = await setting(core, "handoff_text", "") if lang == "ar" else tt("en", "handoff", text="")
        await core.messenger.send_text(customer["id"], text)
        await cust_svc.log_message(core, customer["id"], "system", "تم تحويل المحادثة إلى الإدارة")


# ------------------------------------------------------------------ start
@router.message(CommandStart())
async def start(message: Message, core: Core, customer: dict, lang: str):
    s = await get_settings(core)
    text = tt(lang, "welcome", store=_esc(s.get("store_name") or "HD农场"))
    await message.answer(text)
    await cust_svc.log_message(core, customer["id"], "assistant", text)


@router.message(Command("claim"))
async def claim(message: Message, core: Core):
    from ..services import admins as admins_svc
    parts = (message.text or "").split(maxsplit=1)
    try:
        a = await admins_svc.claim_owner(core, message.from_user.id, parts[1] if len(parts) > 1 else "")
    except StoreError as ex:
        await message.answer(_esc(ex.message))
        return
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(f"تم ربط حسابك كمالك للمتجر (حساب اللوحة: <code>{_esc(a['username'])}</code>). "
                         "ستصلك الإشعارات ورموز دخول اللوحة هنا.")


# --------------------------------------------------------- staff replies
@router.message(F.reply_to_message, F.text)
async def staff_reply(message: Message, core: Core, customer: dict, lang: str, role: str | None, bot: Bot):
    """An admin replying (Reply) to a forwarded customer message → relayed to that customer."""
    src = message.reply_to_message
    m = CID_TAG.search((src.text or src.caption or "")) if src else None
    if not role or not m:
        await chat(message, core, customer, lang, role, bot)
        return
    cid = int(m.group(1))
    ok = await core.messenger.send_text(cid, message.text)
    if ok:
        await cust_svc.log_message(core, cid, "admin", message.text, author=f"tg:{message.from_user.id}")
        await core.pool.execute("UPDATE customers SET ai_paused=TRUE WHERE id=$1", cid)
        await message.answer("تم إرسال ردك للعميل. (الرد الآلي متوقف لهذا العميل حتى تعيد تفعيله من اللوحة)")
    else:
        await message.answer("تعذر إرسال الرسالة (ربما حظر العميل البوت).")


# ------------------------------------------------------------------ chat
@router.message(F.text)
async def chat(message: Message, core: Core, customer: dict, lang: str, role: str | None, bot: Bot):
    text = message.text.strip()
    if not text:
        return
    async with _lock(customer["id"]):
        await cust_svc.log_message(core, customer["id"], "user", text)
        fresh = await cust_svc.get(core, customer["id"])
        # waiting for a transaction id after a screenshot
        if fresh.get("awaiting", "") and fresh["awaiting"].startswith("txid:") and re.fullmatch(r"[A-Za-z0-9_\-]{5,80}", text):
            try:
                p = await pay_svc.submit_txid(core, customer["id"], int(fresh["awaiting"].split(":")[1]), text)
                ref = await core.pool.fetchval("SELECT ref FROM orders WHERE id=$1", p["order_id"])
                await core.messenger.notify_customer(customer["id"], "in_review", ref=ref)
            except StoreError as ex:
                await message.answer(_esc(ex.message))
            return
        ai_on = (await setting(core, "ai_enabled", "true")) == "true" and ai_svc.enabled(core)
        if fresh["ai_paused"] or not ai_on:
            await forward_to_staff(core, fresh, text)
            recent = await core.pool.fetchval(
                "SELECT 1 FROM messages WHERE customer_id=$1 AND role IN ('admin','system') "
                "AND (role='admin' OR content='waiting_staff') AND created_at > now() - interval '30 minutes' LIMIT 1",
                customer["id"])
            if not recent:
                await message.answer(tt(lang, "waiting_staff"))
                await cust_svc.log_message(core, customer["id"], "system", "waiting_staff")
            return
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        res = await ai_svc.safe_respond(core, fresh)
        if res.text:
            await message.answer(_esc(res.text))
            await cust_svc.log_message(core, customer["id"], "assistant", res.text)
        if res.order:
            await core.messenger.send_order_summary(res.order)
        if res.handoff:
            if res.handoff == "ai_error":
                await message.answer(tt(lang, "ai_error"))
                await do_handoff(core, fresh, "تعذر عمل الذكاء الاصطناعي", lang, tell_customer=False)
            else:
                await do_handoff(core, fresh, res.handoff, lang, tell_customer=not res.text)


# ----------------------------------------------------------------- photos
@router.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def photo(message: Message, core: Core, customer: dict, lang: str):
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    unique = message.photo[-1].file_unique_id if message.photo else message.document.file_unique_id
    async with _lock(customer["id"]):
        order = await pay_svc.awaiting_proof_order(core, customer["id"])
        if order:
            try:
                r = await pay_svc.submit_proof(core, customer["id"], file_id, unique)
            except StoreError as ex:
                await message.answer(_esc(ex.message))
                return
            await cust_svc.log_message(core, customer["id"], "user", f"[أرسل صورة إثبات الدفع للطلب {order['ref']}]")
            await core.messenger.notify_customer(customer["id"], "need_txid" if r["need_txid"] else "in_review", ref=order["ref"])
            return
        await cust_svc.log_message(core, customer["id"], "user", "[أرسل صورة]" + (f" {message.caption}" if message.caption else ""))
        fresh = await cust_svc.get(core, customer["id"])
        if fresh["ai_paused"]:
            await forward_to_staff(core, fresh, message.caption or "[صورة]", photo=file_id)
            return
        await message.answer(tt(lang, "photo_no_order"))


# -------------------------------------------------------------- callbacks
@router.callback_query(F.data.startswith("o:c:"))
async def confirm_order(cb: CallbackQuery, core: Core, customer: dict, lang: str):
    order_id = int(cb.data.split(":")[2])
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        o = await orders_svc.confirm(core, customer["id"], order_id)
    except StoreError as ex:
        if ex.code == "already":
            return
        await cb.message.answer(_esc(ex.message))
        await cust_svc.log_message(core, customer["id"], "system", f"فشل تأكيد الطلب: {ex.message}")
        return
    await cust_svc.log_message(core, customer["id"], "system", f"العميل أكد الطلب {o['ref']} والمزارع محجوزة حتى انتهاء المهلة.")
    methods = await pay_svc.list_methods(core, active_only=True, currency=o["currency"])
    await core.messenger.send_payment_methods(o, methods)


@router.callback_query(F.data.startswith("o:x:"))
async def cancel_order(cb: CallbackQuery, core: Core, customer: dict, lang: str):
    order_id = int(cb.data.split(":")[2])
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await orders_svc.cancel_by_customer(core, customer["id"], order_id)
    except StoreError as ex:
        await cb.message.answer(_esc(ex.message))
        return
    await cb.message.answer(tt(lang, "cancel_done"))
    await cust_svc.log_message(core, customer["id"], "system", "العميل ألغى الطلب.")


@router.callback_query(F.data.startswith("p:m:"))
async def choose_method(cb: CallbackQuery, core: Core, customer: dict, lang: str):
    _, _, order_id, method_id = cb.data.split(":")
    await cb.answer()
    try:
        o, m = await pay_svc.choose_method(core, customer["id"], int(order_id), int(method_id))
    except StoreError as ex:
        await cb.message.answer(_esc(ex.message))
        return
    await core.messenger.send_payment_details(o, m)


@router.message()
async def other(message: Message, lang: str):
    pass  # stickers, voice, etc. are ignored silently
