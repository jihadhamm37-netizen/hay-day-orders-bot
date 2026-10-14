"""Telegram side of the services: everything the system (not the AI) sends."""
from __future__ import annotations

import logging
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from ..core import Core, fmt
from ..services import customers as cust_svc
from ..services.admins import admin_recipients
from ..services.orders import status_text
from ..services.system import setting
from .texts import tt

log = logging.getLogger(__name__)
LOCAL_OFFSET_H = 3


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def copy_btn(text: str, value: str) -> InlineKeyboardButton | None:
    if not value or len(value) > 256:
        return None
    return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=value))


def e(v) -> str:
    return escape(str(v)) if v is not None else ""


def local_time(dt) -> str:
    from datetime import timedelta, timezone
    return dt.astimezone(timezone(timedelta(hours=LOCAL_OFFSET_H))).strftime("%H:%M") if dt else "—"


def payment_review_kb(payment_id: int):
    return kb([btn("قبول الدفع", f"a:pa:{payment_id}", "success"), btn("رفض الإثبات", f"a:pr:{payment_id}", "danger")])


class TelegramMessenger:
    def __init__(self, bot: Bot, core: Core):
        self.bot = bot
        self.core = core

    async def _lang(self, customer_id: int) -> str:
        return await self.core.pool.fetchval("SELECT lang FROM customers WHERE id=$1", customer_id) or "ar"

    async def _send(self, customer_id: int, text: str, markup=None, log_it: bool = True) -> bool:
        try:
            await self.bot.send_message(customer_id, text, reply_markup=markup)
        except TelegramForbiddenError:
            return False
        except TelegramAPIError as ex:
            log.warning("send to %s failed: %s", customer_id, ex)
            return False
        if log_it:
            await cust_svc.log_message(self.core, customer_id, "system", _plain(text))
        return True

    # ------------------------------------------------------------ orders
    async def send_order_summary(self, order: dict) -> None:
        lang = await self._lang(order["customer_id"])
        off = order["offer"]
        minutes = await setting(self.core, "reservation_minutes", "30")
        text = tt(lang, "summary", ref=order["ref"], name=e(off["name"]), lvl=off["lvl"], barn=off["barn"], silo=off["silo"],
                  tools=off["tools"], qty=order["quantity"], price=fmt(order["unit_price"]), total=fmt(order["total"]),
                  cur=order["currency"], minutes=minutes)
        await self._send(order["customer_id"], text, kb(
            [btn(tt(lang, "btn_confirm"), f"o:c:{order['id']}", "success"), btn(tt(lang, "btn_cancel"), f"o:x:{order['id']}", "danger")]))

    async def send_payment_methods(self, order: dict, methods: list[dict]) -> None:
        lang = await self._lang(order["customer_id"])
        if not methods:
            await self._send(order["customer_id"], tt(lang, "no_methods"))
            await self.notify_admins(f"لا توجد وسيلة دفع مفعّلة بعملة {order['currency']} للطلب <code>{order['ref']}</code>.", perm="methods")
            return
        text = tt(lang, "confirmed", ref=order["ref"], until=local_time(order.get("reserved_until")))
        await self._send(order["customer_id"], text, kb(*[[btn(m["name"], f"p:m:{order['id']}:{m['id']}", "primary")] for m in methods]))

    async def send_payment_details(self, order: dict, method: dict) -> None:
        lang = await self._lang(order["customer_id"])
        text = tt(lang, "pay_details", method=e(method["name"]), ref=order["ref"], total=fmt(order["total"]),
                  cur=order["currency"], account=e(method["account"]), instructions=e(method["instructions"] or ""))
        await self._send(order["customer_id"], text, kb(
            [b for b in (copy_btn(tt(lang, "copy_account"), method["account"]), copy_btn(tt(lang, "copy_amount"), str(order["total"]))) if b],
            [b for b in (copy_btn(tt(lang, "copy_ref"), order["ref"]),) if b]))

    async def deliver_farms(self, order: dict, items: list[tuple[dict, str, str]]) -> None:
        """All farms of the order in one copyable list. Raises if Telegram refuses (order stays undelivered)."""
        lang = await self._lang(order["customer_id"])
        block = "\n".join(f"ID: {tok}\nPassword: {pw}" for _, tok, pw in items)
        head = tt(lang, "delivered", ref=order["ref"], n=len(items), lvl=order["offer"]["lvl"])
        text = f"{head}\n\n<pre>{e(block)}</pre>\n\n{tt(lang, 'keep_safe')}"
        if len(text) > 4000:  # split long lists
            chunks, cur = [], []
            for _, tok, pw in items:
                cur.append(f"ID: {tok}\nPassword: {pw}")
                if len("\n".join(cur)) > 3300:
                    chunks.append(cur[:-1])
                    cur = cur[-1:]
            chunks.append(cur)
            await self.bot.send_message(order["customer_id"], head)
            for ch in chunks:
                await self.bot.send_message(order["customer_id"], f"<pre>{e(chr(10).join(ch))}</pre>")
            await self.bot.send_message(order["customer_id"], tt(lang, "keep_safe"))
        else:
            await self.bot.send_message(order["customer_id"], text,
                                        reply_markup=kb([b for b in (copy_btn(tt(lang, "copy_all"), block),) if b]))
        # never store credentials in the chat log
        await cust_svc.log_message(self.core, order["customer_id"], "system",
                                   f"تم تسليم الطلب {order['ref']} ({len(items)} مزرعة). البيانات أُرسلت للعميل.")

    async def notify_customer(self, customer_id: int, key: str, **params) -> bool:
        lang = await self._lang(customer_id)
        if key.startswith("status:"):
            status = key.split(":", 1)[1]
            text = tt(lang, "order_status", ref=params["ref"], status=status_text(status, lang))
        else:
            params = {k: e(v) for k, v in params.items()}
            text = tt(lang, key, **params)
        return await self._send(customer_id, text)

    async def send_text(self, customer_id: int, text: str) -> bool:
        try:
            await self.bot.send_message(customer_id, e(text))
            return True
        except TelegramAPIError as ex:
            log.warning("admin reply to %s failed: %s", customer_id, ex)
            return False

    # ------------------------------------------------------------- admins
    async def notify_admins(self, text: str, *, perm: str = "view", photo: str | None = None,
                            reply_markup: Any = None) -> None:
        if isinstance(reply_markup, tuple) and reply_markup[0] == "payment_review":
            reply_markup = payment_review_kb(reply_markup[1])
        for admin_id in await admin_recipients(self.core, perm):
            try:
                if photo:
                    await self.bot.send_photo(admin_id, photo, caption=text[:1024], reply_markup=reply_markup)
                else:
                    await self.bot.send_message(admin_id, text, reply_markup=reply_markup)
            except TelegramAPIError as ex:
                log.warning("notify admin %s failed: %s", admin_id, ex)

    async def send_admin_code(self, telegram_id: int, code: str) -> bool:
        try:
            await self.bot.send_message(telegram_id, f"رمز الدخول إلى لوحة التحكم: <code>{code}</code>\nصالح لمدة 5 دقائق.")
            return True
        except TelegramAPIError as ex:
            log.warning("admin code to %s failed: %s", telegram_id, ex)
            return False


def _plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
