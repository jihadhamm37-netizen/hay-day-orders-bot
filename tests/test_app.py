"""HD Agent customer app: code login bound to one device, AI chat, cards, proof upload, delivery."""
from __future__ import annotations

import io
import itertools
import json

import pytest
from PIL import Image

from app.api.app_api import app_login_limiter
from app.api.server import create_app, login_limiter
from app.messenger import AppMessenger
from app.services import admins, ai, customers, orders, payments
from tests.asgi_client import Client
from tests.conftest import add_farms

_ids = itertools.count(1)


class FakeModel:
    def __init__(self):
        self.steps = []
        self.payloads = []

    async def __call__(self, core, payload):
        self.payloads.append(json.loads(json.dumps(payload, default=str)))
        step = self.steps.pop(0)
        return {"content": step(payload) if callable(step) else step}


def tool(name, **inp):
    return {"type": "tool_use", "id": f"tu_{next(_ids)}", "name": name, "input": inp}


def text(t):
    return {"type": "text", "text": t}


def last_tool_result(payload) -> dict:
    return json.loads(payload["messages"][-1]["content"][-1]["content"])


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 200, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
async def env(core, monkeypatch):
    app_login_limiter.hits.clear()
    login_limiter.hits.clear()
    core.messenger = AppMessenger(core)
    model = FakeModel()
    monkeypatch.setattr(ai, "call_api", model)
    return core, Client(create_app(core)), model


class AppUser:
    def __init__(self, client: Client, token: str):
        self.c, self.h = client, {"authorization": "Bearer " + token}

    async def get(self, url):
        return await self.c.request("GET", "/app/api" + url, headers=self.h)

    async def post(self, url, body=None, files=None):
        return await self.c.request("POST", "/app/api" + url, json_body=None if files else (body or {}), headers=self.h,
                                    files=files)

    async def messages(self, after=0):
        r = await self.get(f"/messages?after={after}")
        return r.json()["data"]


async def login(client, code, device="device-aaaa-1111"):
    return await client.request("POST", "/app/api/login", json_body={"code": code, "device_id": device, "device_label": "Pixel"})


async def new_user(core, client, name="Ali"):
    code = (await customers.create_codes(core, "test", 1, name))[0]["access_code"]
    r = await login(client, code)
    assert r.status_code == 200, r.text
    return code, AppUser(client, r.json()["data"]["token"])


# ------------------------------------------------------------------ login
async def test_codes_start_with_hd_and_bind_to_one_device(env):
    core, client, _ = env
    code = (await customers.create_codes(core, "test", 1, "Sara"))[0]["access_code"]
    assert code.startswith("HD-")
    r1 = await login(client, code.lower().replace("hd-", "hd"), "phone-one-123")   # typed loosely
    assert r1.status_code == 200
    r2 = await login(client, code, "phone-one-123")          # same phone again: fine
    assert r2.status_code == 200
    r3 = await login(client, code, "phone-two-456")          # second phone: refused
    assert r3.status_code == 400 and "جهاز آخر" in r3.json()["error"]
    # admin resets the device → old session is revoked, a new phone can log in
    cid = await core.pool.fetchval("SELECT id FROM customers WHERE access_code=$1", code)
    await customers.reset_device(core, "admin", cid)
    old = AppUser(client, r1.json()["data"]["token"])
    assert (await old.get("/me")).status_code == 401
    assert (await login(client, code, "phone-two-456")).status_code == 200


async def test_bad_or_disabled_code(env):
    core, client, _ = env
    assert (await login(client, "HD-NOPE1234")).status_code == 400
    code, user = await new_user(core, client)
    cid = await core.pool.fetchval("SELECT id FROM customers WHERE access_code=$1", code)
    await customers.set_code_active(core, "admin", cid, False)
    assert (await user.get("/me")).status_code == 401
    assert (await login(client, code)).status_code == 400


async def test_requires_token(env):
    _, client, _ = env
    assert (await client.request("GET", "/app/api/messages")).status_code == 401


async def test_welcome_message_once(env):
    core, client, _ = env
    _, user = await new_user(core, client)
    await user.get("/me")
    msgs = (await user.messages())["messages"]
    assert len(msgs) == 1 and "HD Agent" in msgs[0]["text"]


# ------------------------------------------------------------- full sale
async def test_full_sale_in_app(env):
    core, client, model = env
    await add_farms(core, 6, lvl=50, price="4")
    code, user = await new_user(core, client)
    model.steps += [
        [tool("search_farms", min_level=50)],
        lambda p: [tool("prepare_order", offer_code=last_tool_result(p)["offers"][0]["offer_code"], quantity=5)],
        [text("5 مزارع × 4.00 = 20.00 USDT. متأكد تريد تشتري؟")],
    ]
    r = await user.post("/messages", {"text": "اريد 5 مزارع مستوى 50"})
    assert r.status_code == 200, r.text
    data = await user.messages()
    kinds = [m["kind"] for m in data["messages"]]
    assert "order_summary" in kinds
    card = next(m for m in data["messages"] if m["kind"] == "order_summary")
    assert card["payload"]["total"] == "20.00"
    assert data["states"][str(card["payload"]["order_id"])]["status"] == "pending_confirmation"
    # internal notes are hidden from the customer
    assert all(m["kind"] != "internal" for m in data["messages"])

    # customer says yes in text → AI confirms → payment details card (only one method)
    model.steps += [[tool("confirm_order")], [text("حوّل المبلغ وأرسل صورة التحويل.")]]
    await user.post("/messages", {"text": "نعم"})
    data = await user.messages()
    pay = next(m for m in data["messages"] if m["kind"] == "pay_details")
    assert pay["payload"]["account"] == "1127859028" and pay["payload"]["total"] == "20.00"

    # screenshot only
    r = await user.post("/proof", files={"file": ("p.png", png())})
    assert r.status_code == 200, r.text
    oid = card["payload"]["order_id"]
    assert (await orders.get_order(core, oid))["status"] == "payment_review"
    pid = await core.pool.fetchval("SELECT id FROM payments WHERE order_id=$1", oid)
    assert await core.pool.fetchval("SELECT proof_image IS NOT NULL FROM payments WHERE id=$1", pid)

    # farms not visible before approval
    assert (await user.get(f"/orders/{oid}/farms")).status_code == 400
    await payments.approve(core, "admin", pid)
    data = await user.messages()
    assert not any(m["kind"] == "delivered" for m in data["messages"])          # being prepared
    assert (await user.get(f"/orders/{oid}/farms")).status_code == 400
    await orders.deliver(core, oid, "admin")
    data = await user.messages()
    assert any(m["kind"] == "delivered" for m in data["messages"])
    farms = (await user.get(f"/orders/{oid}/farms")).json()["data"]["farms"]
    assert len(farms) == 5 and farms[0]["id"].startswith("TOK50")
    # credentials never stored in the chat
    logged = " ".join(r["content"] + json.dumps(r["payload"] or {}) for r in await core.pool.fetch("SELECT content, payload FROM messages"))
    assert "TOK50-0" not in logged and "pw0" not in logged


