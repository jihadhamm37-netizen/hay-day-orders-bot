"""Farm types, farm accounts (inventory) and CSV/bulk import."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from typing import Any

import asyncpg

from ..core import Core, StoreError, money, row, rows
from .system import audit, raise_alert, setting

MAX_FIELD = 200


def _esc(v: str) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

_TYPE_STATS = """
SELECT t.*,
  COUNT(a.id) FILTER (WHERE a.status='available' AND t.is_active)  AS available,
  COUNT(a.id) FILTER (WHERE a.status='available')                  AS available_raw,
  COUNT(a.id) FILTER (WHERE a.status='reserved')                   AS reserved,
  COUNT(a.id) FILTER (WHERE a.status='sold')                       AS sold,
  COUNT(a.id) FILTER (WHERE a.status='disabled')                   AS disabled,
  COUNT(a.id)                                                       AS total,
  MIN(COALESCE(a.custom_price, t.price)) FILTER (WHERE a.status='available') AS min_price,
  MAX(COALESCE(a.custom_price, t.price)) FILTER (WHERE a.status='available') AS max_price
FROM farm_types t LEFT JOIN farm_accounts a ON a.type_id = t.id
"""


# --------------------------------------------------------------- filtering
_FILTER_RE = re.compile(r"(lvl|level|barn|silo|price|مستوى|مخزن|صومعة|سعر)\s*(>=|<=|=|>|<|:)?\s*([\d.]+)", re.I)
_ALIASES = {"level": "lvl", "مستوى": "lvl", "مخزن": "barn", "صومعة": "silo", "سعر": "price"}


def parse_filter(text: str) -> dict[str, tuple[str, Decimal]]:
    """'lvl>=70 barn 4000 price<=12' -> {'lvl': ('>=',70), 'barn': ('=',4000), 'price': ('<=',12)}"""
    out: dict[str, tuple[str, Decimal]] = {}
    for field_, op, val in _FILTER_RE.findall(text or ""):
        f = _ALIASES.get(field_.lower(), field_.lower())
        op = {"": "=", ":": "="}.get(op, op)
        out[f] = (op, Decimal(val))
    return out


async def list_types(core: Core, *, include_inactive: bool = True, filters: dict | None = None,
                     for_customers: bool = False) -> list[dict]:
    q = _TYPE_STATS + " WHERE NOT t.is_deleted"
    args: list[Any] = []
    if not include_inactive or for_customers:
        q += " AND t.is_active"
    for f, (op, val) in (filters or {}).items():
        if f not in ("lvl", "barn", "silo", "price") or op not in ("=", ">", "<", ">=", "<="):
            continue
        args.append(val)
        q += f" AND t.{f} {op} ${len(args)}"
    q += " GROUP BY t.id ORDER BY t.sort_order, t.lvl, t.price, t.id"
    result = rows(await core.pool.fetch(q, *args))
    if for_customers and (await setting(core, "hide_out_of_stock", "false")) == "true":
        result = [t for t in result if t["available"] > 0]
    return result


async def get_type(core: Core, type_id: int) -> dict | None:
    return row(await core.pool.fetchrow(_TYPE_STATS + " WHERE t.id=$1 GROUP BY t.id", type_id))


def _type_fields(data: dict, partial: bool) -> dict:
    out: dict[str, Any] = {}
    for f in ("lvl", "barn", "silo"):
        if f in data and data[f] is not None and data[f] != "":
            try:
                v = int(str(data[f]).strip())
            except ValueError:
                raise StoreError("bad_input", f"قيمة {f.upper()} يجب أن تكون رقماً صحيحاً.")
            if v < (1 if f == "lvl" else 0) or v > 10_000_000:
                raise StoreError("bad_input", f"قيمة {f.upper()} غير منطقية.")
            out[f] = v
        elif not partial:
            raise StoreError("bad_input", f"حقل {f.upper()} مطلوب.")
    if "price" in data and data["price"] not in (None, ""):
        p = money(data["price"])
        if p <= 0:
            raise StoreError("bad_amount", "السعر يجب أن يكون أكبر من صفر.")
        out["price"] = p
    elif not partial:
        raise StoreError("bad_input", "السعر مطلوب.")
    for f in ("name", "description"):
        if f in data and data[f] is not None:
            v = str(data[f]).strip()[:120 if f == "name" else 1000]
            out[f] = v or None
    if "sort_order" in data and data["sort_order"] not in (None, ""):
        out["sort_order"] = int(data["sort_order"])
    if "is_active" in data and data["is_active"] is not None:
        out["is_active"] = bool(data["is_active"])
    return out


async def create_type(core: Core, actor: str, data: dict, ip: str | None = None) -> dict:
    f = _type_fields(data, partial=False)
    name = f.get("name") or f"LVL {f['lvl']}"
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.fetchrow(
            "INSERT INTO farm_types(name, lvl, barn, silo, price, description, sort_order, is_active) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
            name, f["lvl"], f["barn"], f["silo"], f["price"], f.get("description"),
            f.get("sort_order", 0), f.get("is_active", True))
        await audit(conn, actor, "type.create", "farm_type", r["id"], dict(r), ip)
    return dict(r)


async def update_type(core: Core, actor: str, type_id: int, data: dict, ip: str | None = None) -> dict:
    f = _type_fields(data, partial=True)
    if "name" in f and not f["name"]:
        f.pop("name")
    if not f:
        raise StoreError("bad_input", "لا توجد تعديلات.")
    async with core.pool.acquire() as conn, conn.transaction():
        old = await conn.fetchrow("SELECT * FROM farm_types WHERE id=$1 FOR UPDATE", type_id)
        if not old or old["is_deleted"]:
            raise StoreError("not_found", "النوع غير موجود.")
        sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(f))
        r = await conn.fetchrow(f"UPDATE farm_types SET {sets}, updated_at=now() WHERE id=$1 RETURNING *",
                                type_id, *f.values())
        changes = {k: {"old": old[k], "new": v} for k, v in f.items() if old[k] != v}
        await audit(conn, actor, "type.update", "farm_type", type_id, changes, ip)
    return dict(r)


async def delete_type(core: Core, actor: str, type_id: int, ip: str | None = None) -> dict:
    """Delete a farm type.

    Never used → erased completely. Has sales history → its unsold accounts are erased, the type is hidden
    everywhere (archived) and sold accounts/orders stay in the records. Refused while an account is reserved
    (a purchase is being delivered).
    """
    async with core.pool.acquire() as conn, conn.transaction():
        t = await conn.fetchrow("SELECT * FROM farm_types WHERE id=$1 AND NOT is_deleted FOR UPDATE", type_id)
        if not t:
            raise StoreError("not_found", "النوع غير موجود.")
        if await conn.fetchval("SELECT 1 FROM farm_accounts WHERE type_id=$1 AND status='reserved' LIMIT 1", type_id):
            raise StoreError("busy", "يوجد حساب محجوز قيد التسليم في هذا النوع. حاول بعد قليل أو راجع الطلبات.")
        removed = await conn.fetchval(
            "WITH d AS (DELETE FROM farm_accounts a WHERE a.type_id=$1 AND a.status IN ('available','disabled') "
            "AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.account_id=a.id) RETURNING 1) SELECT count(*) FROM d",
            type_id)
        history = await conn.fetchval("SELECT 1 FROM orders WHERE type_id=$1 LIMIT 1", type_id) or \
            await conn.fetchval("SELECT 1 FROM farm_accounts WHERE type_id=$1 LIMIT 1", type_id)
        if history:
            await conn.execute("UPDATE farm_types SET is_deleted=TRUE, is_active=FALSE, deleted_at=now(), "
                               "updated_at=now() WHERE id=$1", type_id)
            # unconfirmed orders for this type can no longer be completed
            await conn.execute("UPDATE orders SET status='cancelled', failure_reason='تم حذف النوع', updated_at=now() "
                               "WHERE type_id=$1 AND status='pending'", type_id)
        else:
            await conn.execute("DELETE FROM farm_types WHERE id=$1", type_id)
        await audit(conn, actor, "type.delete", "farm_type", type_id,
                    {"name": t["name"], "archived": bool(history), "accounts_removed": removed}, ip)
    return {"archived": bool(history), "accounts_removed": removed}


async def price_tiers(core: Core, type_id: int) -> list[dict]:
    """Available stock grouped by effective price (type price or per-account custom price)."""
    return rows(await core.pool.fetch(
        "SELECT COALESCE(a.custom_price, t.price) AS price, COUNT(*) AS available "
        "FROM farm_accounts a JOIN farm_types t ON t.id=a.type_id "
        "WHERE a.type_id=$1 AND a.status='available' AND t.is_active "
        "GROUP BY 1 ORDER BY 1", type_id))


# ----------------------------------------------------------------- accounts
def parse_lines(text: str) -> tuple[list[dict], list[str]]:
    """Bulk text: one account per line → 'login:password', 'login password' or 'login,password[,price]'."""
    result, errors = [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = None
        for sep in (",", ";", "\t", ":", "|"):
            if sep in line:
                parts = [p.strip() for p in line.split(sep)]
                break
        if parts is None:
            parts = line.split()
        if len(parts) < 2:
            errors.append(f"سطر {n}: يجب أن يحتوي على ID وكلمة مرور")
            continue
        item = {"line": n, "login": parts[0], "password": parts[1]}
        if len(parts) >= 3 and parts[2]:
            item["price"] = parts[2]
        if len(parts) >= 4 and parts[3]:
            item["note"] = parts[3]
        result.append(item)
    return result, errors


def parse_csv(data: bytes) -> tuple[list[dict], list[str]]:
    """CSV with columns id/login, password[, price][, note]; header row optional."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1256")
        except UnicodeDecodeError:
            return [], ["تعذر قراءة الملف — احفظه بترميز UTF-8."]
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max(",;\t|", key=first.count) if first else ","
    if first and first.count(delim) == 0:
        delim = ":" if ":" in first else ","
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not reader:
        return [], ["الملف فارغ."]
    header = [h.strip().lower() for h in reader[0]]
    login_names = {"id", "login", "login_id", "username", "user", "email", "account", "المعرف", "معرف"}
    pass_names = {"password", "pass", "pwd", "كلمة المرور", "كلمة_المرور"}
    cols = {"login": 0, "password": 1, "price": 2, "note": 3}
    start = 0
    if any(h in login_names for h in header) and any(h in pass_names for h in header):
        start = 1
        cols = {"login": next(i for i, h in enumerate(header) if h in login_names),
                "password": next(i for i, h in enumerate(header) if h in pass_names)}
        for i, h in enumerate(header):
            if h in ("price", "السعر", "سعر"):
                cols["price"] = i
            if h in ("note", "notes", "ملاحظة", "ملاحظات"):
                cols["note"] = i
    result, errors = [], []
    for n, rec in enumerate(reader[start:], start + 1):
        if not any(c.strip() for c in rec):
            continue

        def col(name: str) -> str:
            i = cols.get(name)
            return rec[i].strip() if i is not None and i < len(rec) else ""

        login, password = col("login"), col("password")
        if not login or not password:
            errors.append(f"سطر {n}: ID أو كلمة المرور فارغ")
            continue
        item = {"line": n, "login": login, "password": password}
        if col("price"):
            item["price"] = col("price")
        if col("note"):
            item["note"] = col("note")
        result.append(item)
    return result, errors


