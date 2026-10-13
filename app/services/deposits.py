"""USDT top-ups via Binance Pay: request → proof → review → credit exactly once."""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

import asyncpg

from ..core import Core, StoreError, fmt, money, row, rows
from ..security import make_ref
from . import binance
from .system import audit, raise_alert, setting, setting_bool, setting_money
from .wallet import apply_tx

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "awaiting_payment": "بانتظار الدفع",
    "under_review": "قيد المراجعة",
    "approved": "مقبول",
    "rejected": "مرفوض",
    "cancelled": "ملغي",
}
TXID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
OPEN_TTL_HOURS = 24


async def create(core: Core, user_id: int, amount: Any) -> dict:
    amt = money(amount)
    mn = await setting_money(core, "min_deposit", "1")
    mx = await setting_money(core, "max_deposit", "5000")
    if amt < mn or amt > mx:
        raise StoreError("bad_amount", f"المبلغ يجب أن يكون بين {fmt(mn)} و {fmt(mx)} USDT.")
    u = await core.pool.fetchrow("SELECT is_banned FROM users WHERE id=$1", user_id)
    if not u:
        raise StoreError("not_found", "المستخدم غير موجود.")
    if u["is_banned"]:
        raise StoreError("banned", "حسابك موقوف. تواصل مع الدعم.")
    pay_id = await setting(core, "binance_pay_id")
    async with core.pool.acquire() as conn, conn.transaction():
        # replace an older unpaid request instead of piling them up
        await conn.execute("UPDATE deposits SET status='cancelled', updated_at=now() "
                           "WHERE user_id=$1 AND status='awaiting_payment'", user_id)
        d = await conn.fetchrow(
            "INSERT INTO deposits(ref, user_id, amount, pay_id_shown) VALUES($1,$2,$3,$4) RETURNING *",
            make_ref("DEP"), user_id, amt, pay_id)
    return dict(d)


async def get(core: Core, deposit_id: int) -> dict | None:
    return row(await core.pool.fetchrow(
        "SELECT d.*, u.username, u.first_name FROM deposits d JOIN users u ON u.id=d.user_id WHERE d.id=$1",
        deposit_id))


async def open_for_user(core: Core, user_id: int) -> dict | None:
    return row(await core.pool.fetchrow(
        "SELECT * FROM deposits WHERE user_id=$1 AND status='awaiting_payment' ORDER BY id DESC LIMIT 1", user_id))


async def attach_photo(core: Core, user_id: int, deposit_id: int, file_id: str, file_unique_id: str) -> dict:
    try:
        d = await core.pool.fetchrow(
            "UPDATE deposits SET proof_file_id=$3, proof_file_unique_id=$4, updated_at=now() "
            "WHERE id=$1 AND user_id=$2 AND status='awaiting_payment' RETURNING *",
            deposit_id, user_id, file_id, file_unique_id)
    except asyncpg.UniqueViolationError:
        raise StoreError("proof_reused", "⛔️ هذا الإثبات مستخدم مسبقاً في طلب شحن آخر.")
    if not d:
        raise StoreError("bad_state", "لا يوجد طلب شحن مفتوح. ابدأ من «شحن الرصيد».")
    return dict(d)


async def attach_txid(core: Core, user_id: int, deposit_id: int, txid: str) -> dict:
    txid = (txid or "").strip()
    if not TXID_RE.match(txid):
        raise StoreError("bad_txid", "رقم العملية غير صالح. انسخ Order ID من تفاصيل التحويل في Binance.")
    try:
        d = await core.pool.fetchrow(
            "UPDATE deposits SET proof_txid=$3, updated_at=now() "
            "WHERE id=$1 AND user_id=$2 AND status='awaiting_payment' RETURNING *", deposit_id, user_id, txid)
    except asyncpg.UniqueViolationError:
        raise StoreError("proof_reused", "⛔️ رقم العملية هذا مستخدم مسبقاً في طلب شحن آخر.")
    if not d:
        raise StoreError("bad_state", "لا يوجد طلب شحن مفتوح.")
    return dict(d)


async def submit(core: Core, user_id: int, deposit_id: int) -> dict:
    """Move to under_review once the required proof is attached, notify admins, try auto-verify."""
    need_txid = await setting_bool(core, "require_txid")
    d = await core.pool.fetchrow(
        "UPDATE deposits SET status='under_review', updated_at=now() WHERE id=$1 AND user_id=$2 "
        "AND status='awaiting_payment' AND proof_file_id IS NOT NULL "
        "AND (proof_txid IS NOT NULL OR NOT $3) RETURNING *", deposit_id, user_id, need_txid)
    if not d:
        raise StoreError("bad_state", "أرسل إثبات الدفع أولاً.")
    d = await get(core, d["id"])
    if await setting_bool(core, "auto_verify_enabled") and d["proof_txid"] and binance.enabled(core):
        try:
            ok, info = await binance.verify_incoming(core, d["proof_txid"], d["amount"], d["created_at"])
        except Exception as e:  # never block the manual path
            log.warning("auto-verify error for %s: %s", d["ref"], e)
            ok, info = False, f"خطأ في الاتصال بـ Binance: {e}"
        if ok:
            await approve(core, "system:binance", d["id"], note="تحقق آلي عبر Binance API")
            return await get(core, d["id"])
        d["auto_verify_note"] = info
    if core.messenger:
        await core.messenger.notify_admins(admin_card(d), perm="deposits", photo=d["proof_file_id"],
                                           reply_markup=("deposit_review", d["id"]))
    return d