async def test_other_customer_cannot_see_farms(env):
    core, client, model = env
    await add_farms(core, 1)
    _, user1 = await new_user(core, client, "A")
    c2 = (await customers.create_codes(core, "t", 1, "B"))[0]["access_code"]
    user2 = AppUser(client, (await login(client, c2, "device-bbbb-2222")).json()["data"]["token"])
    model.steps += [[tool("search_farms")],
                    lambda p: [tool("prepare_order", offer_code=last_tool_result(p)["offers"][0]["offer_code"], quantity=1)],
                    [text("متأكد؟")]]
    await user1.post("/messages", {"text": "اريد مزرعة"})
    oid = (await user1.messages())["messages"][-1]["payload"]["order_id"]
    assert (await user2.post(f"/orders/{oid}/confirm")).status_code in (400, 404)
    assert (await user2.get(f"/orders/{oid}/farms")).status_code == 404


async def test_confirm_and_cancel_buttons(env):
    core, client, model = env
    fs = await add_farms(core, 2)
    _, user = await new_user(core, client)
    model.steps += [[tool("search_farms")],
                    lambda p: [tool("prepare_order", offer_code=last_tool_result(p)["offers"][0]["offer_code"], quantity=2)],
                    [text("متأكد؟")]]
    await user.post("/messages", {"text": "مزرعتين"})
    oid = next(m for m in (await user.messages())["messages"] if m["kind"] == "order_summary")["payload"]["order_id"]
    assert (await user.post(f"/orders/{oid}/confirm")).status_code == 200
    assert (await user.post(f"/orders/{oid}/confirm")).status_code == 200      # double tap is harmless
    assert await core.pool.fetchval("SELECT count(*) FROM order_items WHERE order_id=$1", oid) == 2
    assert (await user.post(f"/orders/{oid}/cancel")).status_code == 200
    assert await core.pool.fetchval("SELECT count(*) FROM farms WHERE status='available'") == 2


async def test_proof_without_order_and_non_image(env):
    core, client, _ = env
    _, user = await new_user(core, client)
    r = await user.post("/proof", files={"file": ("x.png", png())})
    assert r.status_code == 400
    r = await user.post("/proof", files={"file": ("x.txt", b"hello world")})
    assert r.status_code == 400


async def test_staff_message_appears_in_app(env):
    core, client, _ = env
    await admins.create_admin(core, "test", "boss", "StrongPass123", "owner")
    panel = Client(create_app(core))
    await panel.post("/api/auth/login", {"username": "boss", "password": "StrongPass123"}, csrf=False)
    code, user = await new_user(core, client)
    cid = await core.pool.fetchval("SELECT id FROM customers WHERE access_code=$1", code)
    r = await panel.post(f"/api/customers/{cid}/message", {"text": "أهلاً، معك الدعم"})
    assert r.status_code == 200, r.text
    msgs = (await user.messages())["messages"]
    assert msgs[-1]["role"] == "admin" and msgs[-1]["text"] == "أهلاً، معك الدعم"


async def test_panel_creates_codes_and_resets_device(env):
    core, client, _ = env
    await admins.create_admin(core, "test", "boss", "StrongPass123", "owner")
    panel = Client(create_app(core))
    await panel.post("/api/auth/login", {"username": "boss", "password": "StrongPass123"}, csrf=False)
    r = await panel.post("/api/codes", {"count": 3, "name": "VIP"})
    codes = r.json()["data"]
    assert len(codes) == 3 and all(c["access_code"].startswith("HD-") for c in codes)
    assert (await login(client, codes[0]["access_code"], "dev-xxxx-1")).status_code == 200
    assert (await login(client, codes[0]["access_code"], "dev-yyyy-2")).status_code == 400
    assert (await panel.post(f"/api/customers/{codes[0]['id']}/reset-device", {})).status_code == 200
    assert (await login(client, codes[0]["access_code"], "dev-yyyy-2")).status_code == 200


async def test_app_pages_served(env):
    _, client, _ = env
    r = await client.request("GET", "/")
    assert r.status_code == 200 and "HD Agent" in r.text
    assert (await client.request("GET", "/manifest.webmanifest")).status_code == 200
    assert (await client.request("GET", "/sw.js")).status_code == 200
    assert (await client.request("GET", "/a/icon-192.png")).status_code == 200
