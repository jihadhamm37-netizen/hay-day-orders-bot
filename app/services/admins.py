"""Administrators, roles/permissions and web login."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from ..core import Core, StoreError, row, rows
from ..security import hash_code, hash_password, verify_password
from .system import audit

ROLES = {
    "owner": "المالك",
    "admin": "مشرف",
    "support": "دعم فني",
}
# permission → roles that have it
PERMISSIONS = {
    "view": {"owner", "admin", "support"},
    "deposits": {"owner", "admin", "support"},
    "orders": {"owner", "admin", "support"},
    "catalog": {"owner", "admin"},
    "users": {"owner", "admin"},
    "wallet": {"owner", "admin"},
    "settings": {"owner", "admin"},
    "admins": {"owner"},
    "backup": {"owner"},
}
LOCK_AFTER = 5
LOCK_MINUTES = 15
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


def has_perm(role: str | None, perm: str) -> bool:
    return bool(role) and role in PERMISSIONS.get(perm, set())


async def telegram_role(core: Core, telegram_id: int) -> str | None:
    """Role of a Telegram user for the in-bot admin menu (checked by numeric ID, never username)."""
    if telegram_id in core.config.owner_ids:
        return "owner"
    return await core.pool.fetchval("SELECT role FROM admins WHERE telegram_id=$1 AND is_active", telegram_id)


async def admin_recipients(core: Core, perm: str) -> list[int]:
    ids = set(core.config.owner_ids)
    for r in await core.pool.fetch("SELECT telegram_id, role FROM admins WHERE is_active AND telegram_id IS NOT NULL"):
        if has_perm(r["role"], perm):
            ids.add(r["telegram_id"])
    return sorted(ids)


def _check_password_strength(pw: str) -> None:
    if len(pw) < 10 or pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        raise StoreError("weak_password",
                         "كلمة المرور ضعيفة: 10 أحرف على الأقل وتحتوي حروفاً كبيرة وصغيرة ورقماً.")


async def create_admin(core: Core, actor: str, username: str, password: str, role: str = "admin",
                       telegram_id: int | None = None, ip: str | None = None) -> dict:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise StoreError("bad_input", "اسم المستخدم: 3-32 حرفاً إنجليزياً أو أرقام أو _ . -")
    if role not in ROLES:
        raise StoreError("bad_input", "الدور غير صالح.")
    _check_password_strength(password)
    try:
        async with core.pool.acquire() as conn, conn.transaction():
            r = await conn.fetchrow(
                "INSERT INTO admins(username, password_hash, telegram_id, role) VALUES($1,$2,$3,$4) "
                "RETURNING id, username, telegram_id, role, is_active, created_at",
                username, hash_password(password), telegram_id, role)
            await audit(conn, actor, "admin.create", "admin", r["id"],
                        {"username": username, "role": role, "telegram_id": telegram_id}, ip)
    except asyncpg.UniqueViolationError:
        raise StoreError("duplicate", "اسم المستخدم أو معرّف تيليجرام مستخدم مسبقاً.")
    return dict(r)


async def update_admin(core: Core, actor: str, admin_id: int, data: dict, ip: str | None = None) -> dict:
    sets: dict[str, Any] = {}
    if "role" in data and data["role"]:
        if data["role"] not in ROLES:
            raise StoreError("bad_input", "الدور غير صالح.")
        sets["role"] = data["role"]
    if "is_active" in data and data["is_active"] is not None:
        sets["is_active"] = bool(data["is_active"])
    if "telegram_id" in data:
        tid = data["telegram_id"]
        sets["telegram_id"] = int(tid) if tid not in (None, "") else None
    if data.get("password"):
        _check_password_strength(data["password"])
        sets["password_hash"] = hash_password(data["password"])
        sets["failed_logins"] = 0
        sets["locked_until"] = None
    if not sets:
        raise StoreError("bad_input", "لا توجد تعديلات.")
    async with core.pool.acquire() as conn, conn.transaction():
        cur = await conn.fetchrow("SELECT * FROM admins WHERE id=$1 FOR UPDATE", admin_id)
        if not cur:
            raise StoreError("not_found", "المشرف غير موجود.")
        if cur["role"] == "owner" and (sets.get("role", "owner") != "owner" or sets.get("is_active") is False):
            owners = await conn.fetchval("SELECT count(*) FROM admins WHERE role='owner' AND is_active")
            if owners <= 1:
                raise StoreError("last_owner", "لا يمكن إزالة آخر مالك نشط.")
        cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(sets))
        # any security-relevant change logs the admin out everywhere
        try:
            r = await conn.fetchrow(
                f"UPDATE admins SET {cols}, token_version=token_version+1 WHERE id=$1 "
                "RETURNING id, username, telegram_id, role, is_active, created_at, last_login_at",
                admin_id, *sets.values())
        except asyncpg.UniqueViolationError:
            raise StoreError("duplicate", "معرّف تيليجرام مستخدم لمشرف آخر.")
        await audit(conn, actor, "admin.update", "admin", admin_id,
                    {k: ("***" if k == "password_hash" else v) for k, v in sets.items()}, ip)
    return dict(r)


async def list_admins(core: Core) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT id, username, telegram_id, role, is_active, created_at, last_login_at, locked_until "
        "FROM admins ORDER BY id"))


async def get_admin(core: Core, admin_id: int) -> dict | None:
    return row(await core.pool.fetchrow("SELECT * FROM admins WHERE id=$1", admin_id))


async def check_login(core: Core, username: str, password: str, ip: str | None) -> dict:
    """Step 1 of web login. Locks the account after repeated failures."""
    username = (username or "").strip().lower()
    a = await core.pool.fetchrow("SELECT * FROM admins WHERE username=$1", username)
    now = datetime.now(timezone.utc)
    if a and a["locked_until"] and a["locked_until"] > now:
        verify_password(password, None)
        raise StoreError("locked", "تم قفل الحساب مؤقتاً بسبب محاولات فاشلة. حاول لاحقاً.")
    if not a or not a["is_active"] or not verify_password(password or "", a["password_hash"]):
        if a:
            fails = a["failed_logins"] + 1
            lock = now + timedelta(minutes=LOCK_MINUTES) if fails >= LOCK_AFTER else None
            await core.pool.execute("UPDATE admins SET failed_logins=$2, locked_until=$3 WHERE id=$1",
                                    a["id"], 0 if lock else fails, lock)
            async with core.pool.acquire() as conn:
                await audit(conn, f"web:{username}", "auth.failed", "admin", a["id"], {"locked": bool(lock)}, ip)
        raise StoreError("bad_login", "اسم المستخدم أو كلمة المرور غير صحيحة.")
    return dict(a)


async def issue_code(core: Core, admin: dict) -> bool:
    """Send a one-time 6-digit login code to the admin's Telegram (second factor)."""
    if not admin.get("telegram_id") or not core.messenger:
        return False
    recent = await core.pool.fetchval(
        "SELECT count(*) FROM login_codes WHERE admin_id=$1 AND created_at > now() - interval '10 minutes'",
        admin["id"])
    if recent >= 5:
        raise StoreError("too_many", "طلبت رموزاً كثيرة، انتظر قليلاً.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    await core.pool.execute(
        "INSERT INTO login_codes(admin_id, code_hash, expires_at) VALUES($1,$2, now() + interval '5 minutes')",
        admin["id"], hash_code(code, core.config.jwt_secret))
    return await core.messenger.send_admin_code(admin["telegram_id"], code)


