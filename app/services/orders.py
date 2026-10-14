"""Order lifecycle:

pending_confirmation → awaiting_payment (farms reserved for N minutes) → proof_received → payment_review
→ payment_confirmed → processing → delivered          (or cancelled / rejected with a reason)

Prices, stock and reservations are decided here — never by the AI.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

import asyncpg

from ..core import Core, StoreError, fmt, row, rows
from ..security import make_ref
from . import farms as farms_svc
from .system import audit, raise_alert, setting

log = logging.getLogger(__name__)

STATUS_AR = {
    "pending_confirmation": "بانتظار تأكيد الطلب",
    "awaiting_payment": "بانتظار الدفع",
    "proof_received": "إثبات الدفع مستلم",
    "payment_review": "الدفع قيد المراجعة",
    "payment_confirmed": "الدفع مؤكد",
    "processing": "الطلب قيد التجهيز",
    "delivered": "تم التسليم",
    "cancelled": "الطلب ملغي",
    "rejected": "الطلب مرفوض",
}
STATUS_EN = {
    "pending_confirmation": "Awaiting your confirmation",
    "awaiting_payment": "Awaiting payment",
    "proof_received": "Payment proof received",
    "payment_review": "Payment under review",
    "payment_confirmed": "Payment confirmed",
    "processing": "Being prepared",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "rejected": "Rejected",
}
STATUS_VI = {"pending_confirmation": "Chờ bạn xác nhận", "awaiting_payment": "Chờ thanh toán", "proof_received": "Đã nhận bằng chứng",
             "payment_review": "Đang kiểm tra thanh toán", "payment_confirmed": "Đã xác nhận thanh toán", "processing": "Đang chuẩn bị",
             "delivered": "Đã giao", "cancelled": "Đã hủy", "rejected": "Bị từ chối"}
STATUS_ZH = {"pending_confirmation": "待您确认", "awaiting_payment": "待付款", "proof_received": "已收到凭证", "payment_review": "付款审核中",
             "payment_confirmed": "付款已确认", "processing": "准备中", "delivered": "已交付", "cancelled": "已取消", "rejected": "已拒绝"}
OPEN = ("pending_confirmation", "awaiting_payment", "proof_received", "payment_review", "payment_confirmed", "processing")
PENDING_TTL_MIN = 30


async def _int_setting(core: Core, key: str, default: int) -> int:
    try:
        return int(await setting(core, key, str(default)))
    except ValueError:
        return default


# ----------------------------------------------------------------- prepare
async def prepare(core: Core, customer_id: int, offer_code: str, quantity: int) -> dict:
    """Create an order (one farm type) awaiting the customer's confirmation. Nothing is reserved yet."""
    return await prepare_lines(core, customer_id, [(offer_code, quantity)])


