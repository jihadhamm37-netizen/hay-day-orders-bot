"""Customer conversation flow for the HD Agent app (platform independent).

Free text goes to the AI; the system handles confirmations, payment details, proofs and delivery."""
from __future__ import annotations

import asyncio
import hashlib
import logging

from ..core import Core, StoreError
from ..texts import tt
from . import ai as ai_svc
from . import customers as cust_svc
from . import orders as orders_svc
from . import payments as pay_svc
from . import rules as rules_svc
from .system import get_settings, setting

log = logging.getLogger(__name__)
AUTO_RESUME_MIN = 30
_locks: dict[int, asyncio.Lock] = {}


def lock(cid: int) -> asyncio.Lock:
    if len(_locks) > 20000:
        _locks.clear()
    return _locks.setdefault(cid, asyncio.Lock())


async def note(core: Core, cid: int, text: str) -> None:
    """Context line for the AI and the staff; not shown in the customer app."""
    await cust_svc.log_message(core, cid, "system", text, kind="internal")


async def welcome(core: Core, customer: dict) -> None:
    """First open of the app: greet once, in the language the customer picked."""
    if await core.pool.fetchval("SELECT 1 FROM messages WHERE customer_id=$1 LIMIT 1", customer["id"]):
        return
    s = await get_settings(core)
    lang = customer.get("lang") or "ar"
    custom = (s.get("welcome_text") or "").strip()
    text = custom if (lang == "ar" and custom) else rules_svc.r(lang, "welcome", store=s.get("store_name") or "HD Agent")
    await cust_svc.log_message(core, customer["id"], "assistant", text)


async def maybe_resume_ai(core: Core, cid: int) -> bool:
    """A chat handed to staff goes back to the AI when no staff member has written to it for a while."""
    r = await core.pool.execute(
        "UPDATE customers c SET ai_paused=FALSE WHERE id=$1 AND ai_paused "
        "AND coalesce(ai_paused_at, 'epoch') < now() - make_interval(mins => $2) "
        "AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.customer_id=c.id AND m.role='admin' "
        "                AND m.created_at > now() - make_interval(mins => $2))", cid, AUTO_RESUME_MIN)
    return r.endswith(" 1")


async def forward_to_staff(core: Core, customer: dict, text: str) -> None:
    who = customer.get("first_name") or customer.get("access_code") or str(customer["id"])
    await core.messenger.notify_admins(f"رسالة من العميل {who} (#{customer['id']}): {text[:500]}", perm="chat")


async def do_handoff(core: Core, customer: dict, reason: str, lang: str, tell_customer: bool = True) -> None:
    await core.pool.execute("UPDATE customers SET ai_paused=TRUE WHERE id=$1", customer["id"])
    who = customer.get("first_name") or customer.get("access_code") or str(customer["id"])
    await core.messenger.notify_admins(
        f"تحويل محادثة إلى الإدارة: {who} (#{customer['id']}) — السبب: {reason}. افتح المحادثات في اللوحة للرد.", perm="chat")
    if tell_customer:
        text = await setting(core, "handoff_text", "") if lang == "ar" else tt("en", "handoff", text="")
        await core.messenger.send_text(customer["id"], text)
    await note(core, customer["id"], f"تم تحويل المحادثة إلى الإدارة: {reason}")


async def after_confirm(core: Core, o: dict) -> None:
    """Order reserved: show payment details (directly when there is only one method)."""
    methods = await pay_svc.list_methods(core, active_only=True, currency=o["currency"])
    if len(methods) == 1:
        o2, m = await pay_svc.choose_method(core, o["customer_id"], o["id"], methods[0]["id"])
        await core.messenger.send_payment_details(o2, m)
        await note(core, o["customer_id"], f"أُرسلت تفاصيل الدفع ({m['name']}) للطلب {o['ref']}: المبلغ {o['total']} "
                                           f"{o['currency']}. بانتظار صورة إثبات التحويل.")
    else:
        await core.messenger.send_payment_methods(o, methods)


