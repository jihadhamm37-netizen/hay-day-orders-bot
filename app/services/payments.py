"""Payment methods and payment proofs. A payment is confirmed only by an admin (or a trusted integration)."""
from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg

from ..core import Core, StoreError, fmt, row, rows
from . import orders as orders_svc
from .system import audit

log = logging.getLogger(__name__)
TXID_RE = re.compile(r"^[A-Za-z0-9_\-]{5,80}$")


def _esc(v: Any) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----------------------------------------------------------------- methods
async def list_methods(core: Core, active_only: bool = False, currency: str | None = None) -> list[dict]:
    q = "SELECT * FROM payment_methods WHERE 1=1"
    args: list[Any] = []
    if active_only:
        q += " AND is_active"
    if currency:
        args.append(currency)
        q += f" AND currency=${len(args)}"
    return rows(await core.pool.fetch(q + " ORDER BY sort_order, id", *args))


def _method_fields(data: dict, partial: bool) -> dict:
    out: dict[str, Any] = {}
    for f, mx in (("name", 60), ("account", 200), ("instructions", 2000)):
        if f in data and data[f] is not None:
            v = str(data[f]).strip()[:mx]
            if f in ("name", "account") and not v:
                raise StoreError("bad_input", "الاسم والمعرّف مطلوبان.")
            out[f] = v or None
        elif not partial and f != "instructions":
            raise StoreError("bad_input", "الاسم والمعرّف مطلوبان.")
    if data.get("kind"):
        if data["kind"] not in ("binance_pay", "manual", "other"):
            raise StoreError("bad_input", "نوع الوسيلة غير صالح.")
        out["kind"] = data["kind"]
    if data.get("currency"):
        c = str(data["currency"]).strip().upper()
        if not (2 <= len(c) <= 6 and c.isalpha()):
            raise StoreError("bad_input", "العملة غير صالحة.")
        out["currency"] = c
    for f in ("require_txid", "is_active"):
        if f in data and data[f] is not None:
            out[f] = bool(data[f])
    if data.get("sort_order") not in (None, ""):
        out["sort_order"] = int(data["sort_order"])
    return out


async def create_method(core: Core, actor: str, data: dict, ip: str | None = None) -> dict:
    f = _method_fields(data, partial=False)
    cols = list(f)
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.fetchrow(
            f"INSERT INTO payment_methods({', '.join(cols)}) VALUES({', '.join(f'${i+1}' for i in range(len(cols)))}) "
            "RETURNING *", *f.values())
        await audit(conn, actor, "method.create", "payment_method", r["id"], {"name": r["name"], "account": r["account"]}, ip)
    return dict(r)


async def update_method(core: Core, actor: str, method_id: int, data: dict, ip: str | None = None) -> dict:
    f = _method_fields(data, partial=True)
    if not f:
        raise StoreError("bad_input", "لا توجد تعديلات.")
    async with core.pool.acquire() as conn, conn.transaction():
        old = await conn.fetchrow("SELECT * FROM payment_methods WHERE id=$1", method_id)
        if not old:
            raise StoreError("not_found", "الوسيلة غير موجودة.")
        cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(f))
        r = await conn.fetchrow(f"UPDATE payment_methods SET {cols} WHERE id=$1 RETURNING *", method_id, *f.values())
        await audit(conn, actor, "method.update", "payment_method", method_id,
                    {k: {"old": old[k], "new": v} for k, v in f.items() if old[k] != v}, ip)
    return dict(r)