async def validate_accounts(core: Core, items: list[dict]) -> dict:
    """Check rows before saving: format, duplicates inside the batch and in the database."""
    valid, errors, dup_file, dup_db = [], [], [], []
    seen: dict[str, int] = {}
    for it in items:
        login, password = str(it.get("login", "")).strip(), str(it.get("password", "")).strip()
        ln = it.get("line", "?")
        if not login or not password:
            errors.append(f"سطر {ln}: ID أو كلمة المرور فارغ")
            continue
        if len(login) > MAX_FIELD or len(password) > MAX_FIELD:
            errors.append(f"سطر {ln}: القيمة أطول من المسموح")
            continue
        if any(c in login for c in "\r\n") or any(c in password for c in "\r\n"):
            errors.append(f"سطر {ln}: يحتوي على أسطر جديدة")
            continue
        price = None
        if it.get("price") not in (None, ""):
            try:
                price = money(it["price"])
                if price <= 0:
                    raise StoreError("bad_amount", "")
            except StoreError:
                errors.append(f"سطر {ln}: السعر غير صالح")
                continue
        h = core.vault.login_hash(login)
        if h in seen:
            dup_file.append(f"سطر {ln}: مكرر مع السطر {seen[h]} ({core.vault.hint(login)})")
            continue
        seen[h] = ln
        valid.append({"line": ln, "login": login, "password": password, "price": price,
                      "note": (str(it.get("note") or "").strip()[:300] or None), "hash": h})
    if valid:
        existing = {r["login_hash"] for r in await core.pool.fetch(
            "SELECT login_hash FROM farm_accounts WHERE login_hash = ANY($1::text[])", [v["hash"] for v in valid])}
        if existing:
            dup_db = [f"سطر {v['line']}: موجود مسبقاً في المخزون ({core.vault.hint(v['login'])})"
                      for v in valid if v["hash"] in existing]
            valid = [v for v in valid if v["hash"] not in existing]
    return {"valid": valid, "errors": errors, "duplicates_in_file": dup_file, "duplicates_in_db": dup_db}


