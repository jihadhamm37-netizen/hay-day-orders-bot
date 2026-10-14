"""Customer API for the HD Agent app (web + Android). Bearer token bound to one device."""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile

from ..core import Core, StoreError, fmt
from ..services import chat
from ..services import customers as cust_svc
from ..services import orders as orders_svc
from ..services import payments as pay_svc
from .auth import RateLimiter, client_ip, get_core, make_token, read_token

app_login_limiter = RateLimiter(12, 600)
upload_limiter = RateLimiter(20, 600)
MAX_IMAGE = 8 * 1024 * 1024
SESSION_TTL = 10 * 365 * 24 * 3600     # "stay signed in" — revoked by resetting the device or disabling the code
VISIBLE = "(role <> 'system' OR kind <> 'internal')"


async def current_customer(request: Request, core: Core = Depends(get_core)) -> dict:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    data = read_token(core, token, "app") if token else None
    if not data:
        raise HTTPException(401, "سجّل الدخول بالكود.")
    c = await cust_svc.get(core, int(data["sub"]))
    if (not c or not c["code_active"] or c["is_banned"] or c["session_ver"] != data.get("v")
            or not c["device_id"] or c["device_id"] != data.get("dev")):
        raise HTTPException(401, "انتهت الجلسة أو تم إيقاف الكود. سجّل الدخول من جديد.")
    await core.pool.execute("UPDATE customers SET last_seen_at=now() WHERE id=$1 AND last_seen_at < now() - interval '1 minute'",
                            c["id"])
    return c


def _msg(m: dict) -> dict:
    return {"id": m["id"], "role": m["role"], "kind": m["kind"], "text": m["content"], "payload": m["payload"],
            "author": "HD Agent" if m["role"] == "admin" else None, "at": m["created_at"]}


def build_router(ok) -> APIRouter:
    r = APIRouter(prefix="/app/api")

    @r.post("/login")
    async def login(request: Request, body: dict = Body(...), core: Core = Depends(get_core)):
        if not app_login_limiter.check(client_ip(request)):
            raise HTTPException(429, "محاولات كثيرة، انتظر قليلاً ثم حاول.")
        c = await cust_svc.login_with_code(core, body.get("code", ""), body.get("device_id", ""), body.get("device_label"))
        token = make_token(core, {"p": "app", "sub": str(c["id"]), "dev": c["device_id"], "v": c["session_ver"]}, SESSION_TTL)
        await chat.welcome(core, c)
        return ok({"token": token, "name": c["first_name"], "code": c["access_code"]})

    @r.get("/me")
    async def me(c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        await chat.welcome(core, c)
        return ok({"id": c["id"], "name": c["first_name"], "code": c["access_code"], "lang": c["lang"],
                   "device": c["device_label"]})

    @r.get("/messages")
    async def messages(after: int = 0, c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        if after:
            rows = await core.pool.fetch(
                f"SELECT * FROM messages WHERE customer_id=$1 AND id>$2 AND {VISIBLE} ORDER BY id LIMIT 200", c["id"], after)
        else:
            rows = list(reversed(await core.pool.fetch(
                f"SELECT * FROM messages WHERE customer_id=$1 AND {VISIBLE} ORDER BY id DESC LIMIT 120", c["id"])))
        return ok({"messages": [_msg(dict(m)) for m in rows], "states": await _order_states(core, c["id"])})

    @r.post("/messages")
    async def send(body: dict = Body(...), c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        text = (body.get("text") or "").strip()
        if not text:
            raise StoreError("empty", "اكتب رسالتك.")
        await chat.handle_text(core, c, text)
        return ok()

    @r.post("/proof")
    async def proof(request: Request, file: UploadFile = File(...), c: dict = Depends(current_customer),
                    core: Core = Depends(get_core)):
        if not upload_limiter.check(f"c{c['id']}"):
            raise HTTPException(429, "محاولات كثيرة، انتظر قليلاً.")
        data = await file.read(MAX_IMAGE + 1)
        if len(data) > MAX_IMAGE:
            raise StoreError("too_big", "الصورة أكبر من 8MB.")
        mime = _image_type(data)
        if not mime:
            raise StoreError("not_image", "أرسل صورة (JPG أو PNG أو WEBP).")
        await chat.handle_proof(core, c, data, mime)
        return ok()

    @r.post("/orders/{order_id}/confirm")
    async def confirm(order_id: int, c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        try:
            await chat.confirm_order(core, c, order_id)
        except StoreError as ex:
            if ex.code != "already":
                raise
        return ok()

    @r.post("/orders/{order_id}/cancel")
    async def cancel(order_id: int, c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        await chat.cancel_order(core, c, order_id)
        return ok()

    @r.post("/orders/{order_id}/method")
    async def method(order_id: int, body: dict = Body(...), c: dict = Depends(current_customer),
                     core: Core = Depends(get_core)):
        await chat.choose_method(core, c, order_id, int(body.get("method_id") or 0))
        return ok()

    @r.get("/orders")
    async def my_orders(c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        out = []
        for o in await orders_svc.customer_orders(core, c["id"], 50):
            out.append({"id": o["id"], "ref": o["ref"], "status": o["status"],
                        "status_text": orders_svc.status_text(o["status"], c["lang"] or "ar"), "offer": o["offer"],
                        "quantity": o["quantity"], "total": fmt(o["total"]), "currency": o["currency"],
                        "reason": o["reason"], "created_at": o["created_at"], "delivered_at": o["delivered_at"]})
        return ok(out)

    @r.get("/orders/{order_id}/farms")
    async def farms(order_id: int, c: dict = Depends(current_customer), core: Core = Depends(get_core)):
        o = await core.pool.fetchrow("SELECT id, ref, status FROM orders WHERE id=$1 AND customer_id=$2", order_id, c["id"])
        if not o:
            raise HTTPException(404, "الطلب غير موجود.")
        if o["status"] != "delivered":
            raise StoreError("not_delivered", "تظهر البيانات بعد تأكيد الدفع والتسليم.")
        rows = await core.pool.fetch(
            "SELECT f.token_enc, f.password_enc FROM order_items i JOIN farms f ON f.id=i.farm_id "
            "WHERE i.order_id=$1 AND i.active ORDER BY f.id", order_id)
        items = [{"id": core.vault.decrypt(x["token_enc"]), "password": core.vault.decrypt(x["password_enc"])} for x in rows]
        return ok({"ref": o["ref"], "farms": items})

    return r


async def _order_states(core: Core, cid: int) -> dict[str, Any]:
    """Live status per order so old cards in the chat disable their buttons."""
    rows = await core.pool.fetch("SELECT id, status, payment_method_id FROM orders WHERE customer_id=$1 "
                                 "ORDER BY id DESC LIMIT 60", cid)
    return {str(x["id"]): {"status": x["status"], "method": x["payment_method_id"]} for x in rows}


def _image_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        kind = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        kind = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = "image/webp"
    else:
        return None
    return kind
