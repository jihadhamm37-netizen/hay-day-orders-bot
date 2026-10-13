"""Settings, audit log and alerts."""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from ..core import Core, StoreError, money, rows

log = logging.getLogger(__name__)

# key -> (label, kind)
SETTINGS_SCHEMA: dict[str, tuple[str, str]] = {
    "binance_pay_id": ("معرّف Binance Pay", "text"),
    "payment_instructions": ("تعليمات الدفع", "longtext"),
    "welcome_text": ("رسالة الترحيب", "longtext"),
    "support_text": ("رسالة الدعم الفني", "longtext"),
    "support_username": ("معرّف حساب الدعم (بدون @)", "text"),
    "hide_out_of_stock": ("إخفاء الأنواع النافدة", "bool"),
    "low_stock_threshold": ("حد تنبيه انخفاض المخزون", "int"),
    "min_deposit": ("أقل مبلغ شحن (USDT)", "money"),
    "max_deposit": ("أعلى مبلغ شحن (USDT)", "money"),
    "require_txid": ("طلب رقم عملية Binance مع الإثبات", "bool"),
    "auto_verify_enabled": ("التحقق الآلي عبر Binance API", "bool"),
}

_CACHE_TTL = 10.0


async def get_settings(core: Core, fresh: bool = False) -> dict[str, str]:
    c = core._settings_cache
    if not fresh and c.get("_ts", 0) > time.monotonic() - _CACHE_TTL:
        return c["data"]
    data = {r["key"]: r["value"] for r in await core.pool.fetch("SELECT key, value FROM settings")}
    core._settings_cache = {"_ts": time.monotonic(), "data": data}
    return data


async def setting(core: Core, key: str, default: str = "") -> str:
    return (await get_settings(core)).get(key, default)


async def setting_bool(core: Core, key: str) -> bool:
    return (await setting(core, key, "false")).lower() == "true"


async def setting_money(core: Core, key: str, default: str) -> Decimal:
    try:
        return money(await setting(core, key, default))
    except StoreError:
        return money(default)


def _normalize(key: str, value: Any) -> str:
    if key not in SETTINGS_SCHEMA:
        raise StoreError("bad_setting", "إعداد غير معروف.")
    kind = SETTINGS_SCHEMA[key][1]
    if kind == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        v = str(value).strip().lower()
        if v in ("true", "1", "yes", "on", "نعم"):
            return "true"
        if v in ("false", "0", "no", "off", "لا"):
            return "false"
        raise StoreError("bad_setting", "القيمة يجب أن تكون نعم أو لا.")
    if kind == "int":
        try:
            n = int(str(value).strip())
        except ValueError:
            raise StoreError("bad_setting", "القيمة يجب أن تكون رقماً صحيحاً.")
        if n < 0:
            raise StoreError("bad_setting", "القيمة لا يمكن أن تكون سالبة.")
        return str(n)
    if kind == "money":
        m = money(value)
        if m <= 0:
            raise StoreError("bad_setting", "المبلغ يجب أن يكون أكبر من صفر.")
        return str(m)
    v = str(value).strip()
    if key == "binance_pay_id":
        if not v.isdigit() or not (4 <= len(v) <= 20):
            raise StoreError("bad_setting", "معرّف Binance Pay يجب أن يكون أرقاماً فقط.")
    if key == "support_username":
        v = v.lstrip("@")
    if len(v) > 3500:
        raise StoreError("bad_setting", "النص طويل جداً.")
    if not v and key != "support_username":
        raise StoreError("bad_setting", "القيمة لا يمكن أن تكون فارغة.")
    return v


async def update_settings(core: Core, actor: str, values: dict[str, Any], ip: str | None = None) -> dict:
    normalized = {k: _normalize(k, v) for k, v in values.items()}
    if "min_deposit" in normalized or "max_deposit" in normalized:
        cur = await get_settings(core, fresh=True)
        mn = Decimal(normalized.get("min_deposit", cur.get("min_deposit", "1")))
        mx = Decimal(normalized.get("max_deposit", cur.get("max_deposit", "5000")))
        if mn > mx:
            raise StoreError("bad_setting", "أقل مبلغ شحن أكبر من أعلى مبلغ.")
    async with core.pool.acquire() as conn, conn.transaction():
        old = {r["key"]: r["value"] for r in await conn.fetch(
            "SELECT key, value FROM settings WHERE key = ANY($1::text[])", list(normalized))}
        for k, v in normalized.items():
            await conn.execute(
                "INSERT INTO settings(key, value, updated_by) VALUES($1,$2,$3) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=EXCLUDED.updated_by",
                k, v, actor)
        changes = {k: {"old": old.get(k), "new": v} for k, v in normalized.items() if old.get(k) != v}
        if changes:
            await audit(conn, actor, "settings.update", "settings", None, changes, ip)
    core._settings_cache = {}
    return await get_settings(core, fresh=True)


# -------------------------------------------------------------------- audit
async def audit(conn, actor: str, action: str, entity: str | None = None, entity_id: Any = None,
                details: dict | None = None, ip: str | None = None) -> None:
    await conn.execute(
        "INSERT INTO audit_log(actor, action, entity, entity_id, details, ip) VALUES($1,$2,$3,$4,$5,$6)",
        actor, action, entity, None if entity_id is None else str(entity_id),
        _jsonable(details) if details else None, ip)


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


async def list_audit(core: Core, limit: int = 50, offset: int = 0, actor: str | None = None,
                     action: str | None = None) -> list[dict]:
    q = "SELECT * FROM audit_log WHERE 1=1"
    args: list[Any] = []
    if actor:
        args.append(f"%{actor}%")
        q += f" AND actor ILIKE ${len(args)}"
    if action:
        args.append(f"{action}%")
        q += f" AND action LIKE ${len(args)}"
    args += [limit, offset]
    q += f" ORDER BY id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


# ------------------------------------------------------------------- alerts
async def raise_alert(core: Core, level: str, kind: str, message: str, entity: str | None = None,
                      entity_id: Any = None, notify: bool = True, perm: str = "view") -> None:
    try:
        await core.pool.execute(
            "INSERT INTO alerts(level, kind, message, entity, entity_id) VALUES($1,$2,$3,$4,$5)",
            level, kind, message, entity, None if entity_id is None else str(entity_id))
    except Exception:  # alerts must never break the main flow
        log.exception("failed to store alert")
    if notify and core.messenger:
        icon = {"error": "🚨", "warning": "⚠️"}.get(level, "ℹ️")
        try:
            await core.messenger.notify_admins(f"{icon} {message}", perm=perm)
        except Exception:
            log.exception("failed to notify admins")


async def list_alerts(core: Core, unread_only: bool = False, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM alerts"
    if unread_only:
        q += " WHERE NOT is_read"
    q += " ORDER BY id DESC LIMIT $1"
    return rows(await core.pool.fetch(q, limit))


async def mark_alerts_read(core: Core, ids: list[int] | None = None) -> None:
    if ids:
        await core.pool.execute("UPDATE alerts SET is_read=TRUE WHERE id = ANY($1::bigint[])", ids)
    else:
        await core.pool.execute("UPDATE alerts SET is_read=TRUE WHERE NOT is_read")
