"""Farm inventory: one row per farm with its own encrypted Token ID + password."""
from __future__ import annotations

import csv
import hashlib
import io
from decimal import Decimal
from typing import Any

import asyncpg

from ..core import Core, StoreError, money, row, rows
from .system import audit, raise_alert, setting

MAX_FIELD = 300
CURRENCIES = {"USDT", "USD", "IQD", "EUR", "SAR", "AED", "JOD", "TRY"}
OFFER_FIELDS = ("name", "lvl", "barn", "silo", "tools", "price", "currency")

PUBLIC_COLS = ("id, name, lvl, barn, silo, tools, price, cost, currency, description, token_hint, status, "
               "created_at, updated_at, sold_at")


def _esc(v: Any) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ offers
def offer_code(o: dict) -> str:
    """Stable short code for a group of identical farms (what customers actually choose between)."""
    key = "|".join(str(Decimal(o[f]) if f == "price" else o[f]) for f in OFFER_FIELDS)
    return "F" + hashlib.sha1(key.encode()).hexdigest()[:7].upper()


async def search_offers(core: Core, *, min_level: int | None = None, max_level: int | None = None,
                        min_price: Any = None, max_price: Any = None, currency: str | None = None,
                        query: str | None = None, limit: int = 15) -> list[dict]:
    """Available stock grouped into offers. Only real DB data is returned."""
    q = ("SELECT name, lvl, barn, silo, tools, price, currency, max(description) AS description, count(*) AS available "
         "FROM farms WHERE status='available'")
    args: list[Any] = []
    for col, op, val in (("lvl", ">=", min_level), ("lvl", "<=", max_level),
                         ("price", ">=", min_price), ("price", "<=", max_price)):
        if val not in (None, ""):
            args.append(Decimal(str(val)))
            q += f" AND {col} {op} ${len(args)}"
    if currency:
        args.append(currency.upper())
        q += f" AND currency = ${len(args)}"
    if query:
        args.append(f"%{query}%")
        q += f" AND (name ILIKE ${len(args)} OR description ILIKE ${len(args)})"
    args.append(max(1, min(limit, 50)))
    q += f" GROUP BY name, lvl, barn, silo, tools, price, currency ORDER BY lvl, price LIMIT ${len(args)}"
    out = []
    for r in await core.pool.fetch(q, *args):
        d = dict(r)
        d["offer_code"] = offer_code(d)
        out.append(d)
    return out


async def find_offer(core: Core, code: str) -> dict | None:
    code = (code or "").strip().upper()
    for o in await search_offers(core, limit=50):
        if o["offer_code"] == code:
            return o
    # fall back to a full scan when there are many groups
    rs = await core.pool.fetch(
        "SELECT name, lvl, barn, silo, tools, price, currency, max(description) AS description, count(*) AS available "
        "FROM farms WHERE status='available' GROUP BY name, lvl, barn, silo, tools, price, currency")
    for r in rs:
        d = dict(r)
        if offer_code(d) == code:
            d["offer_code"] = code
            return d
    return None


async def stock_summary(core: Core) -> dict:
    r = await core.pool.fetchrow(
        "SELECT count(*) FILTER (WHERE status='available') AS available, count(*) FILTER (WHERE status='reserved') AS reserved, "
        "count(*) FILTER (WHERE status='sold') AS sold, count(*) FILTER (WHERE status='disabled') AS disabled, "
        "min(lvl) FILTER (WHERE status='available') AS min_lvl, max(lvl) FILTER (WHERE status='available') AS max_lvl, "
        "min(price) FILTER (WHERE status='available') AS min_price, max(price) FILTER (WHERE status='available') AS max_price "
        "FROM farms")
    return dict(r)