async def add_accounts(core: Core, actor: str, type_id: int, items: list[dict], ip: str | None = None) -> dict:
    """Validate then insert. Race-safe: ON CONFLICT on login_hash skips anything added meanwhile."""
    t = await core.pool.fetchrow("SELECT id FROM farm_types WHERE id=$1 AND NOT is_deleted", type_id)
    if not t:
        raise StoreError("not_found", "النوع غير موجود.")
    report = await validate_accounts(core, items)
    inserted = 0
    raced: list[str] = []
    async with core.pool.acquire() as conn, conn.transaction():
        for v in report["valid"]:
            new_id = await conn.fetchval(
                "INSERT INTO farm_accounts(type_id, login_enc, password_enc, login_hash, login_hint, custom_price, note) "
                "VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (login_hash) DO NOTHING RETURNING id",
                type_id, core.vault.encrypt(v["login"]), core.vault.encrypt(v["password"]), v["hash"],
                core.vault.hint(v["login"]), v["price"], v["note"])
            if new_id:
                inserted += 1
            else:
                raced.append(f"سطر {v['line']}: أضيف بالتزامن من مكان آخر")
        if inserted:
            await audit(conn, actor, "accounts.add", "farm_type", type_id,
                        {"inserted": inserted, "skipped": len(items) - inserted}, ip)
    report["duplicates_in_db"] += raced
    report["inserted"] = inserted
    report.pop("valid")
    return report