async def prepare_lines(core: Core, customer_id: int, wanted: list[tuple[str, int]]) -> dict:
    """Create an order with one or more farm types awaiting confirmation. Prices come from the stock only."""
    cust = await core.pool.fetchrow("SELECT * FROM customers WHERE id=$1", customer_id)
    if not cust:
        raise StoreError("not_found", "العميل غير موجود.")
    if cust["is_banned"]:
        raise StoreError("banned", "الحساب موقوف.")
    if not wanted:
        raise StoreError("bad_qty", "الطلب فارغ.")
    merged: dict[str, int] = {}
    for code, q in wanted:                     # same type twice → one line
        merged[code] = merged.get(code, 0) + int(q)
    max_q = await _int_setting(core, "max_quantity", 20)
    total_q = sum(merged.values())
    if any(q < 1 for q in merged.values()) or not (1 <= total_q <= max_q):
        raise StoreError("bad_qty", f"عدد المزارع في الطلب يجب أن يكون بين 1 و {max_q}.", max=max_q)
    lines, total, currency = [], Decimal("0"), None
    for code, q in merged.items():
        offer = await farms_svc.find_offer(core, code)
        if not offer:
            raise StoreError("no_offer", "أحد الأنواع المطلوبة غير متوفر حالياً.")
        if offer["available"] < q:
            raise StoreError("out_of_stock", f"المتوفر من مستوى {offer['lvl']} ({offer.get('tool_type', 'land')}) "
                                             f"{offer['available']} فقط.", available=offer["available"], offer_code=code)
        if currency and offer["currency"] != currency:
            raise StoreError("currency", "لا يمكن جمع عملات مختلفة في طلب واحد.")
        currency = offer["currency"]
        snap = {k: (str(offer[k]) if k == "price" else offer[k]) for k in farms_svc.OFFER_FIELDS}
        snap["description"] = offer.get("description")
        snap["offer_code"] = offer["offer_code"]
        price = Decimal(offer["price"])
        lines.append({"offer": snap, "quantity": q, "unit_price": str(price), "subtotal": str(price * q)})
        total += price * q
    open_n = await core.pool.fetchval(
        "SELECT count(*) FROM orders WHERE customer_id=$1 AND status IN ('awaiting_payment','proof_received','payment_review')",
        customer_id)
    if open_n >= await _int_setting(core, "max_open_orders", 3):
        raise StoreError("too_many_open", "لديك طلبات مفتوحة بانتظار الدفع. أكمل أو ألغِ أحدها أولاً.")
    first = lines[0]
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE orders SET status='cancelled', reason='استُبدل بطلب أحدث', updated_at=now() "
                           "WHERE customer_id=$1 AND status='pending_confirmation'", customer_id)
        o = await conn.fetchrow(
            "INSERT INTO orders(ref, customer_id, status, offer, quantity, unit_price, total, currency, lines) "
            "VALUES($1,$2,'pending_confirmation',$3,$4,$5,$6,$7,$8) RETURNING *",
            make_ref("HD"), customer_id, first["offer"], total_q, Decimal(first["unit_price"]), total, currency, lines)
    return dict(o)


def order_lines(o: dict) -> list[dict]:
    """Lines of any order (old single-type orders included)."""
    return o.get("lines") or [{"offer": o["offer"], "quantity": o["quantity"], "unit_price": str(o["unit_price"]),
                               "subtotal": str(o["total"])}]


# ----------------------------------------------------------------- confirm
async def confirm(core: Core, customer_id: int, order_id: int) -> dict:
    """Customer pressed confirm: reserve the farms for a limited time (all or nothing)."""
    minutes = await _int_setting(core, "reservation_minutes", 30)
    async with core.pool.acquire() as conn:
        try:
            async with conn.transaction():
                o = await conn.fetchrow(
                    "UPDATE orders SET status='awaiting_payment', confirmed_at=now(), updated_at=now(), "
                    "reserved_until=now() + make_interval(mins => $3) "
                    "WHERE id=$1 AND customer_id=$2 AND status='pending_confirmation' "
                    "AND created_at > now() - make_interval(mins => $4) RETURNING *",
                    order_id, customer_id, minutes, PENDING_TTL_MIN)
                if not o:
                    cur = await conn.fetchrow("SELECT status, customer_id FROM orders WHERE id=$1", order_id)
                    if not cur or cur["customer_id"] != customer_id:
                        raise StoreError("not_found", "الطلب غير موجود.")
                    if cur["status"] == "pending_confirmation":
                        raise StoreError("expired", "انتهت صلاحية هذا الطلب، اطلب من جديد.")
                    raise StoreError("already", "تم تأكيد هذا الطلب مسبقاً.")
                farms = []
                for ln in order_lines(dict(o)):
                    off = ln["offer"]
                    got = await conn.fetch(
                        "SELECT id, price, cost FROM farms WHERE status='available' AND name=$1 AND lvl=$2 AND barn=$3 "
                        "AND silo=$4 AND tools=$5 AND price=$6 AND currency=$7 AND tool_type=$9 ORDER BY id LIMIT $8 "
                        "FOR UPDATE SKIP LOCKED",
                        off["name"], off["lvl"], off["barn"], off["silo"], off["tools"], Decimal(off["price"]),
                        off["currency"], ln["quantity"], off.get("tool_type", "land"))
                    if len(got) < ln["quantity"]:
                        raise StoreError("out_of_stock", "عذراً، نفدت الكمية قبل التأكيد.", available=len(got))
                    farms.extend(got)
                ids = [f["id"] for f in farms]
                await conn.execute("UPDATE farms SET status='reserved', updated_at=now() WHERE id = ANY($1::bigint[])", ids)
                await conn.executemany("INSERT INTO order_items(order_id, farm_id, price, cost) VALUES($1,$2,$3,$4)",
                                       [(o["id"], f["id"], f["price"], f["cost"]) for f in farms])
                await audit(conn, f"tg:{customer_id}", "order.confirm", "order", o["id"],
                            {"ref": o["ref"], "qty": o["quantity"], "total": o["total"]})
                o = dict(o)
        except StoreError as e:
            if e.code not in ("already", "not_found"):
                await conn.execute("UPDATE orders SET status='cancelled', reason=$2, updated_at=now() "
                                   "WHERE id=$1 AND status='pending_confirmation'", order_id, e.message)
            raise
    if core.messenger:
        await core.messenger.notify_admins(
            f"<b>طلب جديد مؤكد</b>\nالطلب: <code>{o['ref']}</code>\nالعميل: <code>{customer_id}</code>\n"
            f"{_offer_line(o)}\nالإجمالي: {fmt(o['total'])} {o['currency']}\nبانتظار الدفع.", perm="orders")
    return o


