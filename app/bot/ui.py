"""Keyboards and text formatting shared by the bot handlers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Iterable

from aiogram.types import (CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup)

from ..core import fmt
from ..i18n import LANGS, t
from ..services.deposits import STATUS_LABELS as DEP_LABELS
from ..services.orders import STATUS_LABELS as ORD_LABELS
from ..services.wallet import KIND_LABELS

LOCAL_TZ = timezone(timedelta(hours=3))  # Asia/Amman (UTC+3)

# main menu: key -> (fallback emoji, Telegram button colour)
MENU = {
    "buy": ("🛒", "success"),
    "wallet": ("💼", "primary"),
    "topup": ("💳", "success"),
    "orders": ("📦", "primary"),
    "support": ("🎧", None),
    "lang": ("🌐", None),
    "admin": ("🛠", "danger"),
}
BTN_ADMIN = "🛠 لوحة الإدارة"   # kept for the admin router


def menu_labels(key: str) -> set[str]:
    """Every text a menu button can send (all languages, with or without the emoji)."""
    emoji = MENU[key][0]
    out = set()
    for lang in LANGS:
        label = t(lang, f"btn_{key}")
        out |= {label, f"{emoji} {label}"}
    return out


def _menu_btn(key: str, lang: str, icons: dict | None) -> KeyboardButton:
    emoji, style = MENU[key]
    icon = (icons or {}).get(key)
    label = t(lang, f"btn_{key}")
    if icon:
        return KeyboardButton(text=label, icon_custom_emoji_id=icon, style=style)
    return KeyboardButton(text=f"{emoji} {label}", style=style)


def main_menu(lang: str, is_admin: bool, icons: dict | None = None) -> ReplyKeyboardMarkup:
    b = lambda k: _menu_btn(k, lang, icons)  # noqa: E731
    rows = [[b("buy")], [b("wallet"), b("topup")], [b("orders"), b("support")], [b("lang")]]
    if is_admin:
        rows[-1].append(b("admin"))
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def lang_kb() -> InlineKeyboardMarkup:
    return kb([btn(name, f"c:lang:{code}") for code, name in LANGS.items()])


def kb(*rows: Iterable[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


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


def type_line(tp: dict) -> str:
    return f"LVL {tp['lvl']} • Barn {tp['barn']} • Silo {tp['silo']}"


def type_card(tp: dict, tiers: list[dict] | None = None, lang: str = "ar") -> str:
    lines = [
        f"🌾 <b>{e(tp['name'])}</b>",
        "",
        f"{t(lang, 'card_level')}: <b>{tp['lvl']}</b>",
        f"{t(lang, 'card_barn')}: <b>{tp['barn']:,}</b>",
        f"{t(lang, 'card_silo')}: <b>{tp['silo']:,}</b>",
        f"{t(lang, 'card_price')}: <b>{fmt(tp['price'])} USDT</b>",
        f"{t(lang, 'card_stock')}: <b>{tp['available']}</b>",
    ]
    if tp.get("description"):
        lines += ["", e(tp["description"])]
    if tiers and len(tiers) > 1:
        lines += ["", t(lang, "card_tiers")] + [t(lang, "tier_line", price=fmt(x["price"]), n=x["available"]) for x in tiers]
    return "\n".join(lines)


def credentials_text(order: dict, login: str, password: str, lang: str = "ar") -> str:
    snap = order["type_snapshot"]
    part = order.get("part")
    return t(lang, "creds", part=f" ({part[0]}/{part[1]})" if part else "", ref=e(order["ref"]), name=e(snap["name"]),
             lvl=snap["lvl"], barn=snap["barn"], silo=snap["silo"], price=fmt(order["price"]),
             login=e(login), password=e(password))


def credentials_kb(login: str, password: str, lang: str = "ar") -> InlineKeyboardMarkup:
    full = f"ID: {login}\nPassword: {password}"
    return kb(
        [b for b in (copy_btn(t(lang, "copy_id"), login), copy_btn(t(lang, "copy_pw"), password)) if b],
        [b for b in (copy_btn(t(lang, "copy_all"), full),) if b],
    )


ORDER_ICONS = {"pending": "⏳", "processing": "⚙️", "completed": "✅", "cancelled": "✖️", "needs_review": "⚠️"}
DEP_ICONS = {"awaiting_payment": "⏳", "under_review": "🔎", "approved": "✅", "rejected": "❌", "cancelled": "✖️"}


def order_line(o: dict, lang: str = "ar") -> str:
    snap = o["type_snapshot"]
    return f"{ORDER_ICONS.get(o['status'], '•')} {snap['name']} — {fmt(o['price'])} USDT — {t(lang, 'st_' + o['status'])}"


def deposit_line(d: dict, lang: str = "ar") -> str:
    return (f"{DEP_ICONS.get(d['status'], '•')} {fmt(d['amount'])} USDT — {t(lang, 'dst_' + d['status'])} — "
            f"{dt(d['created_at'])}")


def tx_line(x: dict, lang: str = "ar") -> str:
    sign = "+" if x["amount"] > 0 else ""
    return f"• {dt(x['created_at'])} | {t(lang, 'kind_' + x['kind'])} | <b>{sign}{fmt(x['amount'])}</b> | <code>{x['ref']}</code>"


# admin-side helpers (Arabic only)
def order_line_ar(o: dict) -> str:
    snap = o["type_snapshot"]
    return f"{ORDER_ICONS.get(o['status'], '•')} {snap['name']} — {fmt(o['price'])} USDT — {ORD_LABELS[o['status']]}"


def deposit_line_ar(d: dict) -> str:
    return f"{DEP_ICONS.get(d['status'], '•')} {fmt(d['amount'])} USDT — {DEP_LABELS[d['status']]} — {dt(d['created_at'])}"


def tx_line_ar(x: dict) -> str:
    sign = "+" if x["amount"] > 0 else ""
    return f"• {dt(x['created_at'])} | {KIND_LABELS.get(x['kind'], x['kind'])} | <b>{sign}{fmt(x['amount'])}</b> | <code>{x['ref']}</code>"
