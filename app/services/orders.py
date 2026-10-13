"""Purchase flow: prepare → confirm (atomic reserve + charge) → deliver → complete."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from ..core import Core, StoreError, fmt, money, row, rows
from ..security import make_ref
from .catalog import check_stock_alert
from .system import audit, raise_alert
from .wallet import apply_tx

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "pending": "بانتظار التأكيد",
    "processing": "قيد المعالجة",
    "completed": "مكتمل",
    "cancelled": "ملغي",
    "needs_review": "يحتاج إلى مراجعة",
}
PENDING_TTL_MIN = 15
STUCK_PROCESSING_MIN = 5


async def prepare(core: Core, user_id: int, type_id: int, price: Any, qty: int = 1) -> dict:
    """Create order(s) awaiting the customer's confirmation. Nothing is reserved or charged yet.

    Buying several farms creates one order per account, all sharing a batch id, confirmed together.
    Returns the first order with extra keys: batch_id, qty, total, order_ids.
    """
    from .system import setting
    price = money(price)
    try:
        max_qty = max(1, int(await setting(core, "max_quantity", "20")))
    except ValueError:
        max_qty = 20
    if not isinstance(qty, int) or qty < 1 or qty > max_qty:
        raise StoreError("bad_qty", f"العدد يجب أن يكون بين 1 و {max_qty}.", max=max_qty)
    user = await core.pool.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
    if not user:
        raise StoreError("not_found", "المستخدم غير موجود.")
    if user["is_banned"]:
        raise StoreError("banned", "حسابك موقوف. تواصل مع الدعم.")
    t = await core.pool.fetchrow("SELECT * FROM farm_types WHERE id=$1", type_id)
    if not t or not t["is_active"]:
        raise StoreError("unavailable", "هذا النوع غير متاح حالياً.")
    stock = await core.pool.fetchval(
        "SELECT COUNT(*) FROM farm_accounts WHERE type_id=$1 AND status='available' "
        "AND COALESCE(custom_price, $2)=$3", type_id, t["price"], price)
    if stock < qty:
        raise StoreError("out_of_stock",
                         f"عذراً، المتوفر بهذا السعر {stock} فقط." if stock else "عذراً، نفد المخزون بهذا السعر.",
                         available=stock)
    total = price * qty
    if user["balance"] < total:
        raise StoreError("insufficient_funds",
                         f"رصيدك ({fmt(user['balance'])} USDT) لا يكفي. الإجمالي {fmt(total)} USDT.",
                         balance=fmt(user["balance"]), total=fmt(total))
    snapshot = {"name": t["name"], "lvl": t["lvl"], "barn": t["barn"], "silo": t["silo"]}
    batch = uuid.uuid4().hex
    base = make_ref("ORD")
    created = []
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE orders SET status='cancelled', failure_reason='استُبدل بطلب أحدث', "
                           "updated_at=now() WHERE user_id=$1 AND status='pending'", user_id)
        for i in range(qty):
            ref = base if qty == 1 else f"{base}-{i + 1}"
            created.append(await conn.fetchrow(
                "INSERT INTO orders(ref, user_id, type_id, price, status, type_snapshot, idempotency_key, batch_id) "
                "VALUES($1,$2,$3,$4,'pending',$5,$6,$7) RETURNING *",
                ref, user_id, type_id, price, snapshot, f"prep:{uuid.uuid4()}", batch))
    first = dict(created[0])
    first.update(batch_id=batch, qty=qty, total=total, batch_ref=base, order_ids=[o["id"] for o in created])
    return first


async def _confirm(core: Core, user_id: int, order_id: int) -> list[dict]:
    """Atomically reserve one account per order of the batch and charge them — all or nothing."""
    async with core.pool.acquire() as conn:
        try:
            async with conn.transaction():
                # The status flip is the double-click guard: only one caller can move pending → processing.
                os_ = await conn.fetch(
                    "UPDATE orders SET status='processing', updated_at=now() WHERE user_id=$2 AND status='pending' "
                    "AND created_at > now() - make_interval(mins => $3) AND (id=$1 OR batch_id = "
                    "(SELECT batch_id FROM orders WHERE id=$1 AND user_id=$2)) RETURNING *",
                    order_id, user_id, PENDING_TTL_MIN)
                if not os_:
                    cur = await conn.fetchrow("SELECT status, user_id FROM orders WHERE id=$1", order_id)
                    if not cur or cur["user_id"] != user_id:
                        raise StoreError("not_found", "الطلب غير موجود.")
                    if cur["status"] == "pending":
                        raise StoreError("expired", "انتهت صلاحية هذا الطلب، ابدأ الشراء من جديد.")
                    raise StoreError("already", f"تمت معالجة هذا الطلب مسبقاً ({STATUS_LABELS[cur['status']]}).")
                os_ = sorted(os_, key=lambda r: r["id"])
                if await conn.fetchval("SELECT is_banned FROM users WHERE id=$1", user_id):
                    raise StoreError("banned", "حسابك موقوف. تواصل مع الدعم.")
                first = os_[0]
                accs = await conn.fetch(
                    "SELECT a.id FROM farm_accounts a JOIN farm_types t ON t.id=a.type_id "
                    "WHERE a.type_id=$1 AND a.status='available' AND t.is_active "
                    "AND COALESCE(a.custom_price, t.price)=$2 "
                    "ORDER BY a.id LIMIT $3 FOR UPDATE OF a SKIP LOCKED",
                    first["type_id"], first["price"], len(os_))
                if len(accs) < len(os_):
                    raise StoreError("out_of_stock", "عذراً، نفد المخزون قبل إتمام الطلب. لم يُخصم أي مبلغ.",
                                     available=len(accs))
                result = []
                for o, acc in zip(os_, accs):
                    await conn.execute("UPDATE farm_accounts SET status='reserved', updated_at=now() "
                                       "WHERE id=$1 AND status='available'", acc["id"])
                    o = await conn.fetchrow("UPDATE orders SET account_id=$2 WHERE id=$1 RETURNING *", o["id"], acc["id"])
                    await apply_tx(conn, user_id=user_id, amount=-o["price"], kind="purchase",
                                   idempotency_key=f"order:{o['id']}", order_id=o["id"],
                                   actor=f"tg:{user_id}", reason=f"شراء {o['type_snapshot']['name']} ({o['ref']})")
                    result.append(dict(o))
                return result
        except StoreError as e:
            if e.code not in ("already", "not_found"):
                await conn.execute(
                    "UPDATE orders SET status='cancelled', failure_reason=$2, updated_at=now() WHERE user_id=$3 "
                    "AND status='pending' AND (id=$1 OR batch_id=(SELECT batch_id FROM orders WHERE id=$1))",
                    order_id, e.message, user_id)
            raise


async def purchase(core: Core, user_id: int, order_id: int) -> dict:
    """Confirm + deliver every order of the batch. Returns the first order, with 'batch' = all orders."""
    confirmed = await _confirm(core, user_id, order_id)
    if len(confirmed) == 1:
        await deliver(core, confirmed[0]["id"])
    else:
        await deliver_batch(core, [o["id"] for o in confirmed])
    final = [await get_order(core, o["id"]) for o in confirmed]
    first = dict(final[0])
    first["batch"] = final
    return first


async def deliver(core: Core, order_id: int, *, actor: str = "system", part: tuple[int, int] | None = None) -> bool:
    """Send credentials. Only marks the order completed after Telegram accepted the message."""
    o = await core.pool.fetchrow(
        "SELECT o.*, a.login_enc, a.password_enc, COALESCE(a.photo_file_id, t.photo_file_id) AS photo "
        "FROM orders o JOIN farm_accounts a ON a.id=o.account_id JOIN farm_types t ON t.id=o.type_id "
        "WHERE o.id=$1", order_id)
    if not o or o["status"] != "processing":
        return False
    try:
        if core.messenger is None:
            raise RuntimeError("messenger not configured")
        login = core.vault.decrypt(o["login_enc"])
        password = core.vault.decrypt(o["password_enc"])
        await core.messenger.send_credentials(o["user_id"], dict(o) | {"part": part}, login, password)
    except Exception as e:  # Telegram refused, user blocked bot, network, …
        log.warning("delivery failed for order %s: %s", o["ref"], e)
        await core.pool.execute(
            "UPDATE orders SET status='needs_review', failure_reason=$2, updated_at=now() "
            "WHERE id=$1 AND status='processing'", order_id, f"فشل التسليم: {type(e).__name__}: {str(e)[:200]}")
        await raise_alert(core, "error", "delivery_failed",
                          f"تعذر تسليم الطلب {o['ref']} للمستخدم {o['user_id']}. المبلغ مخصوم والحساب محجوز — "
                          f"راجع الطلب لإعادة الإرسال أو الاسترداد.", "order", order_id, perm="orders")
        return False
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE orders SET status='completed', delivered_at=now(), failure_reason=NULL, "
                           "updated_at=now() WHERE id=$1 AND status IN ('processing','needs_review')", order_id)
        await conn.execute("UPDATE farm_accounts SET status='sold', sold_at=now(), updated_at=now() "
                           "WHERE id=$1 AND status='reserved'", o["account_id"])
        if actor != "system":
            await audit(conn, actor, "order.redeliver", "order", order_id, None)
    if core.messenger:
        snap = o["type_snapshot"]
        user = await core.pool.fetchrow("SELECT username FROM users WHERE id=$1", o["user_id"])
        uname = f"@{user['username']}" if user and user["username"] else str(o["user_id"])
        try:
            await core.messenger.notify_admins(
                f"<b>عملية بيع جديدة</b>\nالطلب: <code>{o['ref']}</code>\nالنوع: {snap['name']} — LVL {snap['lvl']}\n"
                f"السعر: {fmt(o['price'])} USDT\nالمشتري: {uname} (<code>{o['user_id']}</code>)", perm="orders")
        except Exception:
            log.exception("sale notification failed")
    await check_stock_alert(core, o["type_id"])
    return True


async def deliver_batch(core: Core, order_ids: list[int]) -> bool:
    """Send all accounts of a multi-farm purchase in ONE message; complete them only if Telegram accepted it."""
    rs = await core.pool.fetch(
        "SELECT o.*, a.login_enc, a.password_enc, t.photo_file_id AS photo "
        "FROM orders o JOIN farm_accounts a ON a.id=o.account_id JOIN farm_types t ON t.id=o.type_id "
        "WHERE o.id = ANY($1::bigint[]) AND o.status='processing' ORDER BY o.id", order_ids)
    if not rs:
        return False
    first = rs[0]
    try:
        if core.messenger is None:
            raise RuntimeError("messenger not configured")
        items = [(dict(r), core.vault.decrypt(r["login_enc"]), core.vault.decrypt(r["password_enc"])) for r in rs]
        await core.messenger.send_credentials_batch(first["user_id"], items)
    except Exception as e:
        log.warning("batch delivery failed for %s: %s", first["ref"], e)
        await core.pool.execute(
            "UPDATE orders SET status='needs_review', failure_reason=$2, updated_at=now() "
            "WHERE id = ANY($1::bigint[]) AND status='processing'", [r["id"] for r in rs],
            f"فشل التسليم: {type(e).__name__}: {str(e)[:200]}")
        await raise_alert(core, "error", "delivery_failed",
                          f"تعذر تسليم {len(rs)} حساب للمستخدم {first['user_id']} (الطلب {first['ref']}…). المبلغ مخصوم "
                          f"والحسابات محجوزة — راجع الطلبات لإعادة الإرسال أو الاسترداد.", "order", first["id"],
                          perm="orders")
        return False
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE orders SET status='completed', delivered_at=now(), failure_reason=NULL, "
                           "updated_at=now() WHERE id = ANY($1::bigint[]) AND status IN ('processing','needs_review')",
                           [r["id"] for r in rs])
        await conn.execute("UPDATE farm_accounts SET status='sold', sold_at=now(), updated_at=now() "
                           "WHERE id = ANY($1::bigint[]) AND status='reserved'", [r["account_id"] for r in rs])
    if core.messenger:
        snap = first["type_snapshot"]
        user = await core.pool.fetchrow("SELECT username FROM users WHERE id=$1", first["user_id"])
        uname = f"@{user['username']}" if user and user["username"] else str(first["user_id"])
        total = sum(r["price"] for r in rs)
        try:
            await core.messenger.notify_admins(
                f"<b>عملية بيع جديدة</b> — {len(rs)} مزارع\nالطلب: <code>{first['ref'].rsplit('-', 1)[0]}</code>\n"
                f"النوع: {str(snap['name']).replace('<', '&lt;')} — LVL {snap['lvl']}\n"
                f"الإجمالي: {fmt(total)} USDT\nالمشتري: {uname} (<code>{first['user_id']}</code>)", perm="orders")
        except Exception:
            log.exception("sale notification failed")
    await check_stock_alert(core, first["type_id"])
    return True


async def buyer_batch_credentials(core: Core, user_id: int, order_id: int) -> list[tuple[dict, str, str]]:
    """All completed accounts bought together with this order (buyer only)."""
    rs = await core.pool.fetch(
        "SELECT o.*, a.login_enc, a.password_enc FROM orders o JOIN farm_accounts a ON a.id=o.account_id "
        "WHERE o.user_id=$2 AND o.status='completed' AND (o.id=$1 OR o.batch_id = "
        "(SELECT batch_id FROM orders WHERE id=$1 AND user_id=$2)) ORDER BY o.id", order_id, user_id)
    if not rs:
        raise StoreError("not_found", "لا توجد بيانات لهذا الطلب.")
    return [(dict(r), core.vault.decrypt(r["login_enc"]), core.vault.decrypt(r["password_enc"])) for r in rs]


async def retry_delivery(core: Core, order_id: int, *, user_id: int | None = None, actor: str = "system") -> bool:
    """Re-send credentials for an order stuck in needs_review (by its buyer or an admin)."""
    q = "UPDATE orders SET status='processing', updated_at=now() WHERE id=$1 AND status='needs_review' " \
        "AND account_id IS NOT NULL"
    args: list[Any] = [order_id]
    if user_id is not None:
        q += " AND user_id=$2"
        args.append(user_id)
    claimed = await core.pool.fetchrow(q + " RETURNING id", *args)
    if not claimed:
        raise StoreError("not_retryable", "لا يمكن إعادة إرسال هذا الطلب.")
    return await deliver(core, order_id, actor=actor)


async def mark_delivered(core: Core, actor: str, order_id: int, note: str = "", ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        o = await conn.fetchrow("UPDATE orders SET status='completed', delivered_at=now(), admin_note=$2, "
                                "updated_at=now() WHERE id=$1 AND status='needs_review' RETURNING *",
                                order_id, note or None)
        if not o:
            raise StoreError("bad_state", "الطلب ليس بحالة «يحتاج إلى مراجعة».")
        await conn.execute("UPDATE farm_accounts SET status='sold', sold_at=now() WHERE id=$1 AND status='reserved'",
                           o["account_id"])
        await audit(conn, actor, "order.mark_delivered", "order", order_id, {"note": note}, ip)


async def refund(core: Core, actor: str, order_id: int, reason: str, restock: bool = False,
                 ip: str | None = None) -> dict:
    """Cancel a charged order and return the money to the wallet (exactly once)."""
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StoreError("reason_required", "يجب كتابة سبب الاسترداد.")
    async with core.pool.acquire() as conn, conn.transaction():
        o = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
        if not o:
            raise StoreError("not_found", "الطلب غير موجود.")
        if o["status"] not in ("needs_review", "completed", "processing"):
            raise StoreError("bad_state", "لا يمكن استرداد طلب بهذه الحالة.")
        if o["status"] == "processing" and await conn.fetchval(
                "SELECT updated_at > now() - interval '2 minutes' FROM orders WHERE id=$1", order_id):
            raise StoreError("busy", "الطلب قيد التسليم الآن، حاول بعد دقيقتين.")
        charged = await conn.fetchval("SELECT 1 FROM wallet_transactions WHERE idempotency_key=$1",
                                      f"order:{order_id}")
        tx = None
        if charged:
            tx = await apply_tx(conn, user_id=o["user_id"], amount=o["price"], kind="refund",
                                idempotency_key=f"refund:{order_id}", order_id=order_id, actor=actor, reason=reason)
        await conn.execute("UPDATE orders SET status='cancelled', admin_note=$2, updated_at=now() WHERE id=$1",
                           order_id, reason)
        if o["account_id"]:
            acc_status = await conn.fetchval("SELECT status FROM farm_accounts WHERE id=$1 FOR UPDATE", o["account_id"])
            if acc_status == "reserved":
                await conn.execute("UPDATE farm_accounts SET status=$2, updated_at=now() WHERE id=$1",
                                   o["account_id"], "available" if restock else "disabled")
        await audit(conn, actor, "order.refund", "order", order_id,
                    {"amount": o["price"], "reason": reason, "restock": restock,
                     "previous_status": o["status"]}, ip)
    if core.messenger and tx:
        await core.messenger.notify_user(o["user_id"], key="n_refund", ref=o["ref"], amount=fmt(o["price"]),
                                         reason=reason.replace("<", "&lt;"))
    return await get_order(core, order_id)


async def get_order(core: Core, order_id: int) -> dict | None:
    return row(await core.pool.fetchrow(
        "SELECT o.*, a.login_hint, u.username FROM orders o LEFT JOIN farm_accounts a ON a.id=o.account_id "
        "LEFT JOIN users u ON u.id=o.user_id WHERE o.id=$1", order_id))


async def get_order_by_ref(core: Core, ref: str) -> dict | None:
    oid = await core.pool.fetchval("SELECT id FROM orders WHERE ref=$1", ref.strip().upper())
    return await get_order(core, oid) if oid else None


async def buyer_credentials(core: Core, user_id: int, order_id: int) -> tuple[dict, str, str]:
    """Credentials are only ever revealed to the buyer of a completed order."""
    o = await core.pool.fetchrow(
        "SELECT o.*, a.login_enc, a.password_enc, COALESCE(a.photo_file_id, t.photo_file_id) AS photo "
        "FROM orders o JOIN farm_accounts a ON a.id=o.account_id JOIN farm_types t ON t.id=o.type_id "
        "WHERE o.id=$1 AND o.user_id=$2 AND o.status='completed'", order_id, user_id)
    if not o:
        raise StoreError("not_found", "لا توجد بيانات لهذا الطلب.")
    return dict(o), core.vault.decrypt(o["login_enc"]), core.vault.decrypt(o["password_enc"])


async def list_orders(core: Core, *, user_id: int | None = None, status: str | None = None,
                      search: str | None = None, limit: int = 50, offset: int = 0,
                      include_pending: bool = False) -> list[dict]:
    q = ("SELECT o.id, o.ref, o.user_id, o.type_id, o.account_id, o.price, o.status, o.type_snapshot, "
         "o.failure_reason, o.admin_note, o.delivered_at, o.created_at, o.updated_at, "
         "a.login_hint, u.username FROM orders o LEFT JOIN farm_accounts a ON a.id=o.account_id "
         "LEFT JOIN users u ON u.id=o.user_id WHERE 1=1")
    args: list[Any] = []
    if user_id is not None:
        args.append(user_id)
        q += f" AND o.user_id=${len(args)}"
    if status:
        args.append(status)
        q += f" AND o.status=${len(args)}"
    elif not include_pending:
        q += " AND NOT (o.status='cancelled' AND o.account_id IS NULL) AND o.status<>'pending'"
    if search:
        s = search.strip()
        if s.isdigit():
            args.append(int(s))
            q += f" AND (o.user_id=${len(args)} OR o.id=${len(args)})"
        else:
            args.append(f"%{s.upper()}%")
            q += f" AND o.ref LIKE ${len(args)}"
    args += [limit, offset]
    q += f" ORDER BY o.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


async def maintenance(core: Core) -> dict:
    """Expire unconfirmed orders and flag orders whose delivery never finished (e.g. crash mid-way)."""
    expired = await core.pool.execute(
        "UPDATE orders SET status='cancelled', failure_reason='انتهت مهلة التأكيد', updated_at=now() "
        "WHERE status='pending' AND created_at < now() - make_interval(mins => $1)", PENDING_TTL_MIN)
    stuck = await core.pool.fetch(
        "UPDATE orders SET status='needs_review', failure_reason='لم يتم تأكيد التسليم (توقف أثناء المعالجة)', "
        "updated_at=now() WHERE status='processing' AND updated_at < now() - make_interval(mins => $1) "
        "RETURNING id, ref, user_id", STUCK_PROCESSING_MIN)
    for s in stuck:
        await raise_alert(core, "error", "delivery_unconfirmed",
                          f"الطلب {s['ref']} توقف أثناء التسليم ويحتاج إلى مراجعة.", "order", s["id"], perm="orders")
    return {"expired": int(expired.split()[-1]), "stuck": len(stuck)}