TOOL_AR = {"land": "أدوات أرض", "barn": "أدوات حظيرة", "silo": "أدوات صومعة"}


def _offer_line(o: dict) -> str:
    return "\n".join(
        f"{ln['quantity']} × المستوى {ln['offer']['lvl']}، المخزن {ln['offer']['barn']}، الصومعة {ln['offer']['silo']}، "
        f"{TOOL_AR.get(ln['offer'].get('tool_type', 'land'))} {ln['offer']['tools']} — {ln['unit_price']}"
        for ln in order_lines(o))


async def cancel_by_customer(core: Core, customer_id: int, ref_or_id: Any) -> dict:
    """Customers may cancel only before sending a payment proof."""
    o = await _find_customer_order(core, customer_id, ref_or_id)
    if o["status"] not in ("pending_confirmation", "awaiting_payment"):
        raise StoreError("bad_state", "لا يمكن إلغاء الطلب بعد إرسال إثبات الدفع. تواصل مع الإدارة.")
    return await _close(core, o["id"], "cancelled", "ألغاه العميل", f"tg:{customer_id}", notify=False)


async def _find_customer_order(core: Core, customer_id: int, ref_or_id: Any) -> dict:
    if isinstance(ref_or_id, int) or str(ref_or_id).isdigit():
        r = await core.pool.fetchrow("SELECT * FROM orders WHERE id=$1 AND customer_id=$2", int(ref_or_id), customer_id)
    else:
        r = await core.pool.fetchrow("SELECT * FROM orders WHERE upper(ref)=upper($1) AND customer_id=$2",
                                     str(ref_or_id).strip(), customer_id)
    if not r:
        raise StoreError("not_found", "الطلب غير موجود.")
    return dict(r)


async def _close(core: Core, order_id: int, status: str, reason: str, actor: str, notify: bool = True,
                 ip: str | None = None, restock: bool = True) -> dict:
    """Cancel or reject an order and release its farms (exactly once)."""
    assert status in ("cancelled", "rejected")
    async with core.pool.acquire() as conn, conn.transaction():
        o = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
        if not o:
            raise StoreError("not_found", "الطلب غير موجود.")
        if o["status"] in ("delivered", "cancelled", "rejected"):
            raise StoreError("bad_state", f"الطلب منتهٍ بالفعل ({STATUS_AR[o['status']]}).")
        if o["status"] == "processing":
            raise StoreError("busy", "الطلب قيد التسليم الآن.")
        farm_ids = [r["farm_id"] for r in await conn.fetch(
            "UPDATE order_items SET active=FALSE WHERE order_id=$1 AND active RETURNING farm_id", order_id)]
        if farm_ids:
            await conn.execute("UPDATE farms SET status=$2, updated_at=now() WHERE id = ANY($1::bigint[]) "
                               "AND status='reserved'", farm_ids, "available" if restock else "disabled")
        await conn.execute("UPDATE payments SET status='rejected', reject_reason=$2, reviewed_by=$3, reviewed_at=now() "
                           "WHERE order_id=$1 AND status='pending'", order_id, reason, actor)
        o = await conn.fetchrow("UPDATE orders SET status=$2, reason=$3, updated_at=now() WHERE id=$1 RETURNING *",
                                order_id, status, reason)
        await audit(conn, actor, f"order.{status}", "order", order_id, {"ref": o["ref"], "reason": reason}, ip)
    if notify and core.messenger:
        await core.messenger.notify_customer(o["customer_id"], f"order_{status}", ref=o["ref"], reason=reason)
    return dict(o)