# -------------------------------------------------------------------- CRUD
def _fields(core: Core, data: dict, partial: bool) -> dict:
    out: dict[str, Any] = {}
    for f in ("lvl", "barn", "silo", "tools"):
        v = data.get(f)
        if v in (None, ""):
            if not partial and f == "lvl":
                raise StoreError("bad_input", "المستوى مطلوب.")
            if not partial:
                out[f] = 0
            continue
        try:
            n = int(str(v).replace(",", "").strip())
        except ValueError:
            raise StoreError("bad_input", f"قيمة {f} يجب أن تكون رقماً صحيحاً.")
        if n < (1 if f == "lvl" else 0) or n > 100_000_000:
            raise StoreError("bad_input", f"قيمة {f} غير منطقية.")
        out[f] = n
    if data.get("price") not in (None, ""):
        p = money(data["price"])
        if p <= 0:
            raise StoreError("bad_amount", "السعر يجب أن يكون أكبر من صفر.")
        out["price"] = p
    elif not partial:
        raise StoreError("bad_input", "السعر مطلوب.")
    if "cost" in data:
        out["cost"] = None if data["cost"] in (None, "") else money(data["cost"])
    if data.get("currency") not in (None, ""):
        c = str(data["currency"]).strip().upper()
        if not (2 <= len(c) <= 6 and c.isalpha()):
            raise StoreError("bad_input", "العملة غير صالحة.")
        out["currency"] = c
    elif not partial:
        out["currency"] = "USDT"
    if data.get("name") not in (None, ""):
        out["name"] = str(data["name"]).strip()[:80]
    elif not partial:
        out["name"] = f"Farm LVL {out['lvl']}"
    if "description" in data:
        out["description"] = (str(data["description"] or "").strip()[:1000]) or None
    for f in ("token_id", "password"):
        if data.get(f) not in (None, ""):
            v = str(data[f]).strip()
            if len(v) > MAX_FIELD or "\n" in v:
                raise StoreError("bad_input", f"{f} غير صالح.")
            out[f] = v
        elif not partial:
            raise StoreError("bad_input", "Token ID وكلمة المرور مطلوبان.")
    return out


def _enc(core: Core, f: dict) -> dict:
    out = {k: v for k, v in f.items() if k not in ("token_id", "password")}
    if "token_id" in f:
        out["token_enc"] = core.vault.encrypt(f["token_id"])
        out["token_hash"] = core.vault.login_hash(f["token_id"])
        out["token_hint"] = core.vault.hint(f["token_id"])
    if "password" in f:
        out["password_enc"] = core.vault.encrypt(f["password"])
    return out


async def create_farm(core: Core, actor: str, data: dict, ip: str | None = None) -> dict:
    f = _enc(core, _fields(core, data, partial=False))
    cols = list(f)
    try:
        async with core.pool.acquire() as conn, conn.transaction():
            r = await conn.fetchrow(
                f"INSERT INTO farms({', '.join(cols)}) VALUES({', '.join(f'${i+1}' for i in range(len(cols)))}) "
                f"RETURNING {PUBLIC_COLS}", *f.values())
            await audit(conn, actor, "farm.create", "farm", r["id"], {"lvl": r["lvl"], "price": r["price"]}, ip)
    except asyncpg.UniqueViolationError:
        raise StoreError("duplicate", "هذا الـ Token ID موجود مسبقاً.")
    return dict(r)


async def update_farm(core: Core, actor: str, farm_id: int, data: dict, ip: str | None = None) -> dict:
    f = _fields(core, data, partial=True)
    if "status" in data and data["status"]:
        if data["status"] not in ("available", "disabled"):
            raise StoreError("bad_input", "الحالة المسموحة: متوفر أو معطّل.")
    async with core.pool.acquire() as conn, conn.transaction():
        cur = await conn.fetchrow("SELECT * FROM farms WHERE id=$1 FOR UPDATE", farm_id)
        if not cur:
            raise StoreError("not_found", "المزرعة غير موجودة.")
        if cur["status"] in ("sold", "reserved") and (f or data.get("status")):
            raise StoreError("locked", "لا يمكن تعديل مزرعة محجوزة أو مباعة.")
        sets = _enc(core, f)
        if data.get("status"):
            sets["status"] = data["status"]
        if not sets:
            raise StoreError("bad_input", "لا توجد تعديلات.")
        cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(sets))
        try:
            r = await conn.fetchrow(f"UPDATE farms SET {cols}, updated_at=now() WHERE id=$1 RETURNING {PUBLIC_COLS}",
                                    farm_id, *sets.values())
        except asyncpg.UniqueViolationError:
            raise StoreError("duplicate", "هذا الـ Token ID موجود مسبقاً.")
        changes = {k: {"old": cur[k], "new": v} for k, v in sets.items()
                   if k in ("name", "lvl", "barn", "silo", "tools", "price", "cost", "currency", "status")}
        if "token_enc" in sets or "password_enc" in sets:
            changes["credentials_changed"] = True
        await audit(conn, actor, "farm.update", "farm", farm_id, changes, ip)
    return dict(r)