def admin_card(d: dict) -> str:
    uname = f"@{d['username']}" if d.get("username") else ""
    lines = [
        "💰 <b>طلب شحن جديد</b>",
        f"المرجع: <code>{d['ref']}</code>",
        f"المستخدم: {uname} <code>{d['user_id']}</code>",
        f"المبلغ: <b>{fmt(d['amount'])} USDT</b>",
        f"Order ID: <code>{d['proof_txid'] or '—'}</code>",
        "⚠️ تحقق من وصول المبلغ في Binance قبل الموافقة.",
    ]
    if d.get("auto_verify_note"):
        lines.append(f"🤖 التحقق الآلي: {d['auto_verify_note']}")
    return "\n".join(lines)


async def approve(core: Core, actor: str, deposit_id: int, credited: Any = None, note: str = "",
                  ip: str | None = None) -> dict:
    async with core.pool.acquire() as conn, conn.transaction():
        # status flip = single winner even if two admins click at the same time
        d = await conn.fetchrow(
            "UPDATE deposits SET status='approved', reviewed_by=$2, reviewed_at=now(), updated_at=now(), "
            "auto_verified=$3 WHERE id=$1 AND status='under_review' RETURNING *",
            deposit_id, actor, actor == "system:binance")
        if not d:
            cur = await conn.fetchval("SELECT status FROM deposits WHERE id=$1", deposit_id)
            if cur is None:
                raise StoreError("not_found", "طلب الشحن غير موجود.")
            raise StoreError("already", f"تمت مراجعة هذا الطلب مسبقاً ({STATUS_LABELS[cur]}).")
        amount = money(credited) if credited not in (None, "") else d["amount"]
        if amount <= 0:
            raise StoreError("bad_amount", "المبلغ يجب أن يكون أكبر من صفر.")
        await conn.execute("UPDATE deposits SET credited_amount=$2 WHERE id=$1", deposit_id, amount)
        tx = await apply_tx(conn, user_id=d["user_id"], amount=amount, kind="deposit",
                            idempotency_key=f"deposit:{deposit_id}", deposit_id=deposit_id, actor=actor,
                            reason=f"شحن عبر Binance Pay ({d['ref']})" + (f" — {note}" if note else ""))
        await audit(conn, actor, "deposit.approve", "deposit", deposit_id,
                    {"requested": d["amount"], "credited": amount, "tx": tx["ref"], "note": note}, ip)
    if core.messenger:
        await core.messenger.notify_user(
            d["user_id"], key="n_deposit_ok", ref=d["ref"], amount=fmt(amount),
            balance=fmt(tx["balance_after"]),
            extra=None if amount == d["amount"] else ("n_deposit_extra", {"requested": fmt(d["amount"])}))
    return await get(core, deposit_id)


async def reject(core: Core, actor: str, deposit_id: int, reason: str, ip: str | None = None) -> dict:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StoreError("reason_required", "يجب كتابة سبب الرفض.")
    async with core.pool.acquire() as conn, conn.transaction():
        d = await conn.fetchrow(
            "UPDATE deposits SET status='rejected', reject_reason=$3, reviewed_by=$2, reviewed_at=now(), "
            "updated_at=now() WHERE id=$1 AND status IN ('under_review','awaiting_payment') RETURNING *",
            deposit_id, actor, reason[:500])
        if not d:
            raise StoreError("already", "تمت مراجعة هذا الطلب مسبقاً.")
        await audit(conn, actor, "deposit.reject", "deposit", deposit_id, {"reason": reason}, ip)
    if core.messenger:
        await core.messenger.notify_user(d["user_id"], key="n_deposit_rejected", ref=d["ref"], reason=_esc(reason))
    return await get(core, deposit_id)


async def cancel(core: Core, user_id: int, deposit_id: int) -> None:
    r = await core.pool.execute("UPDATE deposits SET status='cancelled', updated_at=now() "
                                "WHERE id=$1 AND user_id=$2 AND status='awaiting_payment'", deposit_id, user_id)
    if r.endswith(" 0"):
        raise StoreError("bad_state", "لا يمكن إلغاء هذا الطلب.")


async def list_deposits(core: Core, *, status: str | None = None, user_id: int | None = None,
                        search: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    q = ("SELECT d.*, u.username, u.first_name FROM deposits d JOIN users u ON u.id=d.user_id WHERE 1=1")
    args: list[Any] = []
    if status:
        args.append(status)
        q += f" AND d.status=${len(args)}"
    if user_id is not None:
        args.append(user_id)
        q += f" AND d.user_id=${len(args)}"
    if search:
        s = search.strip()
        if s.isdigit() and len(s) < 15:
            args.append(int(s))
            q += f" AND d.user_id=${len(args)}"
        else:
            args.append(s.upper())
            q += f" AND (d.ref=${len(args)} OR upper(d.proof_txid)=${len(args)})"
    args += [limit, offset]
    q += f" ORDER BY d.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


async def maintenance(core: Core) -> int:
    r = await core.pool.execute(
        "UPDATE deposits SET status='cancelled', updated_at=now() WHERE status='awaiting_payment' "
        "AND updated_at < now() - make_interval(hours => $1)", OPEN_TTL_HOURS)
    return int(r.split()[-1])


def _esc(v: str) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