async def delete_method(core: Core, actor: str, method_id: int, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        used = await conn.fetchval("SELECT 1 FROM payments WHERE method_id=$1 LIMIT 1", method_id) or \
            await conn.fetchval("SELECT 1 FROM orders WHERE payment_method_id=$1 LIMIT 1", method_id)
        if used:
            raise StoreError("in_use", "الوسيلة مستخدمة في طلبات سابقة — عطّلها بدلاً من حذفها.")
        await conn.execute("DELETE FROM payment_methods WHERE id=$1", method_id)
        await audit(conn, actor, "method.delete", "payment_method", method_id, None, ip)


# ---------------------------------------------------------- customer side
async def choose_method(core: Core, customer_id: int, order_id: int, method_id: int) -> tuple[dict, dict]:
    m = await core.pool.fetchrow("SELECT * FROM payment_methods WHERE id=$1 AND is_active", method_id)
    if not m:
        raise StoreError("not_found", "وسيلة الدفع غير متاحة.")
    o = await core.pool.fetchrow(
        "UPDATE orders SET payment_method_id=$3, updated_at=now() WHERE id=$1 AND customer_id=$2 "
        "AND status='awaiting_payment' RETURNING *", order_id, customer_id, method_id)
    if not o:
        raise StoreError("bad_state", "هذا الطلب ليس بانتظار الدفع.")
    if m["currency"] != o["currency"]:
        raise StoreError("currency", f"هذه الوسيلة بعملة {m['currency']} والطلب بعملة {o['currency']}.")
    return dict(o), dict(m)


async def awaiting_proof_order(core: Core, customer_id: int) -> dict | None:
    """The order a newly sent screenshot belongs to (latest awaiting payment with a chosen method)."""
    return row(await core.pool.fetchrow(
        "SELECT * FROM orders WHERE customer_id=$1 AND status='awaiting_payment' AND payment_method_id IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", customer_id))


async def submit_proof(core: Core, customer_id: int, file_id: str, file_unique_id: str) -> dict:
    """Screenshot received → payment row created, order 'proof_received' (reservation stays until reviewed)."""
    o = await awaiting_proof_order(core, customer_id)
    if not o:
        raise StoreError("no_order", "لا يوجد طلب بانتظار الدفع.")
    async with core.pool.acquire() as conn:
        try:
            async with conn.transaction():
                upd = await conn.fetchrow(
                    "UPDATE orders SET status='proof_received', updated_at=now() WHERE id=$1 AND status='awaiting_payment' "
                    "RETURNING *", o["id"])
                if not upd:
                    raise StoreError("bad_state", "تم استلام إثبات لهذا الطلب مسبقاً.")
                m = await conn.fetchrow("SELECT * FROM payment_methods WHERE id=$1", o["payment_method_id"])
                p = await conn.fetchrow(
                    "INSERT INTO payments(order_id, method_id, amount, currency, proof_file_id, proof_file_unique_id) "
                    "VALUES($1,$2,$3,$4,$5,$6) RETURNING *",
                    o["id"], o["payment_method_id"], o["total"], o["currency"], file_id, file_unique_id)
                if m["require_txid"]:
                    await conn.execute("UPDATE customers SET awaiting=$2 WHERE id=$1", customer_id, f"txid:{p['id']}")
                else:
                    await conn.execute("UPDATE orders SET status='payment_review', updated_at=now() WHERE id=$1", o["id"])
        except asyncpg.UniqueViolationError as e:
            if "proof" in (e.constraint_name or ""):
                raise StoreError("proof_reused", "هذا الإثبات مستخدم مسبقاً في طلب آخر.")
            raise StoreError("duplicate", "يوجد دفع مسجل لهذا الطلب مسبقاً.")
    result = {"order": dict(upd), "payment": dict(p), "need_txid": bool(m["require_txid"])}
    if not m["require_txid"]:
        await _notify_review(core, p["id"])
    return result


async def submit_txid(core: Core, customer_id: int, payment_id: int, txid: str) -> dict:
    txid = (txid or "").strip()
    if not TXID_RE.match(txid):
        raise StoreError("bad_txid", "رقم العملية غير صالح. انسخه من تفاصيل التحويل.")
    async with core.pool.acquire() as conn:
        try:
            async with conn.transaction():
                p = await conn.fetchrow(
                    "UPDATE payments p SET txid=$3 FROM orders o WHERE p.id=$1 AND o.id=p.order_id AND o.customer_id=$2 "
                    "AND p.status='pending' AND p.txid IS NULL RETURNING p.*", payment_id, customer_id, txid)
                if not p:
                    raise StoreError("bad_state", "لا يوجد دفع بانتظار رقم العملية.")
                await conn.execute("UPDATE orders SET status='payment_review', updated_at=now() WHERE id=$1 "
                                   "AND status='proof_received'", p["order_id"])
                await conn.execute("UPDATE customers SET awaiting=NULL WHERE id=$1", customer_id)
        except asyncpg.UniqueViolationError:
            raise StoreError("proof_reused", "رقم العملية هذا مستخدم مسبقاً في طلب آخر.")
    await _notify_review(core, p["id"])
    return dict(p)


async def _notify_review(core: Core, payment_id: int) -> None:
    if not core.messenger:
        return
    p = await get_payment(core, payment_id)
    text = (f"<b>إثبات دفع بانتظار المراجعة</b>\nالطلب: <code>{p['order_ref']}</code>\n"
            f"العميل: <code>{p['customer_id']}</code> {('@' + _esc(p['username'])) if p['username'] else ''}\n"
            f"المبلغ: <b>{fmt(p['amount'])} {p['currency']}</b>\nالوسيلة: {_esc(p['method_name'])} ({_esc(p['account'])})\n"
            f"رقم العملية: <code>{_esc(p['txid'] or '—')}</code>\nتحقق من وصول المبلغ فعلياً قبل الموافقة.")
    await core.messenger.notify_admins(text, perm="payments", photo=p["proof_file_id"],
                                       reply_markup=("payment_review", payment_id))


# -------------------------------------------------------------- admin side
async def approve(core: Core, actor: str, payment_id: int, ip: str | None = None) -> dict:
    async with core.pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow("UPDATE payments SET status='approved', reviewed_by=$2, reviewed_at=now() "
                                "WHERE id=$1 AND status='pending' RETURNING *", payment_id, actor)
        if not p:
            raise StoreError("already", "تمت مراجعة هذا الدفع مسبقاً.")
        o = await conn.fetchrow(
            "UPDATE orders SET status='payment_confirmed', paid_at=now(), updated_at=now() WHERE id=$1 "
            "AND status IN ('proof_received','payment_review','awaiting_payment') RETURNING *", p["order_id"])
        if not o:
            raise StoreError("bad_state", "الطلب لم يعد بانتظار الدفع (ربما أُلغي).")
        await conn.execute("UPDATE customers SET awaiting=NULL WHERE id=$1 AND awaiting=$2", o["customer_id"], f"txid:{payment_id}")
        await audit(conn, actor, "payment.approve", "payment", payment_id,
                    {"order": o["ref"], "amount": p["amount"], "currency": p["currency"], "txid": p["txid"]}, ip)
    if core.messenger:
        await core.messenger.notify_customer(o["customer_id"], "payment_confirmed", ref=o["ref"])
    await orders_svc.deliver(core, o["id"], actor)
    return dict(p)


async def reject(core: Core, actor: str, payment_id: int, reason: str, *, close_order: bool = False,
                 ip: str | None = None) -> dict:
    """Reject the proof. Default: order returns to 'awaiting_payment' so the customer can send a correct proof.
    close_order=True rejects the whole order and releases the farms."""
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StoreError("reason_required", "اكتب سبب الرفض ليظهر للعميل.")
    async with core.pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow("UPDATE payments SET status='rejected', reject_reason=$3, reviewed_by=$2, reviewed_at=now() "
                                "WHERE id=$1 AND status='pending' RETURNING *", payment_id, actor, reason)
        if not p:
            raise StoreError("already", "تمت مراجعة هذا الدفع مسبقاً.")
        o = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", p["order_id"])
        await conn.execute("UPDATE customers SET awaiting=NULL WHERE id=$1 AND awaiting=$2", o["customer_id"], f"txid:{payment_id}")
        if not close_order:
            await conn.execute(
                "UPDATE orders SET status='awaiting_payment', reserved_until=greatest(reserved_until, now() + interval '30 minutes'), "
                "updated_at=now() WHERE id=$1 AND status IN ('proof_received','payment_review')", p["order_id"])
        await audit(conn, actor, "payment.reject", "payment", payment_id,
                    {"order": o["ref"], "reason": reason, "close_order": close_order}, ip)
    if close_order:
        await orders_svc._close(core, o["id"], "rejected", reason, actor, ip=ip)
    elif core.messenger:
        await core.messenger.notify_customer(o["customer_id"], "payment_rejected", ref=o["ref"], reason=reason)
    return dict(p)


async def get_payment(core: Core, payment_id: int) -> dict | None:
    return row(await core.pool.fetchrow(
        "SELECT p.*, o.ref AS order_ref, o.customer_id, o.status AS order_status, o.offer, o.quantity, "
        "c.username, c.first_name, m.name AS method_name, m.account, m.kind "
        "FROM payments p JOIN orders o ON o.id=p.order_id JOIN customers c ON c.id=o.customer_id "
        "JOIN payment_methods m ON m.id=p.method_id WHERE p.id=$1", payment_id))


async def list_payments(core: Core, *, status: str | None = None, search: str | None = None,
                        limit: int = 50, offset: int = 0) -> list[dict]:
    q = ("SELECT p.id, p.order_id, p.amount, p.currency, p.txid, p.status, p.reject_reason, p.reviewed_by, p.reviewed_at, "
         "p.created_at, (p.proof_file_id IS NOT NULL) AS has_proof, o.ref AS order_ref, o.customer_id, o.status AS order_status, "
         "c.username, m.name AS method_name FROM payments p JOIN orders o ON o.id=p.order_id "
         "JOIN customers c ON c.id=o.customer_id JOIN payment_methods m ON m.id=p.method_id WHERE 1=1")
    args: list[Any] = []
    if status:
        args.append(status)
        q += f" AND p.status=${len(args)}"
    if search:
        args.append(f"%{search.strip()}%")
        q += f" AND (o.ref ILIKE ${len(args)} OR p.txid ILIKE ${len(args)} OR c.id::text = trim('%' from ${len(args)}))"
    args += [limit, offset]
    q += f" ORDER BY p.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))
