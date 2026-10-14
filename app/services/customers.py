"""Customers (app users with an access code), their device binding and conversation history."""
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


async def log_message(core: Core, customer_id: int, role: str, content: str, author: str | None = None,
                      kind: str = "text", payload: dict | None = None) -> int:
    """kind: 'text' (shown in the app), 'internal' (context for the AI/staff only) or a card type."""
    mid = await core.pool.fetchval(
        "INSERT INTO messages(customer_id, role, content, author, kind, payload) VALUES($1,$2,$3,$4,$5,$6) RETURNING id",
        customer_id, role, content[:8000], author, kind, payload)
    if role == "user":
        await core.pool.execute("UPDATE customers SET last_message_at=now() WHERE id=$1", customer_id)
    return mid


async def history(core: Core, customer_id: int, limit: int = 30, before_id: int | None = None) -> list[dict]:
    q = "SELECT id, role, content, author, kind, payload, created_at FROM messages WHERE customer_id=$1"
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
            q += (f" AND (c.username ILIKE ${len(args)} OR c.first_name ILIKE ${len(args)} "
                  f"OR c.access_code ILIKE ${len(args)} OR c.notes ILIKE ${len(args)})")
    if waiting:
        q += " AND c.ai_paused"
    args += [limit, offset]
    q += f" ORDER BY c.last_message_at DESC NULLS LAST, c.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


# ------------------------------------------------------------ access codes
import secrets as _secrets

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I


def new_code() -> str:
    return "HD-" + "".join(_secrets.choice(CODE_ALPHABET) for _ in range(8))


def normalize_code(code: str) -> str:
    c = re.sub(r"[\s_]", "", (code or "").upper())
    if c.startswith("HD") and not c.startswith("HD-"):
        c = "HD-" + c[2:]
    return c


async def create_codes(core: Core, actor: str, count: int = 1, name: str | None = None, notes: str | None = None,
                       ip: str | None = None) -> list[dict]:
    if not (1 <= int(count) <= 200):
        raise StoreError("bad_input", "العدد بين 1 و 200.")
    out = []
    async with core.pool.acquire() as conn, conn.transaction():
        for i in range(int(count)):
            nm = (name or "").strip()[:60] or None
            if nm and int(count) > 1:
                nm = f"{nm} {i + 1}"
            for _ in range(5):
                code = new_code()
                r = await conn.fetchrow(
                    "INSERT INTO customers(first_name, access_code, notes, created_by) VALUES($1,$2,$3,$4) "
                    "ON CONFLICT (access_code) DO NOTHING RETURNING id, first_name, access_code, created_at",
                    nm, code, (notes or "").strip()[:500] or None, actor)
                if r:
                    out.append(dict(r))
                    break
        await audit(conn, actor, "code.create", "customer", None, {"count": len(out)}, ip)
    return out


async def login_with_code(core: Core, code: str, device_id: str, device_label: str | None) -> dict:
    code = normalize_code(code)
    device_id = (device_id or "").strip()[:100]
    if not re.fullmatch(r"HD-[A-Z0-9]{4,16}", code):
        raise StoreError("bad_code", "الكود غير صحيح.")
    if len(device_id) < 8:
        raise StoreError("bad_device", "تعذر التعرف على الجهاز.")
    async with core.pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow("SELECT * FROM customers WHERE access_code=$1 FOR UPDATE", code)
        if not c or not c["code_active"]:
            raise StoreError("bad_code", "الكود غير صحيح أو موقوف.")
        if c["is_banned"]:
            raise StoreError("banned", "هذا الحساب موقوف. تواصل مع الإدارة.")
        if c["device_id"] and c["device_id"] != device_id:
            raise StoreError("other_device", "هذا الكود مفعّل على جهاز آخر. لا يمكن استخدامه على أكثر من جهاز — تواصل مع الإدارة.")
        if not c["device_id"]:
            c = await conn.fetchrow(
                "UPDATE customers SET device_id=$2, device_label=$3, bound_at=now(), last_seen_at=now() WHERE id=$1 RETURNING *",
                c["id"], device_id, (device_label or "").strip()[:120] or None)
            await audit(conn, f"app:{c['id']}", "code.bind", "customer", c["id"], {"device": c["device_label"]})
    return dict(c)


async def reset_device(core: Core, actor: str, customer_id: int, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE customers SET device_id=NULL, device_label=NULL, bound_at=NULL, "
                               "session_ver=session_ver+1 WHERE id=$1", customer_id)
        if r.endswith(" 0"):
            raise StoreError("not_found", "العميل غير موجود.")
        await audit(conn, actor, "code.reset_device", "customer", customer_id, None, ip)


async def set_code_active(core: Core, actor: str, customer_id: int, active: bool, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE customers SET code_active=$2, session_ver=session_ver+(CASE WHEN $2 THEN 0 ELSE 1 END) "
                           "WHERE id=$1", customer_id, active)
        await audit(conn, actor, "code.enable" if active else "code.disable", "customer", customer_id, None, ip)


async def set_name(core: Core, actor: str, customer_id: int, name: str, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE customers SET first_name=$2 WHERE id=$1", customer_id, (name or "").strip()[:60] or None)
        await audit(conn, actor, "customer.rename", "customer", customer_id, None, ip)