async def delete_farm(core: Core, actor: str, farm_id: int, ip: str | None = None) -> None:
    async with core.pool.acquire() as conn, conn.transaction():
        cur = await conn.fetchrow("SELECT * FROM farms WHERE id=$1 FOR UPDATE", farm_id)
        if not cur:
            raise StoreError("not_found", "المزرعة غير موجودة.")
        if cur["status"] in ("sold", "reserved") or await conn.fetchval(
                "SELECT 1 FROM order_items WHERE farm_id=$1 LIMIT 1", farm_id):
            raise StoreError("locked", "لا يمكن حذف مزرعة مرتبطة بطلب — عطّلها بدلاً من ذلك.")
        await conn.execute("DELETE FROM farms WHERE id=$1", farm_id)
        await audit(conn, actor, "farm.delete", "farm", farm_id, {"hint": cur["token_hint"], "lvl": cur["lvl"]}, ip)


async def get_farm(core: Core, farm_id: int) -> dict | None:
    return row(await core.pool.fetchrow(f"SELECT {PUBLIC_COLS} FROM farms WHERE id=$1", farm_id))


async def list_farms(core: Core, *, status: str | None = None, min_level: Any = None, max_level: Any = None,
                     min_price: Any = None, max_price: Any = None, search: str | None = None,
                     limit: int = 50, offset: int = 0) -> list[dict]:
    q = (f"SELECT {PUBLIC_COLS}, (SELECT o.ref FROM order_items i JOIN orders o ON o.id=i.order_id "
         "WHERE i.farm_id=farms.id AND i.active LIMIT 1) AS order_ref FROM farms WHERE 1=1")
    args: list[Any] = []
    if status:
        args.append(status)
        q += f" AND status=${len(args)}"
    for col, op, val in (("lvl", ">=", min_level), ("lvl", "<=", max_level),
                         ("price", ">=", min_price), ("price", "<=", max_price)):
        if val not in (None, ""):
            args.append(Decimal(str(val)))
            q += f" AND {col} {op} ${len(args)}"
    if search:
        s = search.strip()
        if s.isdigit() and len(s) < 10:
            args.append(int(s))
            q += f" AND id=${len(args)}"
        else:
            args += [core.vault.login_hash(s), f"%{s}%"]
            q += f" AND (token_hash=${len(args)-1} OR name ILIKE ${len(args)})"
    args += [limit, offset]
    q += f" ORDER BY id DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    return rows(await core.pool.fetch(q, *args))


async def bulk_status(core: Core, actor: str, ids: list[int], status: str, ip: str | None = None) -> int:
    if status not in ("available", "disabled"):
        raise StoreError("bad_input", "حالة غير صالحة.")
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute("UPDATE farms SET status=$2, updated_at=now() WHERE id = ANY($1::bigint[]) "
                               "AND status IN ('available','disabled')", ids, status)
        n = int(r.split()[-1])
        await audit(conn, actor, f"farm.bulk_{status}", "farm", None, {"ids": ids[:200], "count": n}, ip)
    return n


async def bulk_delete(core: Core, actor: str, ids: list[int], ip: str | None = None) -> int:
    async with core.pool.acquire() as conn, conn.transaction():
        r = await conn.execute(
            "DELETE FROM farms f WHERE f.id = ANY($1::bigint[]) AND f.status IN ('available','disabled') "
            "AND NOT EXISTS (SELECT 1 FROM order_items i WHERE i.farm_id=f.id)", ids)
        n = int(r.split()[-1])
        await audit(conn, actor, "farm.bulk_delete", "farm", None, {"ids": ids[:200], "count": n}, ip)
    return n


# --------------------------------------------------------------- import
CSV_HELP = "name,lvl,barn,silo,tools,price,currency,token_id,password,cost,description"


