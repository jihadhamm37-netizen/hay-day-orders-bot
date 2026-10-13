"""Keyboards and text formatting shared by the bot handlers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Iterable

from aiogram.types import (CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup)

from ..core import fmt
from ..services.deposits import STATUS_LABELS as DEP_LABELS
from ..services.orders import STATUS_LABELS as ORD_LABELS
from ..services.wallet import KIND_LABELS

# --------------------------------------------------------- main menu labels
BTN_BUY = "🛒 شراء المزارع"
BTN_WALLET = "💼 محفظتي"
BTN_TOPUP = "💳 شحن الرصيد"
BTN_ORDERS = "📦 طلباتي"
BTN_SUPPORT = "🛟 الدعم الفني"
BTN_ADMIN = "🛠 لوحة الإدارة"

LOCAL_TZ = timezone(timedelta(hours=3))  # Asia/Amman (UTC+3)

ORDER_ICONS = {"pending": "⏳", "processing": "⚙️", "completed": "✅", "cancelled": "✖️", "needs_review": "⚠️"}
DEP_ICONS = {"awaiting_payment": "⏳", "under_review": "🔎", "approved": "✅", "rejected": "❌", "cancelled": "✖️"}


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_BUY)],
        [KeyboardButton(text=BTN_WALLET), KeyboardButton(text=BTN_TOPUP)],
        [KeyboardButton(text=BTN_ORDERS), KeyboardButton(text=BTN_SUPPORT)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def kb(*rows: Iterable[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def copy_btn(text: str, value: str) -> InlineKeyboardButton | None:
    if not value or len(value) > 256:
        return None
    return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=value))


def e(value) -> str:
    return escape(str(value)) if value is not None else ""


def dt(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def type_line(t: dict) -> str:
    return f"LVL {t['lvl']} • Barn {t['barn']} • Silo {t['silo']}"


def type_card(t: dict, tiers: list[dict] | None = None) -> str:
    lines = [
        f"🌾 <b>{e(t['name'])}</b>",
        "",
        f"⭐️ المستوى (LVL): <b>{t['lvl']}</b>",
        f"🏚 سعة المخزن (Barn): <b>{t['barn']:,}</b>",
        f"🌽 سعة الصومعة (Silo): <b>{t['silo']:,}</b>",
        f"💵 السعر: <b>{fmt(t['price'])} USDT</b>",
        f"📦 المتوفر: <b>{t['available']}</b>",
    ]
    if t.get("description"):
        lines += ["", e(t["description"])]
    if tiers and len(tiers) > 1:
        lines += ["", "الأسعار المتاحة:"] + [f"• {fmt(x['price'])} USDT — {x['available']} حساب" for x in tiers]
    return "\n".join(lines)


def credentials_text(order: dict, login: str, password: str) -> str:
    snap = order["type_snapshot"]
    return (
        "🎉 <b>تم شراء المزرعة بنجاح</b>\n\n"
        f"🧾 رقم الطلب: <code>{e(order['ref'])}</code>\n"
        f"🌾 النوع: {e(snap['name'])} — LVL {snap['lvl']} • Barn {snap['barn']} • Silo {snap['silo']}\n"
        f"💵 السعر: {fmt(order['price'])} USDT\n\n"
        f"🆔 <b>ID:</b> <code>{e(login)}</code>\n"
        f"🔑 <b>Password:</b> <code>{e(password)}</code>\n\n"
        "⚠️ احفظ البيانات في مكان آمن ولا تشاركها مع أحد."
    )


def credentials_kb(login: str, password: str) -> InlineKeyboardMarkup:
    full = f"ID: {login}\nPassword: {password}"
    return kb(
        [b for b in (copy_btn("📋 نسخ ID", login), copy_btn("📋 نسخ Password", password)) if b],
        [b for b in (copy_btn("📋 نسخ البيانات كاملة", full),) if b],
    )


def order_line(o: dict) -> str:
    snap = o["type_snapshot"]
    return f"{ORDER_ICONS.get(o['status'], '•')} {snap['name']} — {fmt(o['price'])} USDT — {ORD_LABELS[o['status']]}"


def deposit_line(d: dict) -> str:
    return f"{DEP_ICONS.get(d['status'], '•')} {fmt(d['amount'])} USDT — {DEP_LABELS[d['status']]} — {dt(d['created_at'])}"


def tx_line(t: dict) -> str:
    sign = "+" if t["amount"] > 0 else ""
    return f"• {dt(t['created_at'])} | {KIND_LABELS.get(t['kind'], t['kind'])} | <b>{sign}{fmt(t['amount'])}</b> | <code>{t['ref']}</code>"
