"""Users and wallets. Balances change only by inserting wallet_transactions."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import asyncpg

from ..core import Core, StoreError, money, row, rows
from ..security import make_ref
from .system import audit

KIND_LABELS = {
    "deposit": "شحن رصيد",
    "purchase": "شراء مزرعة",
    "refund": "استرداد",
    "admin_credit": "إضافة من الإدارة",
    "admin_debit": "خصم من الإدارة",
}


# -------------------------------------------------------------------- users
async def touch_user(core: Core, user_id: int, username: str | None, first_name: str | None) -> dict:
    r = await core.pool.fetchrow(
        "INSERT INTO users(id, username, first_name) VALUES($1,$2,$3) "
        "ON CONFLICT (id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name, "
        "last_seen_at=now() RETURNING *",
        user_id, username, first_name)
    return dict(r)


async def get_user(core: Core, user_id: int) -> dict | None:
    return row(await core.pool.fetchrow("SELECT * FROM users WHERE id=$1", user_id))


async def search_users(core: Core, query: str = "", limit: int = 50, offset: int = 0,
                       with_balance: bool = False) -> list[dict]:
    q = ("SELECT u.*, (SELECT count(*) FROM orders o WHERE o.user_id=u.id AND o.status='completed') AS orders_count "
         "FROM users u WHERE 1=1")
    args: list[Any] = []
    query = (query or "").strip().lstrip("@")
    if query:
        if query.isdigit():
            args.append(int(query))
            q += f" AND u.id = ${len(args)}"
        else:
            args.append(f"%{query}%")
            q += f" AND (u.username ILIKE ${len(args)} OR u.first_name ILIKE ${len(args)})"
    if with_balance:
        q += " AND u.balance > 0"
    args += [limit, offset]
    q += f" ORDER BY u.balance DESC, u.last_seen_at DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


async def set_banned(core: Core, actor: str, user_id: int, banned: bool, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE users SET is_banned=$2 WHERE id=$1", user_id, banned)
        if r.endswith("0"):
            raise StoreError("not_found", "المستخدم غير موجود.")
        await audit(conn, actor, "user.ban" if banned else "user.unban", "user", user_id, None, ip)


# ------------------------------------------------------------------- wallet
async def apply_tx(conn: asyncpg.Connection, *, user_id: int, amount: Decimal, kind: str,
                   idempotency_key: str, order_id: int | None = None, deposit_id: int | None = None,
                   actor: str | None = None, reason: str | None = None) -> dict:
    """Insert one ledger row; the DB trigger moves the balance atomically.

    Must be called inside a transaction. Raises StoreError on insufficient funds or
    when the idempotency key was already used (the whole transaction must roll back).
    """
    try:
        async with conn.transaction():  # savepoint so callers get a clean error
            r = await conn.fetchrow(
                "INSERT INTO wallet_transactions(ref, user_id, amount, balance_before, balance_after, kind, "
                "idempotency_key, order_id, deposit_id, actor, reason) "
                "VALUES($1,$2,$3,0,0,$4,$5,$6,$7,$8,$9) RETURNING *",
                make_ref("TX"), user_id, amount, kind, idempotency_key, order_id, deposit_id, actor, reason)
    except asyncpg.UniqueViolationError as e:
        if "idempotency" in (e.constraint_name or ""):
            raise StoreError("duplicate", "تم تنفيذ هذه العملية مسبقاً.")
        raise
    except asyncpg.CheckViolationError:
        raise StoreError("insufficient_funds", "الرصيد غير كافٍ.")
    except asyncpg.PostgresError as e:
        if e.sqlstate == "HD001":
            raise StoreError("insufficient_funds", "الرصيد غير كافٍ.")
        if e.sqlstate == "HD002":
            raise StoreError("not_found", "المستخدم غير موجود.")
        raise
    return dict(r)


async def admin_adjust(core: Core, actor: str, user_id: int, amount: Any, reason: str,
                       idempotency_key: str | None = None, ip: str | None = None) -> dict:
    amt = money(amount)
    if amt == 0:
        raise StoreError("bad_amount", "المبلغ لا يمكن أن يكون صفراً.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StoreError("reason_required", "يجب كتابة سبب واضح للعملية.")
    kind = "admin_credit" if amt > 0 else "admin_debit"
    key = idempotency_key or f"adj:{make_ref('A')}"
    async with core.pool.acquire() as conn, conn.transaction():
        if not await conn.fetchval("SELECT 1 FROM users WHERE id=$1", user_id):
            raise StoreError("not_found", "المستخدم غير موجود.")
        tx = await apply_tx(conn, user_id=user_id, amount=amt, kind=kind, idempotency_key=key,
                            actor=actor, reason=reason)
        await audit(conn, actor, f"wallet.{kind}", "user", user_id,
                    {"amount": amt, "reason": reason, "tx": tx["ref"], "balance_after": tx["balance_after"]}, ip)
    if core.messenger:
        sign = "+" if amt > 0 else ""
        await core.messenger.notify_user(
            user_id,
            f"💼 تم تعديل رصيدك من الإدارة: <b>{sign}{amt} USDT</b>\n"
            f"السبب: {_esc(reason)}\nالرصيد الحالي: <b>{tx['balance_after']} USDT</b>\nرقم العملية: <code>{tx['ref']}</code>")
    return tx


async def history(core: Core, user_id: int | None = None, limit: int = 20, offset: int = 0,
                  kind: str | None = None) -> list[dict]:
    q = "SELECT * FROM wallet_transactions WHERE 1=1"
    args: list[Any] = []
    if user_id is not None:
        args.append(user_id)
        q += f" AND user_id=${len(args)}"
    if kind:
        args.append(kind)
        q += f" AND kind=${len(args)}"
    args += [limit, offset]
    q += f" ORDER BY id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


async def reconcile(core: Core) -> list[dict]:
    """Users whose stored balance differs from the sum of their ledger (should be empty)."""
    return rows(await core.pool.fetch(
        "SELECT u.id, u.balance, COALESCE(s.total,0) AS ledger FROM users u "
        "LEFT JOIN (SELECT user_id, SUM(amount) total FROM wallet_transactions GROUP BY user_id) s "
        "ON s.user_id=u.id WHERE u.balance <> COALESCE(s.total,0)"))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
