"""App side of the services: everything the system (not the AI) shows the customer is stored as a chat item
that the HD Agent app renders (text or a card). Staff are notified in the panel (alerts) and, optionally,
through a send-only Telegram bot (NOTIFY_BOT_TOKEN)."""
from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from .core import Core, fmt
from .services import customers as cust_svc
from .services.admins import admin_recipients
from .services.orders import status_text
from .services.system import raise_alert, setting
from .texts import tt

log = logging.getLogger(__name__)


def plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


class AppMessenger:
    def __init__(self, core: Core):
        self.core = core

    async def _lang(self, customer_id: int) -> str:
        return await self.core.pool.fetchval("SELECT lang FROM customers WHERE id=$1", customer_id) or "ar"

    async def _post(self, customer_id: int, text: str, kind: str = "text", payload: dict | None = None,
                    role: str = "system") -> int:
        return await cust_svc.log_message(self.core, customer_id, role, plain(text), kind=kind, payload=payload)

    # ------------------------------------------------------------ orders
    async def send_order_summary(self, order: dict) -> None:
        lang = await self._lang(order["customer_id"])
        off = order["offer"]
        minutes = await setting(self.core, "reservation_minutes", "30")
        text = tt(lang, "summary", ref=order["ref"], name=off["name"], lvl=off["lvl"], barn=off["barn"], silo=off["silo"],
                  tools=off["tools"], qty=order["quantity"], price=fmt(order["unit_price"]), total=fmt(order["total"]),
                  cur=order["currency"], minutes=minutes)
        await self._post(order["customer_id"], text, "order_summary", {
            "order_id": order["id"], "ref": order["ref"], "lvl": off["lvl"], "barn": off["barn"], "silo": off["silo"],
            "tools": off["tools"], "name": off["name"], "quantity": order["quantity"], "unit_price": fmt(order["unit_price"]),
            "total": fmt(order["total"]), "currency": order["currency"], "minutes": int(minutes)})

    async def send_payment_methods(self, order: dict, methods: list[dict]) -> None:
        lang = await self._lang(order["customer_id"])
        if not methods:
            await self._post(order["customer_id"], tt(lang, "no_methods"))
            await self.notify_admins(f"لا توجد وسيلة دفع مفعّلة بعملة {order['currency']} للطلب {order['ref']}.", perm="methods")
            return
        text = tt(lang, "confirmed", ref=order["ref"], until="")
        await self._post(order["customer_id"], text, "methods", {
            "order_id": order["id"], "ref": order["ref"], "reserved_until": order["reserved_until"].isoformat()
            if order.get("reserved_until") else None, "methods": [{"id": m["id"], "name": m["name"]} for m in methods]})

    async def send_payment_details(self, order: dict, method: dict) -> None:
        lang = await self._lang(order["customer_id"])
        text = tt(lang, "pay_details", method=method["name"], ref=order["ref"], total=fmt(order["total"]),
                  cur=order["currency"], account=method["account"], instructions=method["instructions"] or "")
        await self._post(order["customer_id"], text, "pay_details", {
            "order_id": order["id"], "ref": order["ref"], "method": method["name"], "account": method["account"],
            "instructions": method["instructions"] or "", "total": fmt(order["total"]), "amount": str(order["total"]),
            "currency": order["currency"], "reserved_until": order["reserved_until"].isoformat()
            if order.get("reserved_until") else None})

    async def deliver_farms(self, order: dict, items: list[tuple[dict, str, str]]) -> None:
        """Credentials are never written to the chat: the card lets the customer open them from the order."""
        if not items:
            raise RuntimeError("no farms to deliver")
        lang = await self._lang(order["customer_id"])
        text = plain(tt(lang, "delivered", ref=order["ref"], n=len(items), lvl=order["offer"]["lvl"]))
        await self._post(order["customer_id"], text, "delivered",
                         {"order_id": order["id"], "ref": order["ref"], "count": len(items), "lvl": order["offer"]["lvl"]})

    async def notify_customer(self, customer_id: int, key: str, **params) -> bool:
        lang = await self._lang(customer_id)
        if key.startswith("status:"):
            status = key.split(":", 1)[1]
            text = tt(lang, "order_status", ref=params["ref"], status=status_text(status, lang))
        else:
            text = tt(lang, key, **params)
        await self._post(customer_id, text, "notice", {"key": key, **{k: str(v) for k, v in params.items()}})
        return True

    async def send_text(self, customer_id: int, text: str) -> bool:
        """A plain message to the customer written by the system on behalf of the store."""
        await self._post(customer_id, text, "text", role="assistant")
        return True

    # ------------------------------------------------------------- admins
    async def notify_admins(self, text: str, *, perm: str = "view", photo: str | None = None,
                            reply_markup: Any = None) -> None:
        level = "warning" if "دفع" in text or "تحويل" in text else "info"
        await raise_alert(self.core, level, "notify", plain(text)[:1500], notify=False)
        await self._telegram(plain(text), perm)

    async def send_admin_code(self, telegram_id: int, code: str) -> bool:
        return await self._telegram_to(telegram_id, f"رمز الدخول إلى لوحة HD Agent: {code}\nصالح لمدة 5 دقائق.")

    async def _telegram(self, text: str, perm: str) -> None:
        if not self.core.config.notify_bot_token:
            return
        for admin_id in await admin_recipients(self.core, perm):
            await self._telegram_to(admin_id, text)

    async def _telegram_to(self, chat_id: int, text: str) -> bool:
        token = self.core.config.notify_bot_token
        if not token:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        panel = (self.core.config.public_url or "") + self.core.config.panel_path
        body = {"chat_id": chat_id, "text": f"HD Agent\n{text[:3800]}" + (f"\n\n{panel}" if self.core.config.public_url else ""),
                "disable_web_page_preview": True}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.post(url, json=body) as r:
                    return r.status == 200
        except Exception as ex:  # notifications must never break the flow
            log.warning("telegram notify failed: %s", ex)
            return False