async def list_accounts(core: Core, type_id: int | None = None, status: str | None = None,
                        limit: int = 50, offset: int = 0, search: str | None = None) -> list[dict]:
    q = ("SELECT a.id, a.type_id, a.login_hint, a.custom_price, a.status, a.note, a.created_at, a.sold_at, "
         "(a.photo_file_id IS NOT NULL) AS has_photo, "
         "t.name AS type_name, t.price AS type_price, COALESCE(a.custom_price, t.price) AS effective_price, "
         "(SELECT o.ref FROM orders o WHERE o.account_id=a.id AND o.status<>'cancelled' LIMIT 1) AS order_ref "
         "FROM farm_accounts a JOIN farm_types t ON t.id=a.type_id WHERE 1=1")
    args: list[Any] = []
    if type_id:
        args.append(type_id)
        q += f" AND a.type_id=${len(args)}"
    if status:
        args.append(status)
        q += f" AND a.status=${len(args)}"
    if search:
        s = search.strip()
        if s.isdigit():
            args.append(int(s))
            q += f" AND a.id=${len(args)}"
        else:  # exact login lookup through the keyed hash
            args.append(core.vault.login_hash(s))
            q += f" AND a.login_hash=${len(args)}"
    args += [limit, offset]
    q += f" ORDER BY a.id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