async def admin_cancel(core: Core, actor: str, order_id: int, reason: str, ip: str | None = None) -> dict:
    if len((reason or "").strip()) < 3:
        raise StoreError("reason_required", "اكتب سبب الإلغاء.")
    return await _close(core, order_id, "cancelled", reason.strip(), actor, ip=ip)


async def admin_reject(core: Core, actor: str, order_id: int, reason: str, ip: str | None = None) -> dict:
    if len((reason or "").strip()) < 3:
        raise StoreError("reason_required", "اكتب سبب الرفض ليظهر للعميل.")
    return await _close(core, order_id, "rejected", reason.strip(), actor, ip=ip)


# ---------------------------------------------------------------- delivery
async def deliver(core: Core, order_id: int, actor: str = "system") -> bool:
    """Staff pressed "deliver" on a paid order (processing = being prepared) → delivered.
    Credentials leave the DB only here, only after payment, and only once at a time (delivering_at guard)."""
    o = await core.pool.fetchrow(
        "UPDATE orders SET status='processing', delivering_at=now(), updated_at=now() WHERE id=$1 "
        "AND status IN ('payment_confirmed','processing') "
        "AND (delivering_at IS NULL OR delivering_at < now() - interval '2 minutes') RETURNING *", order_id)
    if not o:
        return False
    items = await core.pool.fetch(
        "SELECT f.id, f.token_enc, f.password_enc FROM order_items i JOIN farms f ON f.id=i.farm_id "
        "WHERE i.order_id=$1 AND i.active ORDER BY f.id", order_id)
    try:
        if not core.messenger:
            raise RuntimeError("messenger not configured")
        creds = [(dict(o), core.vault.decrypt(r["token_enc"]), core.vault.decrypt(r["password_enc"])) for r in items]
        await core.messenger.deliver_farms(dict(o), creds)
    except Exception as e:
        log.warning("delivery failed for %s: %s", o["ref"], e)
        await core.pool.execute("UPDATE orders SET failure_reason=$2, delivering_at=NULL, updated_at=now() WHERE id=$1",
                                order_id, f"فشل التسليم: {type(e).__name__}: {str(e)[:200]}")
        await raise_alert(core, "error", "delivery_failed",
                          f"تعذر تسليم الطلب {o['ref']} للعميل {o['customer_id']}. الدفع مؤكد والمزارع محجوزة — "
                          "أعد الإرسال من لوحة التحكم.", "order", order_id, perm="orders")
        return False
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE orders SET status='delivered', delivered_at=now(), failure_reason=NULL, delivering_at=NULL, "
                           "updated_at=now() WHERE id=$1 AND status='processing'", order_id)
        await conn.execute("UPDATE farms SET status='sold', sold_at=now(), updated_at=now() "
                           "WHERE id = ANY($1::bigint[]) AND status='reserved'", [r["id"] for r in items])
        await audit(conn, actor, "order.delivered", "order", order_id, {"ref": o["ref"], "farms": len(items)})
    if core.messenger:
        await core.messenger.notify_admins(
            f"<b>تم تسليم طلب</b>\nالطلب: <code>{o['ref']}</code>\nالعميل: <code>{o['customer_id']}</code>\n"
            f"الإجمالي: {fmt(o['total'])} {o['currency']}", perm="orders")
    for ln in order_lines(dict(o)):
        await farms_svc.check_low_stock(core, ln["offer"])
    return True