# ------------------------------------------------------------------ text
async def handle_text(core: Core, customer: dict, text: str) -> None:
    text = (text or "").strip()[:2000]
    if not text:
        return
    cid = customer["id"]
    lang = rules_svc.reply_lang(text, customer.get("lang"))   # the app language stays what the customer chose
    async with lock(cid):
        await cust_svc.log_message(core, cid, "user", text)
        if await maybe_resume_ai(core, cid):
            await note(core, cid, "عاد الرد الآلي تلقائياً (لا رد من الإدارة)")
        fresh = await cust_svc.get(core, cid)
        ai_on = (await setting(core, "ai_enabled", "true")) == "true"
        engine = ai_svc if ai_svc.enabled(core) else rules_svc   # Claude if a key is set, else the free built-in assistant
        if fresh["ai_paused"] or not ai_on:
            await forward_to_staff(core, fresh, text)
            window = "30 minutes" if fresh["ai_paused"] and ai_on else "1 minute"
            recent = await core.pool.fetchval(
                "SELECT 1 FROM messages WHERE customer_id=$1 AND role IN ('admin','system') "
                f"AND (role='admin' OR payload->>'key'='waiting_staff') AND created_at > now() - interval '{window}' LIMIT 1",
                cid)
            if not recent:
                await core.messenger.notify_customer(cid, "waiting_staff")
            return
        res = await engine.safe_respond(core, fresh)
        if res.text:
            await cust_svc.log_message(core, cid, "assistant", res.text)
        if res.order and not res.confirmed:
            await core.messenger.send_order_summary(res.order)
        if res.confirmed:
            await note(core, cid, f"العميل أكد الطلب {res.confirmed['ref']} والمزارع محجوزة حتى انتهاء المهلة.")
            await after_confirm(core, res.confirmed)
        if res.handoff:
            if res.handoff == "ai_error":
                await core.messenger.notify_customer(cid, "ai_error")
                await do_handoff(core, fresh, "تعذر عمل الذكاء الاصطناعي", lang, tell_customer=False)
            else:
                await do_handoff(core, fresh, res.handoff, lang, tell_customer=not res.text)


# ------------------------------------------------------------- proof image
async def handle_proof(core: Core, customer: dict, image: bytes, mime: str) -> dict:
    cid = customer["id"]
    digest = hashlib.sha256(image).hexdigest()
    async with lock(cid):
        order = await pay_svc.awaiting_proof_order(core, cid)
        if not order:
            raise StoreError("no_order", tt(customer.get("lang"), "photo_no_order"))
        r = await pay_svc.submit_proof(core, cid, "db", digest, image=image, mime=mime)
        await cust_svc.log_message(core, cid, "user", f"[أرسل صورة إثبات الدفع للطلب {order['ref']}]", kind="proof",
                                   payload={"payment_id": r["payment"]["id"], "ref": order["ref"]})
        await core.messenger.notify_customer(cid, "need_txid" if r["need_txid"] else "in_review", ref=order["ref"])
        return r


# ---------------------------------------------------------------- actions
async def confirm_order(core: Core, customer: dict, order_id: int) -> dict:
    cid = customer["id"]
    async with lock(cid):
        try:
            o = await orders_svc.confirm(core, cid, order_id)
        except StoreError as ex:
            if ex.code != "already":
                await note(core, cid, f"فشل تأكيد الطلب: {ex.message}")
            raise
        await note(core, cid, f"العميل أكد الطلب {o['ref']} والمزارع محجوزة حتى انتهاء المهلة.")
        await after_confirm(core, o)
        return o


async def cancel_order(core: Core, customer: dict, order_id: int) -> dict:
    async with lock(customer["id"]):
        o = await orders_svc.cancel_by_customer(core, customer["id"], order_id)
        await core.messenger.notify_customer(customer["id"], "cancel_done")
        await note(core, customer["id"], f"العميل ألغى الطلب {o['ref']}.")
        return o


async def choose_method(core: Core, customer: dict, order_id: int, method_id: int) -> None:
    async with lock(customer["id"]):
        o, m = await pay_svc.choose_method(core, customer["id"], order_id, method_id)
        await core.messenger.send_payment_details(o, m)


async def edit_order(core: Core, customer: dict, order_id: int) -> None:
    """'Edit order' button: drop the unconfirmed quote (nothing was reserved) and ask what to change."""
    cid = customer["id"]
    async with lock(cid):
        r = await core.pool.execute("UPDATE orders SET status='cancelled', reason='عدّل العميل الطلب', updated_at=now() "
                                    "WHERE id=$1 AND customer_id=$2 AND status='pending_confirmation'", order_id, cid)
        if r.endswith(" 0"):
            raise StoreError("bad_state", "لا يمكن تعديل هذا الطلب الآن.")
        st = await rules_svc.load_state(core, cid)
        await rules_svc.save_state(core, cid, {**st, "expect": "edit"})
        lang = customer.get("lang") or "ar"
        await cust_svc.log_message(core, cid, "assistant", rules_svc.r(lang, "edit"))
