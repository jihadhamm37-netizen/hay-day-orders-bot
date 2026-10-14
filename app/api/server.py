"""Backend API for the admin web panel. Every route is authenticated and permission-checked."""
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
from ..services import admins, backup, customers, farms, orders, payments, stats, system
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


def ok(data: Any = None) -> J:
    return J({"ok": True, "data": data})


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
    async def login(request: Request, body: dict = Body(...)):
        ip = client_ip(request)
        if not login_limiter.check(ip):
            raise HTTPException(429, "محاولات كثيرة، انتظر بضع دقائق.")
        a = await admins.check_login(core, body.get("username", ""), body.get("password", ""), ip)
        if core.config.require_tg_code and a.get("telegram_id"):
            if not await admins.issue_code(core, a):
                raise HTTPException(503, "تعذر إرسال رمز التحقق عبر تيليجرام. افتح البوت وأرسل /start ثم حاول.")
            return ok({"step": "code", "ticket": make_token(core, {"p": "mfa", "sub": str(a["id"])}, 300)})
        resp = ok({"step": "done"})
        set_session(core, resp, a)
        await admins.login_success(core, a["id"], ip)
        return resp

    @api.post("/auth/verify")
    async def verify(request: Request, body: dict = Body(...)):
        ip = client_ip(request)
        if not login_limiter.check(ip):
            raise HTTPException(429, "محاولات كثيرة، انتظر بضع دقائق.")
        t = read_token(core, body.get("ticket", ""), "mfa")
        if not t:
            raise HTTPException(401, "انتهت صلاحية الجلسة، أعد تسجيل الدخول.")
        aid = int(t["sub"])
        if not await admins.verify_code(core, aid, body.get("code", "")):
            raise HTTPException(401, "الرمز غير صحيح أو منتهي.")
        a = await admins.get_admin(core, aid)
        if not a or not a["is_active"]:
            raise HTTPException(401, "الحساب غير نشط.")
        resp = ok({"step": "done"})
        set_session(core, resp, a)
        await admins.login_success(core, aid, ip)
        return resp

    @api.post("/auth/logout")
    async def logout():
        resp = ok()
        clear_session(resp)
        return resp

    @api.get("/auth/me")
    async def me(admin: dict = Depends(current_admin)):
        return ok({"id": admin["id"], "username": admin["username"], "role": admin["role"],
                   "role_label": admins.ROLES[admin["role"]], "telegram_id": admin["telegram_id"],
                   "perms": [p for p in admins.PERMISSIONS if admins.has_perm(admin["role"], p)],
                   "ai_configured": bool(core.config.anthropic_api_key)})

    @api.post("/auth/password")
    async def change_password(request: Request, body: dict = Body(...), admin: dict = Depends(current_admin)):
        from ..security import verify_password
        if not verify_password(body.get("current", ""), admin["password_hash"]):
            raise HTTPException(400, "كلمة المرور الحالية غير صحيحة.")
        await admins.update_admin(core, actor_of(admin), admin["id"], {"password": body.get("new", "")}, client_ip(request))
        resp = ok()
        clear_session(resp)
        return resp

    # ------------------------------------------------------------- stats
    @api.get("/stats/overview")
    async def overview(_=Depends(require("view"))):
        return ok(await stats.overview(core))

    @api.get("/stats/daily")
    async def daily(days: int = Query(30, ge=7, le=365), _=Depends(require("view"))):
        return ok(await stats.daily(core, days))

    @api.get("/stats/top-levels")
    async def top_levels(_=Depends(require("view"))):
        return ok(await stats.top_levels(core))

    @api.get("/alerts")
    async def alerts(unread: bool = False, _=Depends(require("view"))):
        return ok(await system.list_alerts(core, unread_only=unread, limit=100))

    @api.post("/alerts/read")
    async def alerts_read(body: dict = Body(default={}), _=Depends(require("view"))):
        await system.mark_alerts_read(core, body.get("ids"))
        return ok()

    # ------------------------------------------------------------- farms
    @api.get("/farms")
    async def farms_list(status: str | None = None, min_level: str | None = None, max_level: str | None = None,
                         min_price: str | None = None, max_price: str | None = None, search: str | None = None,
                         page: int = 0, _=Depends(require("view"))):
        return ok(await farms.list_farms(core, status=status or None, min_level=min_level, max_level=max_level,
                                         min_price=min_price, max_price=max_price, search=search,
                                         limit=PAGE, offset=page * PAGE))

    @api.get("/farms/summary")
    async def farms_summary(_=Depends(require("view"))):
        return ok({"stock": await farms.stock_summary(core), "offers": await farms.search_offers(core, limit=50)})

    @api.post("/farms")
    async def farm_create(request: Request, body: dict = Body(...), admin=Depends(require("catalog"))):
        return ok(await farms.create_farm(core, actor_of(admin), body, client_ip(request)))

    @api.patch("/farms/{farm_id}")
    async def farm_update(farm_id: int, request: Request, body: dict = Body(...), admin=Depends(require("catalog"))):
        return ok(await farms.update_farm(core, actor_of(admin), farm_id, body, client_ip(request)))

    @api.delete("/farms/{farm_id}")
    async def farm_delete(farm_id: int, request: Request, admin=Depends(require("catalog"))):
        await farms.delete_farm(core, actor_of(admin), farm_id, client_ip(request))
        return ok()

    @api.post("/farms/bulk")
    async def farm_bulk(request: Request, body: dict = Body(...), admin=Depends(require("catalog"))):
        ids = [int(i) for i in body.get("ids", [])][:1000]
        action = body.get("action")
        if action == "delete":
            n = await farms.bulk_delete(core, actor_of(admin), ids, client_ip(request))
        elif action in ("disable", "enable"):
            n = await farms.bulk_status(core, actor_of(admin), ids, "disabled" if action == "disable" else "available",
                                        client_ip(request))
        else:
            raise StoreError("bad_input", "إجراء غير معروف.")
        return ok({"done": n, "skipped": len(ids) - n})

    @api.post("/farms/import")
    async def farm_import_csv(request: Request, file: UploadFile = File(...), preview: bool = False,
                              admin=Depends(require("catalog"))):
        data = await file.read(10_000_001)
        if len(data) > 10_000_000:
            raise StoreError("too_big", "الملف أكبر من 10MB.")
        items, errors = farms.parse_csv(data)
        if len(items) > 20000:
            raise StoreError("too_many", "الحد الأقصى 20,000 مزرعة في المرة الواحدة.")
        rep = await farms.import_farms(core, actor_of(admin), items, preview=preview, ip=client_ip(request))
        rep["errors"] = errors + rep["errors"]
        return ok(rep)

    @api.post("/farms/import-text")
    async def farm_import_text(request: Request, body: dict = Body(...), admin=Depends(require("catalog"))):
        """Shared details (level, price…) + one 'TokenID:Password' per line."""
        items = []
        for n, line in enumerate((body.get("text") or "").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            for sep in (":", ",", ";", "\t", "|", " "):
                if sep in line:
                    tok, pw = line.split(sep, 1)
                    break
            else:
                tok, pw = line, ""
            items.append({"line": n, "token_id": tok.strip(), "password": pw.strip()})
        rep = await farms.import_farms(core, actor_of(admin), items, defaults=body.get("defaults") or {},
                                       preview=bool(body.get("preview")), ip=client_ip(request))
        return ok(rep)

    # ------------------------------------------------------------ orders
    @api.get("/orders")
    async def orders_list(status: str | None = None, search: str | None = None, page: int = 0,
                          _=Depends(require("orders"))):
        return ok(await orders.list_orders(core, status=status or None, search=search, limit=PAGE, offset=page * PAGE))

    @api.get("/orders/{order_id}")
    async def order_get(order_id: int, _=Depends(require("orders"))):
        o = await orders.get_order(core, order_id)
        if not o:
            raise HTTPException(404, "الطلب غير موجود.")
        return ok(o)

    @api.post("/orders/{order_id}/cancel")
    async def order_cancel(order_id: int, request: Request, body: dict = Body(...), admin=Depends(require("orders"))):
        return ok(await orders.admin_cancel(core, actor_of(admin), order_id, body.get("reason", ""), client_ip(request)))

    @api.post("/orders/{order_id}/reject")
    async def order_reject(order_id: int, request: Request, body: dict = Body(...), admin=Depends(require("orders"))):
        return ok(await orders.admin_reject(core, actor_of(admin), order_id, body.get("reason", ""), client_ip(request)))

    @api.post("/orders/{order_id}/redeliver")
    async def order_redeliver(order_id: int, admin=Depends(require("orders"))):
        return ok({"delivered": await orders.redeliver(core, actor_of(admin), order_id)})

    @api.post("/orders/{order_id}/notify")
    async def order_notify(order_id: int, request: Request, body: dict = Body(default={}), admin=Depends(require("orders"))):
        o = await orders.get_order(core, order_id)
        if not o:
            raise HTTPException(404, "الطلب غير موجود.")
        text = (body.get("text") or "").strip()
        if text:
            sent = await core.messenger.send_text(o["customer_id"], text) if core.messenger else False
            if sent:
                await customers.log_message(core, o["customer_id"], "admin", text, author=admin["username"])
        else:
            sent = await core.messenger.notify_customer(o["customer_id"], f"status:{o['status']}", ref=o["ref"]) if core.messenger else False
        async with core.pool.acquire() as conn:
            await system.audit(conn, actor_of(admin), "order.notify", "order", order_id, {"custom": bool(text)}, client_ip(request))
        return ok({"sent": sent})

    # ---------------------------------------------------------- payments
    @api.get("/payments")
    async def payments_list(status: str | None = None, search: str | None = None, page: int = 0,
                            _=Depends(require("payments"))):
        return ok(await payments.list_payments(core, status=status or None, search=search, limit=PAGE, offset=page * PAGE))

    @api.get("/payments/{payment_id}")
    async def payment_get(payment_id: int, _=Depends(require("payments"))):
        p = await payments.get_payment(core, payment_id)
        if not p:
            raise HTTPException(404, "غير موجود.")
        return ok(p)

    @api.get("/payments/{payment_id}/proof")
    async def payment_proof(payment_id: int, request: Request, _=Depends(require("payments"))):
        p = await payments.get_payment(core, payment_id)
        b: Bot | None = request.app.state.bot
        if not p or not p["proof_file_id"] or b is None:
            raise HTTPException(404, "لا توجد صورة.")
        try:
            f = await b.get_file(p["proof_file_id"])
            buf = await b.download_file(f.file_path)
        except Exception:
            raise HTTPException(404, "تعذر تحميل الصورة من تيليجرام.")
        return Response(buf.read(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})

    @api.post("/payments/{payment_id}/approve")
    async def payment_approve(payment_id: int, request: Request, admin=Depends(require("payments"))):
        return ok(await payments.approve(core, actor_of(admin), payment_id, client_ip(request)))

    @api.post("/payments/{payment_id}/reject")
    async def payment_reject(payment_id: int, request: Request, body: dict = Body(...), admin=Depends(require("payments"))):
        return ok(await payments.reject(core, actor_of(admin), payment_id, body.get("reason", ""),
                                        close_order=bool(body.get("close_order")), ip=client_ip(request)))

    # ----------------------------------------------------------- methods
    @api.get("/methods")
    async def methods_list(_=Depends(require("view"))):
        return ok(await payments.list_methods(core))

    @api.post("/methods")
    async def method_create(request: Request, body: dict = Body(...), admin=Depends(require("methods"))):
        return ok(await payments.create_method(core, actor_of(admin), body, client_ip(request)))

    @api.patch("/methods/{method_id}")
    async def method_update(method_id: int, request: Request, body: dict = Body(...), admin=Depends(require("methods"))):
        return ok(await payments.update_method(core, actor_of(admin), method_id, body, client_ip(request)))

    @api.delete("/methods/{method_id}")
    async def method_delete(method_id: int, request: Request, admin=Depends(require("methods"))):
        await payments.delete_method(core, actor_of(admin), method_id, client_ip(request))
        return ok()

    # --------------------------------------------------------- customers
    @api.get("/customers")
    async def customers_list(q: str = "", waiting: bool = False, page: int = 0, _=Depends(require("customers"))):
        return ok(await customers.search(core, q, waiting=waiting, limit=PAGE, offset=page * PAGE))

    @api.get("/customers/{customer_id}")
    async def customer_get(customer_id: int, before: int | None = None, _=Depends(require("customers"))):
        c = await customers.get(core, customer_id)
        if not c:
            raise HTTPException(404, "العميل غير موجود.")
        c["messages"] = await customers.history(core, customer_id, 100, before)
        c["orders"] = await orders.list_orders(core, customer_id=customer_id, limit=50)
        return ok(c)

    @api.post("/customers/{customer_id}/message")
    async def customer_message(customer_id: int, request: Request, body: dict = Body(...), admin=Depends(require("chat"))):
        text = (body.get("text") or "").strip()
        if not text:
            raise StoreError("bad_input", "اكتب الرسالة.")
        if not core.messenger or not await core.messenger.send_text(customer_id, text):
            raise StoreError("send_failed", "تعذر إرسال الرسالة (ربما حظر العميل البوت).")
        await customers.log_message(core, customer_id, "admin", text, author=admin["username"])
        if body.get("takeover", True):
            await core.pool.execute("UPDATE customers SET ai_paused=TRUE WHERE id=$1", customer_id)
        return ok()

    @api.post("/customers/{customer_id}/ai")
    async def customer_ai(customer_id: int, request: Request, body: dict = Body(...), admin=Depends(require("chat"))):
        await customers.set_ai_paused(core, actor_of(admin), customer_id, not bool(body.get("enabled")), client_ip(request))
        return ok()

    @api.post("/customers/{customer_id}/ban")
    async def customer_ban(customer_id: int, request: Request, body: dict = Body(...), admin=Depends(require("customers"))):
        await customers.set_banned(core, actor_of(admin), customer_id, bool(body.get("banned")), client_ip(request))
        return ok()

    @api.post("/customers/{customer_id}/notes")
    async def customer_notes(customer_id: int, request: Request, body: dict = Body(...), admin=Depends(require("customers"))):
        await customers.set_notes(core, actor_of(admin), customer_id, body.get("notes", ""), client_ip(request))
        return ok()

    # ---------------------------------------------------------- settings
    @api.get("/settings")
    async def settings_get(_=Depends(require("settings"))):
        vals = await system.get_settings(core, fresh=True)
        return ok([{"key": k, "label": lbl, "kind": kind, "value": vals.get(k, "")}
                   for k, (lbl, kind) in system.SETTINGS_SCHEMA.items()])

    @api.put("/settings")
    async def settings_put(request: Request, body: dict = Body(...), admin=Depends(require("settings"))):
        await system.update_settings(core, actor_of(admin), body, client_ip(request))
        return ok()

    @api.get("/ai/status")
    async def ai_status(_=Depends(require("view"))):
        return ok({"enabled": (await system.setting(core, "ai_enabled", "true")) == "true",
                   "configured": bool(core.config.anthropic_api_key)})

    @api.post("/ai/toggle")
    async def ai_toggle(request: Request, body: dict = Body(...), admin=Depends(require("chat"))):
        await system.update_settings(core, actor_of(admin), {"ai_enabled": bool(body.get("enabled"))}, client_ip(request))
        return ok()

    # ------------------------------------------------------------ admins
    @api.get("/admins")
    async def admins_list(_=Depends(require("admins"))):
        return ok({"admins": await admins.list_admins(core), "roles": admins.ROLES,
                   "env_owners": sorted(core.config.owner_ids)})

    @api.post("/admins")
    async def admins_create(request: Request, body: dict = Body(...), admin=Depends(require("admins"))):
        tid = body.get("telegram_id")
        return ok(await admins.create_admin(core, actor_of(admin), body.get("username", ""), body.get("password", ""),
                                            body.get("role", "admin"), int(tid) if tid else None, client_ip(request)))

    @api.patch("/admins/{admin_id}")
    async def admins_update(admin_id: int, request: Request, body: dict = Body(...), admin=Depends(require("admins"))):
        return ok(await admins.update_admin(core, actor_of(admin), admin_id, body, client_ip(request)))

    # ------------------------------------------------------------- audit
    @api.get("/audit")
    async def audit_list(page: int = 0, actor: str | None = None, action: str | None = None, _=Depends(require("view"))):
        return ok(await system.list_audit(core, PAGE, page * PAGE, actor, action))

    # ----------------------------------------------------------- backups
    @api.get("/backups")
    async def backups_list(_=Depends(require("backup"))):
        return ok(backup.list_backups(core))

    @api.post("/backups")
    async def backups_create(request: Request, admin=Depends(require("backup"))):
        path = await backup.make_backup(core)
        async with core.pool.acquire() as conn:
            await system.audit(conn, actor_of(admin), "backup.create", "backup", path.name, None, client_ip(request))
        return ok({"name": path.name})

    @api.get("/backups/{name}")
    async def backups_download(name: str, request: Request, admin=Depends(require("backup"))):
        path = backup.backup_path(core, name)
        async with core.pool.acquire() as conn:
            await system.audit(conn, actor_of(admin), "backup.download", "backup", name, None, client_ip(request))
        return FileResponse(path, filename=name, media_type="application/octet-stream")

    app.include_router(api)
    return app