async def verify_code(core: Core, admin_id: int, code: str) -> bool:
    async with core.pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow(
            "SELECT * FROM login_codes WHERE admin_id=$1 AND NOT used AND expires_at > now() "
            "ORDER BY id DESC LIMIT 1 FOR UPDATE", admin_id)
        if not c or c["attempts"] >= 5:
            return False
        ok = secrets.compare_digest(c["code_hash"], hash_code((code or "").strip(), core.config.jwt_secret))
        await conn.execute("UPDATE login_codes SET attempts=attempts+1, used=$2 WHERE id=$1", c["id"], ok)
        return ok


async def login_success(core: Core, admin_id: int, ip: str | None) -> None:
    await core.pool.execute("UPDATE admins SET failed_logins=0, locked_until=NULL, last_login_at=now() WHERE id=$1",
                            admin_id)
    async with core.pool.acquire() as conn:
        await audit(conn, f"web:{await conn.fetchval('SELECT username FROM admins WHERE id=$1', admin_id)}",
                    "auth.login", "admin", admin_id, None, ip)


async def claim_owner(core: Core, telegram_id: int, code: str) -> dict:
    """One-time: link the first web owner account to the Telegram user who knows SETUP_CODE."""
    expected = core.config.setup_code
    if not expected or len(expected) < 8 or not secrets.compare_digest((code or "").strip(), expected):
        raise StoreError("bad_code", "رمز غير صحيح.")
    async with core.pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(727002)")
        if await conn.fetchval("SELECT 1 FROM admins WHERE telegram_id IS NOT NULL LIMIT 1"):
            raise StoreError("claimed", "تم ربط حساب المالك مسبقاً.")
        a = await conn.fetchrow("SELECT * FROM admins WHERE role='owner' AND is_active ORDER BY id LIMIT 1")
        if not a:
            raise StoreError("no_owner", "لا يوجد حساب مالك للوحة بعد.")
        await conn.execute("UPDATE admins SET telegram_id=$2, token_version=token_version+1 WHERE id=$1",
                           a["id"], telegram_id)
        await audit(conn, f"tg:{telegram_id}", "admin.claim_owner", "admin", a["id"], {"telegram_id": telegram_id})
    return dict(a)