async def update_account(core: Core, actor: str, account_id: int, data: dict, ip: str | None = None) -> dict:
    async with core.pool.acquire() as conn, conn.transaction():
        a = await conn.fetchrow("SELECT * FROM farm_accounts WHERE id=$1 FOR UPDATE", account_id)
        if not a:
            raise StoreError("not_found", "الحساب غير موجود.")
        sets: dict[str, Any] = {}
        details: dict[str, Any] = {}
        if "status" in data and data["status"]:
            new = data["status"]
            if new not in ("available", "disabled"):
                raise StoreError("bad_input", "الحالة المسموحة: متوفر أو موقوف.")
            if a["status"] not in ("available", "disabled"):
                raise StoreError("locked", "لا يمكن تغيير حالة حساب محجوز أو مباع.")
            sets["status"] = new
        if "custom_price" in data:
            cp = data["custom_price"]
            if cp in (None, "", "null"):
                sets["custom_price"] = None
            else:
                p = money(cp)
                if p <= 0:
                    raise StoreError("bad_amount", "السعر يجب أن يكون أكبر من صفر.")
                sets["custom_price"] = p
            if a["status"] in ("sold", "reserved"):
                raise StoreError("locked", "لا يمكن تعديل سعر حساب محجوز أو مباع.")
        if "note" in data:
            sets["note"] = (str(data["note"] or "").strip()[:300]) or None
        if data.get("login") or data.get("password"):
            if a["status"] not in ("available", "disabled"):
                raise StoreError("locked", "لا يمكن تعديل بيانات دخول حساب محجوز أو مباع.")
            if data.get("login"):
                login = str(data["login"]).strip()
                if not login or len(login) > MAX_FIELD:
                    raise StoreError("bad_input", "ID غير صالح.")
                sets["login_enc"] = core.vault.encrypt(login)
                sets["login_hash"] = core.vault.login_hash(login)
                sets["login_hint"] = core.vault.hint(login)
            if data.get("password"):
                pw = str(data["password"]).strip()
                if not pw or len(pw) > MAX_FIELD:
                    raise StoreError("bad_input", "كلمة المرور غير صالحة.")
                sets["password_enc"] = core.vault.encrypt(pw)
            details["credentials_changed"] = True
        if "type_id" in data and data["type_id"]:
            if a["status"] not in ("available", "disabled"):
                raise StoreError("locked", "لا يمكن نقل حساب محجوز أو مباع.")
            if not await conn.fetchval("SELECT 1 FROM farm_types WHERE id=$1", int(data["type_id"])):
                raise StoreError("not_found", "النوع غير موجود.")
            sets["type_id"] = int(data["type_id"])
        if not sets:
            raise StoreError("bad_input", "لا توجد تعديلات.")
        cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(sets))
        try:
            r = await conn.fetchrow(f"UPDATE farm_accounts SET {cols}, updated_at=now() WHERE id=$1 RETURNING *",
                                    account_id, *sets.values())
        except asyncpg.UniqueViolationError:
            raise StoreError("duplicate", "هذا الـ ID موجود مسبقاً في المخزون.")
        for k in ("status", "custom_price", "note", "type_id"):
            if k in sets:
                details[k] = {"old": a[k], "new": sets[k]}
        await audit(conn, actor, "account.update", "farm_account", account_id, details, ip)
    out = dict(r)
    out.pop("login_enc"); out.pop("password_enc"); out.pop("login_hash")
    return out


async def delete_account(core: Core, actor: str, account_id: int, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        a = await conn.fetchrow("SELECT * FROM farm_accounts WHERE id=$1 FOR UPDATE", account_id)
        if not a:
            raise StoreError("not_found", "الحساب غير موجود.")
        if a["status"] in ("sold", "reserved") or await conn.fetchval(
                "SELECT 1 FROM orders WHERE account_id=$1 LIMIT 1", account_id):
            raise StoreError("locked", "لا يمكن حذف حساب مرتبط بطلب — يحتفظ به في السجل.")
        await conn.execute("DELETE FROM farm_accounts WHERE id=$1", account_id)
        await audit(conn, actor, "account.delete", "farm_account", account_id,
                    {"type_id": a["type_id"], "hint": a["login_hint"]}, ip)


async def check_stock_alert(core: Core, type_id: int) -> None:
    t = await get_type(core, type_id)
    if not t:
        return
    try:
        threshold = int(await setting(core, "low_stock_threshold", "3"))
    except ValueError:
        threshold = 3
    if t["available_raw"] == 0:
        await raise_alert(core, "warning", "out_of_stock",
                          f"نفد مخزون النوع «{_esc(t['name'])}» (LVL {t['lvl']}).", "farm_type", type_id, perm="catalog")
    elif t["available_raw"] == threshold:
        await raise_alert(core, "info", "low_stock",
                          f"مخزون «{_esc(t['name'])}» منخفض: بقي {threshold} حساب.", "farm_type", type_id, perm="catalog")


async def set_type_photo(core: Core, actor: str, type_id: int, file_id: str | None, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE farm_types SET photo_file_id=$2, updated_at=now() WHERE id=$1", type_id, file_id)
        if r.endswith(" 0"):
            raise StoreError("not_found", "النوع غير موجود.")
        await audit(conn, actor, "type.photo", "farm_type", type_id, {"removed": file_id is None}, ip)


async def set_account_photo(core: Core, actor: str, account_id: int, file_id: str | None,
                            ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE farm_accounts SET photo_file_id=$2, updated_at=now() WHERE id=$1",
                               account_id, file_id)
        if r.endswith(" 0"):
            raise StoreError("not_found", "الحساب غير موجود.")
        await audit(conn, actor, "account.photo", "farm_account", account_id, {"removed": file_id is None}, ip)
