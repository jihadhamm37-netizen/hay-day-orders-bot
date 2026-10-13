"""Backend API used by the web admin panel. Every route is authenticated and permission-checked."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from aiogram import Bot
from fastapi import APIRouter, Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..core import Core, StoreError
from ..services import admins, backup, catalog, deposits, orders, stats, system, wallet
from .auth import (RateLimiter, actor_of, clear_session, client_ip, current_admin, get_core, make_token, read_token,
                   require, set_session)

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PAGE = 50


def _default(o: Any):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"not serializable: {type(o)}")


class J(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=_default, ensure_ascii=False).encode("utf-8")


def ok(data: Any = None, **extra) -> J:
    return J({"ok": True, "data": data, **extra})


login_limiter = RateLimiter(10, 300)


def create_app(core: Core, bot: Bot | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, default_response_class=J)
    app.state.core = core
    app.state.bot = bot
    panel = core.config.panel_path

    @app.exception_handler(StoreError)
    async def store_error(_: Request, exc: StoreError):
        return J({"ok": False, "error": exc.message, "code": exc.code}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return J({"ok": False, "error": exc.detail}, status_code=exc.status_code)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp: Response = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        else:
            resp.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return resp

    # ------------------------------------------------------------- panel
    @app.get("/", include_in_schema=False)
    async def root():
        return Response("OK", media_type="text/plain")

    @app.get("/health", include_in_schema=False)
    async def health():
        await core.pool.fetchval("SELECT 1")
        return Response("healthy", media_type="text/plain")

    @app.get(panel, include_in_schema=False)
    @app.get(panel + "/", include_in_schema=False)
    async def panel_index():
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__PANEL__", panel)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount(panel + "/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    api = APIRouter(prefix="/api")

    # -------------------------------------------------------------- auth
    @api.post("/auth/login")
    async def login(request: Request, body: dict = Body(...), core: Core = Depends(get_core)):
        ip = client_ip(request)
        if not login_limiter.check(ip):
            raise HTTPException(429, "محاولات كثيرة، انتظر بضع دقائق.")
        a = await admins.check_login(core, body.get("username", ""), body.get("password", ""), ip)
        if core.config.require_tg_code and a.get("telegram_id"):
            sent = await admins.issue_code(core, a)
            if not sent:
                raise HTTPException(503, "تعذر إرسال رمز التحقق عبر تيليجرام. افتح البوت وأرسل /start ثم حاول.")
            ticket = make_token(core, {"p": "mfa", "sub": str(a["id"])}, 300)
            return ok({"step": "code", "ticket": ticket})
        resp = ok({"step": "done", "warning": None if a.get("telegram_id") else
                   "ننصح بربط حسابك بمعرّف تيليجرام لتفعيل رمز التحقق الثنائي."})
        set_session(core, resp, a)
        await admins.login_success(core, a["id"], ip)
        return resp

    @api.post("/auth/verify")
    async def verify(request: Request, body: dict = Body(...), core: Core = Depends(get_core)):
        ip = client_ip(request)
        if not login_limiter.check(ip):
            raise HTTPException(429, "محاولات كثيرة، انتظر بضع دقائق.")
        t = read_token(core, body.get("ticket", ""), "mfa")
        if not t:
            raise HTTPException(401, "انتهت صلاحية الجلسة، أعد تسجيل الدخول.")
        admin_id = int(t["sub"])
        if not await admins.verify_code(core, admin_id, body.get("code", "")):
            raise HTTPException(401, "الرمز غير صحيح أو منتهي.")
        a = await admins.get_admin(core, admin_id)
        if not a or not a["is_active"]:
            raise HTTPException(401, "الحساب غير نشط.")
        resp = ok({"step": "done"})
        set_session(core, resp, a)
        await admins.login_success(core, admin_id, ip)
        return resp

    @api.post("/auth/logout")
    async def logout():
        resp = ok()
        clear_session(resp)
        return resp

    @api.get("/auth/me")
    async def me(admin: dict = Depends(current_admin)):
        perms = [p for p in admins.PERMISSIONS if admins.has_perm(admin["role"], p)]
        return ok({"id": admin["id"], "username": admin["username"], "role": admin["role"],
                   "role_label": admins.ROLES[admin["role"]], "telegram_id": admin["telegram_id"], "perms": perms})

    @api.post("/auth/password")
    async def change_password(request: Request, body: dict = Body(...), admin: dict = Depends(current_admin),
                              core: Core = Depends(get_core)):
        from ..security import verify_password
        if not verify_password(body.get("current", ""), admin["password_hash"]):
            raise HTTPException(400, "كلمة المرور الحالية غير صحيحة.")
        await admins.update_admin(core, actor_of(admin), admin["id"], {"password": body.get("new", "")},
                                  client_ip(request))
        resp = ok()
        clear_session(resp)
        return resp

    # ------------------------------------------------------------- stats
    @api.get("/stats/overview")
    async def overview(_=Depends(require("view")), core: Core = Depends(get_core)):
        return ok(await stats.overview(core))

    @api.get("/stats/daily")
    async def daily(days: int = Query(30, ge=7, le=180), _=Depends(require("view")), core: Core = Depends(get_core)):
        return ok(await stats.daily(core, days))

    @api.get("/stats/top-types")
    async def top_types(_=Depends(require("view")), core: Core = Depends(get_core)):
        return ok(await stats.top_types(core))

    @api.get("/alerts")
    async def alerts(unread: bool = False, _=Depends(require("view")), core: Core = Depends(get_core)):
        return ok(await system.list_alerts(core, unread_only=unread, limit=100))

    @api.post("/alerts/read")
    async def alerts_read(body: dict = Body(default={}), _=Depends(require("view")), core: Core = Depends(get_core)):
        await system.mark_alerts_read(core, body.get("ids"))
        return ok()

    # ------------------------------------------------------------- types
    @api.get("/types")
    async def types(lvl: str | None = None, barn: str | None = None, silo: str | None = None,
                    price: str | None = None, q: str | None = None,
                    _=Depends(require("view")), core: Core = Depends(get_core)):
        flt = catalog.parse_filter(q or "")
        for name, val in (("lvl", lvl), ("barn", barn), ("silo", silo), ("price", price)):
            if val:
                flt.update(catalog.parse_filter(f"{name}{val if val[0] in '<>=' else '=' + val}"))
        return ok(await catalog.list_types(core, filters=flt))

    @api.post("/types")
    async def type_create(request: Request, body: dict = Body(...), admin=Depends(require("catalog")),
                          core: Core = Depends(get_core)):
        return ok(await catalog.create_type(core, actor_of(admin), body, client_ip(request)))

    @api.get("/types/{type_id}")
    async def type_get(type_id: int, _=Depends(require("view")), core: Core = Depends(get_core)):
        t = await catalog.get_type(core, type_id)
        if not t:
            raise HTTPException(404, "النوع غير موجود.")
        return ok({**t, "tiers": await catalog.price_tiers(core, type_id)})

    @api.patch("/types/{type_id}")
    async def type_update(type_id: int, request: Request, body: dict = Body(...), admin=Depends(require("catalog")),
                          core: Core = Depends(get_core)):
        return ok(await catalog.update_type(core, actor_of(admin), type_id, body, client_ip(request)))

    @api.delete("/types/{type_id}")
    async def type_delete(type_id: int, request: Request, admin=Depends(require("catalog")),
                          core: Core = Depends(get_core)):
        await catalog.delete_type(core, actor_of(admin), type_id, client_ip(request))
        return ok()

    # ---------------------------------------------------------- accounts
    @api.get("/accounts")
    async def accounts(type_id: int | None = None, status: str | None = None, search: str | None = None,
                       page: int = 0, _=Depends(require("view")), core: Core = Depends(get_core)):
        return ok(await catalog.list_accounts(core, type_id, status or None, PAGE, page * PAGE, search))

    async def _import(core: Core, admin: dict, request: Request, type_id: int, items: list[dict],
                      parse_errors: list[str], preview: bool):
        if len(items) > 20_000:
            raise StoreError("too_many", "الحد الأقصى 20,000 حساب في المرة الواحدة.")
        if preview:
            rep = await catalog.validate_accounts(core, items)
            return ok({"valid": len(rep["valid"]), "errors": parse_errors + rep["errors"],
                       "duplicates_in_file": rep["duplicates_in_file"], "duplicates_in_db": rep["duplicates_in_db"]})
        rep = await catalog.add_accounts(core, actor_of(admin), type_id, items, client_ip(request))
        rep["errors"] = parse_errors + rep["errors"]
        return ok(rep)

    @api.post("/types/{type_id}/accounts")
    async def accounts_add(type_id: int, request: Request, body: dict = Body(...), admin=Depends(require("catalog")),
                           core: Core = Depends(get_core)):
        if body.get("text") is not None:
            items, errors = catalog.parse_lines(body["text"])
        else:
            items, errors = [dict(x, line=i + 1) for i, x in enumerate(body.get("items") or [])], []
        return await _import(core, admin, request, type_id, items, errors, bool(body.get("preview")))

    @api.post("/types/{type_id}/accounts/csv")
    async def accounts_csv(type_id: int, request: Request, file: UploadFile = File(...), preview: bool = False,
                           admin=Depends(require("catalog")), core: Core = Depends(get_core)):
        data = await file.read(5_000_001)
        if len(data) > 5_000_000:
            raise StoreError("too_big", "الملف أكبر من 5MB.")
        items, errors = catalog.parse_csv(data)
        return await _import(core, admin, request, type_id, items, errors, preview)

    @api.patch("/accounts/{account_id}")
    async def account_update(account_id: int, request: Request, body: dict = Body(...),
                             admin=Depends(require("catalog")), core: Core = Depends(get_core)):
        return ok(await catalog.update_account(core, actor_of(admin), account_id, body, client_ip(request)))

    @api.post("/accounts/bulk")
    async def account_bulk(request: Request, body: dict = Body(...), admin=Depends(require("catalog")),
                           core: Core = Depends(get_core)):
        ids = [int(i) for i in body.get("ids", [])][:500]
        action = body.get("action")
        done, failed = 0, []
        for i in ids:
            try:
                if action == "delete":
                    await catalog.delete_account(core, actor_of(admin), i, client_ip(request))
                elif action in ("disable", "enable"):
                    await catalog.update_account(core, actor_of(admin), i,
                                                 {"status": "disabled" if action == "disable" else "available"},
                                                 client_ip(request))
                elif action == "price":
                    await catalog.update_account(core, actor_of(admin), i, {"custom_price": body.get("price")},
                                                 client_ip(request))
                else:
                    raise StoreError("bad_input", "إجراء غير معروف.")
                done += 1
            except StoreError as ex:
                failed.append(f"#{i}: {ex.message}")
        return ok({"done": done, "failed": failed})

    @api.delete("/accounts/{account_id}")
    async def account_delete(account_id: int, request: Request, admin=Depends(require("catalog")),
                             core: Core = Depends(get_core)):
        await catalog.delete_account(core, actor_of(admin), account_id, client_ip(request))
        return ok()

    # ------------------------------------------------------------ orders
    @api.get("/orders")
    async def orders_list(status: str | None = None, search: str | None = None, page: int = 0,
                          _=Depends(require("orders")), core: Core = Depends(get_core)):
        return ok(await orders.list_orders(core, status=status or None, search=search, limit=PAGE,
                                           offset=page * PAGE, include_pending=status == "pending"))

    @api.get("/orders/{order_id}")
    async def order_get(order_id: int, _=Depends(require("orders")), core: Core = Depends(get_core)):
        o = await orders.get_order(core, order_id)
        if not o:
            raise HTTPException(404, "الطلب غير موجود.")
        o["transactions"] = [dict(r) for r in await core.pool.fetch(
            "SELECT ref, amount, kind, created_at, actor, reason FROM wallet_transactions WHERE order_id=$1 ORDER BY id",
            order_id)]
        return ok(o)

    @api.post("/orders/{order_id}/redeliver")
    async def order_redeliver(order_id: int, admin=Depends(require("orders")), core: Core = Depends(get_core)):
        return ok({"delivered": await orders.retry_delivery(core, order_id, actor=actor_of(admin))})

    @api.post("/orders/{order_id}/mark-delivered")
    async def order_mark(order_id: int, request: Request, body: dict = Body(default={}),
                         admin=Depends(require("orders")), core: Core = Depends(get_core)):
        await orders.mark_delivered(core, actor_of(admin), order_id, body.get("note", ""), client_ip(request))
        return ok()

    @api.post("/orders/{order_id}/refund")
    async def order_refund(order_id: int, request: Request, body: dict = Body(...),
                           admin=Depends(require("wallet")), core: Core = Depends(get_core)):
        return ok(await orders.refund(core, actor_of(admin), order_id, body.get("reason", ""),
                                      bool(body.get("restock")), client_ip(request)))

    # ---------------------------------------------------------- deposits
    @api.get("/deposits")
    async def deposits_list(status: str | None = None, search: str | None = None, page: int = 0,
                            _=Depends(require("deposits")), core: Core = Depends(get_core)):
        return ok(await deposits.list_deposits(core, status=status or None, search=search, limit=PAGE,
                                               offset=page * PAGE))

    @api.get("/deposits/{deposit_id}/proof")
    async def deposit_proof(deposit_id: int, request: Request, _=Depends(require("deposits")),
                            core: Core = Depends(get_core)):
        d = await deposits.get(core, deposit_id)
        b: Bot | None = request.app.state.bot
        if not d or not d["proof_file_id"] or b is None:
            raise HTTPException(404, "لا توجد صورة.")
        try:
            f = await b.get_file(d["proof_file_id"])
            buf = await b.download_file(f.file_path)
        except Exception as ex:
            log.warning("proof download failed: %s", ex)
            raise HTTPException(404, "تعذر تحميل الصورة من تيليجرام.")
        return Response(buf.read(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})

    @api.post("/deposits/{deposit_id}/approve")
    async def deposit_approve(deposit_id: int, request: Request, body: dict = Body(default={}),
                              admin=Depends(require("deposits")), core: Core = Depends(get_core)):
        return ok(await deposits.approve(core, actor_of(admin), deposit_id, body.get("amount"),
                                         body.get("note", ""), client_ip(request)))

    @api.post("/deposits/{deposit_id}/reject")
    async def deposit_reject(deposit_id: int, request: Request, body: dict = Body(...),
                             admin=Depends(require("deposits")), core: Core = Depends(get_core)):
        return ok(await deposits.reject(core, actor_of(admin), deposit_id, body.get("reason", ""), client_ip(request)))

    # ------------------------------------------------------------- users
    @api.get("/users")
    async def users(q: str = "", with_balance: bool = False, page: int = 0, _=Depends(require("users")),
                    core: Core = Depends(get_core)):
        return ok(await wallet.search_users(core, q, PAGE, page * PAGE, with_balance))

    @api.get("/users/{user_id}")
    async def user_get(user_id: int, _=Depends(require("users")), core: Core = Depends(get_core)):
        u = await wallet.get_user(core, user_id)
        if not u:
            raise HTTPException(404, "المستخدم غير موجود.")
        u["transactions"] = await wallet.history(core, user_id, limit=50)
        u["orders"] = await orders.list_orders(core, user_id=user_id, limit=50)
        u["deposits"] = await deposits.list_deposits(core, user_id=user_id, limit=50)
        return ok(u)

    @api.post("/users/{user_id}/adjust")
    async def user_adjust(user_id: int, request: Request, body: dict = Body(...), admin=Depends(require("wallet")),
                          core: Core = Depends(get_core)):
        key = body.get("idempotency_key")
        return ok(await wallet.admin_adjust(core, actor_of(admin), user_id, body.get("amount"), body.get("reason", ""),
                                            f"adj:web:{key}" if key else None, client_ip(request)))

    @api.post("/users/{user_id}/ban")
    async def user_ban(user_id: int, request: Request, body: dict = Body(...), admin=Depends(require("users")),
                       core: Core = Depends(get_core)):
        await wallet.set_banned(core, actor_of(admin), user_id, bool(body.get("banned")), client_ip(request))
        return ok()

    @api.get("/transactions")
    async def transactions(user_id: int | None = None, kind: str | None = None, page: int = 0,
                           _=Depends(require("users")), core: Core = Depends(get_core)):
        return ok(await wallet.history(core, user_id, PAGE, page * PAGE, kind or None))

    @api.get("/wallet/reconcile")
    async def reconcile(_=Depends(require("wallet")), core: Core = Depends(get_core)):
        return ok(await wallet.reconcile(core))

    # ---------------------------------------------------------- settings
    @api.get("/settings")
    async def settings_get(_=Depends(require("settings")), core: Core = Depends(get_core)):
        vals = await system.get_settings(core, fresh=True)
        return ok([{"key": k, "label": lbl, "kind": kind, "value": vals.get(k, "")}
                   for k, (lbl, kind) in system.SETTINGS_SCHEMA.items()])

    @api.put("/settings")
    async def settings_put(request: Request, body: dict = Body(...), admin=Depends(require("settings")),
                           core: Core = Depends(get_core)):
        await system.update_settings(core, actor_of(admin), body, client_ip(request))
        return ok()

    # ------------------------------------------------------------ admins
    @api.get("/admins")
    async def admins_list(_=Depends(require("admins")), core: Core = Depends(get_core)):
        return ok({"admins": await admins.list_admins(core), "roles": admins.ROLES,
                   "env_owners": sorted(core.config.owner_ids)})

    @api.post("/admins")
    async def admins_create(request: Request, body: dict = Body(...), admin=Depends(require("admins")),
                            core: Core = Depends(get_core)):
        tid = body.get("telegram_id")
        return ok(await admins.create_admin(core, actor_of(admin), body.get("username", ""), body.get("password", ""),
                                            body.get("role", "admin"), int(tid) if tid else None, client_ip(request)))

    @api.patch("/admins/{admin_id}")
    async def admins_update(admin_id: int, request: Request, body: dict = Body(...),
                            admin=Depends(require("admins")), core: Core = Depends(get_core)):
        return ok(await admins.update_admin(core, actor_of(admin), admin_id, body, client_ip(request)))

    # ------------------------------------------------------------- audit
    @api.get("/audit")
    async def audit_list(page: int = 0, actor: str | None = None, action: str | None = None,
                         _=Depends(require("view")), core: Core = Depends(get_core)):
        return ok(await system.list_audit(core, PAGE, page * PAGE, actor, action))

    # ----------------------------------------------------------- backups
    @api.get("/backups")
    async def backups_list(_=Depends(require("backup")), core: Core = Depends(get_core)):
        return ok(backup.list_backups(core))

    @api.post("/backups")
    async def backups_create(request: Request, admin=Depends(require("backup")), core: Core = Depends(get_core)):
        path = await backup.make_backup(core)
        async with core.pool.acquire() as conn:
            await system.audit(conn, actor_of(admin), "backup.create", "backup", path.name, None, client_ip(request))
        return ok({"name": path.name})

    @api.get("/backups/{name}")
    async def backups_download(name: str, request: Request, admin=Depends(require("backup")),
                               core: Core = Depends(get_core)):
        path = backup.backup_path(core, name)
        async with core.pool.acquire() as conn:
            await system.audit(conn, actor_of(admin), "backup.download", "backup", name, None, client_ip(request))
        return FileResponse(path, filename=name, media_type="application/octet-stream")

    app.include_router(api)
    return app
