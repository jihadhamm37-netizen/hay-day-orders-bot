"""Customers and their conversation history (shared by the AI, the bot and the admin panel)."""
from __future__ import annotations

import re
from typing import Any

from ..core import Core, StoreError, row, rows
from .system import audit

ARABIC = re.compile(r"[؀-ۿ]")


def detect_lang(text: str) -> str | None:
    if not text or not text.strip():
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    return "ar" if ARABIC.search(text) else "en"


async def touch(core: Core, user_id: int, username: str | None, first_name: str | None, lang: str = "ar") -> dict:
    r = await core.pool.fetchrow(
        "INSERT INTO customers(id, username, first_name, lang) VALUES($1,$2,$3,$4) "
        "ON CONFLICT (id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name, last_seen_at=now() "
        "RETURNING *", user_id, username, first_name, lang)
    return dict(r)


async def get(core: Core, customer_id: int) -> dict | None:
    return row(await core.pool.fetchrow("SELECT * FROM customers WHERE id=$1", customer_id))


async def set_lang(core: Core, customer_id: int, lang: str) -> None:
    await core.pool.execute("UPDATE customers SET lang=$2 WHERE id=$1 AND lang<>$2", customer_id, lang)


async def log_message(core: Core, customer_id: int, role: str, content: str, author: str | None = None) -> None:
    await core.pool.execute(
        "INSERT INTO messages(customer_id, role, content, author) VALUES($1,$2,$3,$4)",
        customer_id, role, content[:8000], author)
    if role == "user":
        await core.pool.execute("UPDATE customers SET last_message_at=now() WHERE id=$1", customer_id)


async def history(core: Core, customer_id: int, limit: int = 30, before_id: int | None = None) -> list[dict]:
    q = "SELECT id, role, content, author, created_at FROM messages WHERE customer_id=$1"
    args: list[Any] = [customer_id]
    if before_id:
        args.append(before_id)
        q += f" AND id < ${len(args)}"
    args.append(limit)
    q += f" ORDER BY id DESC LIMIT ${len(args)}"
    return list(reversed(rows(await core.pool.fetch(q, *args))))


async def set_ai_paused(core: Core, actor: str, customer_id: int, paused: bool, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE customers SET ai_paused=$2 WHERE id=$1", customer_id, paused)
        if r.endswith(" 0"):
            raise StoreError("not_found", "العميل غير موجود.")
        await audit(conn, actor, "chat.takeover" if paused else "chat.release", "customer", customer_id, None, ip)


async def set_banned(core: Core, actor: str, customer_id: int, banned: bool, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE customers SET is_banned=$2 WHERE id=$1", customer_id, banned)
        if r.endswith(" 0"):
            raise StoreError("not_found", "العميل غير موجود.")
        await audit(conn, actor, "customer.ban" if banned else "customer.unban", "customer", customer_id, None, ip)


async def set_notes(core: Core, actor: str, customer_id: int, notes: str, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE customers SET notes=$2 WHERE id=$1", customer_id, (notes or "").strip()[:2000] or None)
        await audit(conn, actor, "customer.notes", "customer", customer_id, None, ip)


async def search(core: Core, query: str = "", *, waiting: bool = False, limit: int = 50, offset: int = 0) -> list[dict]:
    q = ("SELECT c.*, (SELECT count(*) FROM orders o WHERE o.customer_id=c.id AND o.status='delivered') AS delivered_orders, "
         "(SELECT coalesce(sum(total),0) FROM orders o WHERE o.customer_id=c.id AND o.status='delivered') AS spent, "
         "(SELECT content FROM messages m WHERE m.customer_id=c.id ORDER BY id DESC LIMIT 1) AS last_message, "
         "(SELECT role FROM messages m WHERE m.customer_id=c.id ORDER BY id DESC LIMIT 1) AS last_role "
         "FROM customers c WHERE 1=1")
    args: list[Any] = []
    s = (query or "").strip().lstrip("@")
    if s:
        if s.isdigit():
            args.append(int(s))
            q += f" AND c.id=${len(args)}"
        else:
            args.append(f"%{s}%")
            q += f" AND (c.username ILIKE ${len(args)} OR c.first_name ILIKE ${len(args)})"
    if waiting:
        q += " AND c.ai_paused"
    args += [limit, offset]
    q += f" ORDER BY c.last_message_at DESC NULLS LAST, c.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))