async def redeliver(core: Core, actor: str, order_id: int) -> bool:
    """Deliver a paid order, or show the delivery again to a customer who already received it."""
    o = await core.pool.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
    if not o:
        raise StoreError("not_found", "الطلب غير موجود.")
    if o["status"] == "delivered":
        items = await core.pool.fetch("SELECT farm_id FROM order_items WHERE order_id=$1 AND active", order_id)
        if core.messenger:
            await core.messenger.deliver_farms(dict(o), [(dict(o), "", "") for _ in items])
        async with core.pool.acquire() as conn:
            await audit(conn, actor, "order.redeliver", "order", order_id, {"ref": o["ref"]})
        return True
    if o["status"] not in ("processing", "payment_confirmed"):
        raise StoreError("bad_state", "لا يمكن تسليم طلب لم يُدفع.")
    return await deliver(core, order_id, actor)


# ------------------------------------------------------------- maintenance
async def maintenance(core: Core) -> dict:
    """Expire unconfirmed orders and release reservations that ran out without a payment proof."""
    await core.pool.execute(
        "UPDATE orders SET status='cancelled', reason='انتهت مهلة التأكيد', updated_at=now() "
        "WHERE status='pending_confirmation' AND created_at < now() - make_interval(mins => $1)", PENDING_TTL_MIN)
    expired = await core.pool.fetch(
        "SELECT id FROM orders WHERE status='awaiting_payment' AND reserved_until < now()")
    n = 0
    for r in expired:
        try:
            await _close(core, r["id"], "cancelled", "انتهت مدة الحجز دون دفع", "system")
            n += 1
        except StoreError:
            pass
    # paid orders wait in "processing" until staff deliver them from the panel (never automatic)
    return {"expired_reservations": n}


# ----------------------------------------------------------------- queries
async def get_order(core: Core, order_id: int) -> dict | None:
    o = row(await core.pool.fetchrow(
        "SELECT o.*, c.username, c.first_name, m.name AS method_name FROM orders o JOIN customers c ON c.id=o.customer_id "
        "LEFT JOIN payment_methods m ON m.id=o.payment_method_id WHERE o.id=$1", order_id))
    if o:
        o["items"] = rows(await core.pool.fetch(
            "SELECT i.farm_id, i.price, i.cost, i.active, f.token_hint, f.status FROM order_items i "
            "JOIN farms f ON f.id=i.farm_id WHERE i.order_id=$1 ORDER BY i.id", order_id))
        o["payments"] = rows(await core.pool.fetch(
            "SELECT p.id, p.amount, p.currency, p.txid, p.status, p.reject_reason, p.reviewed_by, p.reviewed_at, p.created_at, "
            "m.name AS method_name FROM payments p JOIN payment_methods m ON m.id=p.method_id "
            "WHERE p.order_id=$1 ORDER BY p.id DESC", order_id))
    return o


async def customer_orders(core: Core, customer_id: int, limit: int = 10) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT id, ref, status, offer, lines, quantity, total, currency, reason, reserved_until, created_at, delivered_at "
        "FROM orders WHERE customer_id=$1 ORDER BY id DESC LIMIT $2", customer_id, limit))


async def list_orders(core: Core, *, status: str | None = None, search: str | None = None,
                      customer_id: int | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    q = ("SELECT o.id, o.ref, o.customer_id, o.status, o.offer, o.lines, o.quantity, o.total, o.currency, o.reason, "
         "o.failure_reason, o.reserved_until, o.created_at, o.updated_at, o.delivered_at, c.username, c.first_name "
         "FROM orders o JOIN customers c ON c.id=o.customer_id WHERE 1=1")
    args: list[Any] = []
    if status:
        args.append(status)
        q += f" AND o.status=${len(args)}"
    if customer_id is not None:
        args.append(customer_id)
        q += f" AND o.customer_id=${len(args)}"
    if search:
        s = search.strip()
        if s.isdigit():
            args.append(int(s))
            q += f" AND (o.customer_id=${len(args)} OR o.id=${len(args)})"
        else:
            args.append(f"%{s}%")
            q += f" AND (o.ref ILIKE ${len(args)} OR c.username ILIKE ${len(args)})"
    args += [limit, offset]
    q += f" ORDER BY o.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


def status_text(status: str, lang: str) -> str:
    return {"ar": STATUS_AR, "vi": STATUS_VI, "zh": STATUS_ZH}.get(lang, STATUS_EN).get(status, status)
