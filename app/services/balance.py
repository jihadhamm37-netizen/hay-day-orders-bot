"""Customer balance ($ / USDT): staff top up by access code, customers spend it on orders.
Every change is one row in balance_log and an audit entry; the balance can never go below zero."""
from __future__ import annotations

from decimal import Decimal

from ..core import Core, StoreError, fmt, money, row, rows
from . import customers as cust_svc
from .system import audit

BALANCE_CURRENCIES = ("USDT", "USD")


async def get(core: Core, customer_id: int) -> Decimal:
    return await core.pool.fetchval("SELECT balance FROM customers WHERE id=$1", customer_id) or Decimal("0")


async def history(core: Core, customer_id: int, limit: int = 30) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT l.id, l.delta, l.balance_after, l.kind, l.note, l.actor, l.created_at, o.ref AS order_ref "
        "FROM balance_log l LEFT JOIN orders o ON o.id=l.order_id WHERE l.customer_id=$1 ORDER BY l.id DESC LIMIT $2",
        customer_id, limit))


async def _find_customer(conn, code_or_id) -> dict:
    s = str(code_or_id or "").strip()
    if s.isdigit():
        c = await conn.fetchrow("SELECT * FROM customers WHERE id=$1 FOR UPDATE", int(s))
    else:
        c = await conn.fetchrow("SELECT * FROM customers WHERE access_code=$1 FOR UPDATE", cust_svc.normalize_code(s))
    if not c:
        raise StoreError("not_found", "لا يوجد عميل بهذا الكود.")
    return dict(c)


async def adjust(core: Core, actor: str, code_or_id, amount, note: str | None = None, ip: str | None = None) -> dict:
    """Staff adds (positive) or deducts (negative) balance for the customer with this access code."""
    amt = money(amount)
    if amt == 0:
        raise StoreError("bad_amount", "اكتب مبلغًا غير صفري.")
    note = (note or "").strip()[:300] or None
    async with core.pool.acquire() as conn, conn.transaction():
        c = await _find_customer(conn, code_or_id)
        new = c["balance"] + amt
        if new < 0:
            raise StoreError("insufficient", f"رصيد العميل {fmt(c['balance'])} $ فقط، لا يمكن خصم {fmt(-amt)} $.")
        await conn.execute("UPDATE customers SET balance=$2 WHERE id=$1", c["id"], new)
        await conn.execute(
            "INSERT INTO balance_log(customer_id, delta, balance_after, kind, note, actor) VALUES($1,$2,$3,$4,$5,$6)",
            c["id"], amt, new, "topup" if amt > 0 else "deduct", note, actor)
        await audit(conn, actor, "balance.topup" if amt > 0 else "balance.deduct", "customer", c["id"],
                    {"code": c["access_code"], "amount": amt, "balance": new, "note": note}, ip)
    if core.messenger:
        await core.messenger.notify_customer(c["id"], "balance_added" if amt > 0 else "balance_deducted",
                                             amount=fmt(abs(amt)), balance=fmt(new))
    return {"customer_id": c["id"], "code": c["access_code"], "name": c["first_name"], "balance": fmt(new)}


async def pay_order(core: Core, customer_id: int, order_id: int) -> dict:
    """Buy with balance, no staff approval: the balance must cover the whole order; it is deducted once and the
    farms reserved for this order are delivered right away. If delivery fails the order waits for staff."""
    async with core.pool.acquire() as conn, conn.transaction():
        o = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 AND customer_id=$2 FOR UPDATE", order_id, customer_id)
        if not o:
            raise StoreError("not_found", "الطلب غير موجود.")
        if o["status"] != "awaiting_payment":
            raise StoreError("bad_state", "هذا الطلب ليس بانتظار الدفع.")
        if o["currency"] not in BALANCE_CURRENCIES:
            raise StoreError("currency", f"لا يمكن دفع طلب بعملة {o['currency']} من الرصيد.")
        c = await conn.fetchrow("SELECT balance FROM customers WHERE id=$1 FOR UPDATE", customer_id)
        if c["balance"] < o["total"]:
            raise StoreError("insufficient",
                             f"رصيدك ${fmt(c['balance'])} لا يكفي لهذا الطلب (${fmt(o['total'])}). ينقصك "
                             f"${fmt(o['total'] - c['balance'])} — اشحن رصيدك عبر الإدارة أو اختر وسيلة دفع أخرى.")
        new = c["balance"] - o["total"]
        await conn.execute("UPDATE customers SET balance=$2 WHERE id=$1", customer_id, new)
        await conn.execute(
            "INSERT INTO balance_log(customer_id, delta, balance_after, kind, order_id, note, actor) "
            "VALUES($1,$2,$3,'order',$4,$5,$6)", customer_id, -o["total"], new, o["id"], o["ref"], f"customer:{customer_id}")
        o = await conn.fetchrow(
            "UPDATE orders SET status='processing', paid_at=now(), paid_from_balance=total, updated_at=now() "
            "WHERE id=$1 RETURNING *", order_id)
        await audit(conn, f"customer:{customer_id}", "order.paid_from_balance", "order", order_id,
                    {"ref": o["ref"], "amount": o["total"], "balance": new})
    from . import orders as orders_svc          # local import: orders imports this module
    if core.messenger:
        await core.messenger.notify_customer(customer_id, "paid_from_balance", ref=o["ref"], amount=fmt(o["total"]),
                                             balance=fmt(new))
    delivered = await orders_svc.deliver(core, o["id"], f"balance:{customer_id}")
    if core.messenger:
        if delivered:
            await core.messenger.notify_admins(
                f"شراء من الرصيد — الطلب {o['ref']} (${fmt(o['total'])}) دُفع من رصيد العميل وسُلّم تلقائيًا.", perm="orders")
        else:
            await core.messenger.notify_customer(customer_id, "payment_confirmed", ref=o["ref"])
            await core.messenger.notify_admins(
                f"شراء من الرصيد — الطلب {o['ref']} (${fmt(o['total'])}) مدفوع لكن التسليم التلقائي تعذّر. "
                "افتح الطلب واضغط «تسليم الطلب».", perm="orders")
    return dict(await core.pool.fetchrow("SELECT * FROM orders WHERE id=$1", order_id))


async def refund_in_tx(conn, o: dict, actor: str) -> Decimal | None:
    """Inside an order-closing transaction: give back what was paid from the balance (exactly once)."""
    if not o.get("paid_from_balance"):
        return None
    amt = o["paid_from_balance"]
    new = await conn.fetchval("UPDATE customers SET balance=balance+$2 WHERE id=$1 RETURNING balance", o["customer_id"], amt)
    await conn.execute("UPDATE orders SET paid_from_balance=NULL WHERE id=$1", o["id"])
    await conn.execute(
        "INSERT INTO balance_log(customer_id, delta, balance_after, kind, order_id, note, actor) VALUES($1,$2,$3,'refund',$4,$5,$6)",
        o["customer_id"], amt, new, o["id"], o["ref"], actor)
    return amt


async def customer_summary(core: Core, customer_id: int) -> dict:
    c = row(await core.pool.fetchrow("SELECT balance FROM customers WHERE id=$1", customer_id)) or {"balance": 0}
    return {"balance": fmt(c["balance"])}