def parse_csv(data: bytes) -> tuple[list[dict], list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["تعذر قراءة الملف — احفظه بترميز UTF-8."]
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max(",;\t|", key=first.count) if first else ","
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not reader:
        return [], ["الملف فارغ."]
    aliases = {"level": "lvl", "المستوى": "lvl", "token": "token_id", "tokenid": "token_id", "id": "token_id",
               "pass": "password", "pwd": "password", "السعر": "price", "العملة": "currency", "الاسم": "name",
               "الوصف": "description", "التكلفة": "cost", "المخزن": "barn", "الصومعة": "silo", "الأدوات": "tools"}
    header = [aliases.get(h.strip().lower().replace(" ", ""), h.strip().lower()) for h in reader[0]]
    if "token_id" not in header or "password" not in header or "lvl" not in header or "price" not in header:
        return [], [f"صف العناوين مطلوب ويجب أن يحتوي على: lvl, price, token_id, password. الصيغة الكاملة: {CSV_HELP}"]
    items, errors = [], []
    for n, rec in enumerate(reader[1:], 2):
        if not any(c.strip() for c in rec):
            continue
        item = {h: (rec[i].strip() if i < len(rec) else "") for i, h in enumerate(header)}
        item["line"] = n
        items.append(item)
    return items, errors


async def import_farms(core: Core, actor: str, items: list[dict], defaults: dict | None = None,
                       preview: bool = False, ip: str | None = None) -> dict:
    """Validate every row (format + duplicates in file + duplicates in stock) then insert in one transaction."""
    defaults = defaults or {}
    valid, errors, dup_file, dup_db = [], [], [], []
    seen: dict[str, int] = {}
    for it in items:
        ln = it.get("line", "?")
        merged = {**defaults, **{k: v for k, v in it.items() if v not in (None, "")}}
        try:
            f = _fields(core, merged, partial=False)
        except StoreError as ex:
            errors.append(f"سطر {ln}: {ex.message}")
            continue
        h = core.vault.login_hash(f["token_id"])
        if h in seen:
            dup_file.append(f"سطر {ln}: مكرر مع السطر {seen[h]} ({core.vault.hint(f['token_id'])})")
            continue
        seen[h] = ln
        valid.append((ln, f, h))
    if valid:
        existing = {r["token_hash"] for r in await core.pool.fetch(
            "SELECT token_hash FROM farms WHERE token_hash = ANY($1::text[])", [h for _, _, h in valid])}
        dup_db = [f"سطر {ln}: موجود مسبقاً ({core.vault.hint(f['token_id'])})" for ln, f, h in valid if h in existing]
        valid = [v for v in valid if v[2] not in existing]
    report = {"valid": len(valid), "errors": errors, "duplicates_in_file": dup_file, "duplicates_in_db": dup_db,
              "inserted": 0}
    if preview or not valid:
        return report
    async with core.pool.acquire() as conn, conn.transaction():
        for ln, f, h in valid:
            e = _enc(core, f)
            cols = list(e)
            new_id = await conn.fetchval(
                f"INSERT INTO farms({', '.join(cols)}) VALUES({', '.join(f'${i+1}' for i in range(len(cols)))}) "
                "ON CONFLICT (token_hash) DO NOTHING RETURNING id", *e.values())
            if new_id:
                report["inserted"] += 1
            else:
                dup_db.append(f"سطر {ln}: أضيف بالتزامن من مكان آخر")
        await audit(conn, actor, "farm.import", "farm", None, {"inserted": report["inserted"], "rows": len(items)}, ip)
    return report


async def check_low_stock(core: Core, offer: dict) -> None:
    left = await core.pool.fetchval(
        "SELECT count(*) FROM farms WHERE status='available' AND name=$1 AND lvl=$2 AND barn=$3 AND silo=$4 "
        "AND tools=$5 AND price=$6 AND currency=$7",
        offer["name"], offer["lvl"], offer["barn"], offer["silo"], offer["tools"], Decimal(str(offer["price"])),
        offer["currency"])
    if left == 0:
        await raise_alert(core, "warning", "out_of_stock",
                          f"نفد مخزون «{_esc(offer['name'])}» مستوى {offer['lvl']} بسعر {offer['price']} {offer['currency']}.",
                          perm="catalog")
