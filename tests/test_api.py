"""Web panel API: authentication, 2FA via Telegram, CSRF, permissions and key actions."""
from __future__ import annotations

import pytest

from app.api.server import create_app, login_limiter
from app.services import admins, orders
from tests.asgi_client import Client
from tests.conftest import add_farms, make_customer, paid_flow

PW = "StrongPass123"


@pytest.fixture(autouse=True)
def _reset_limiter():
    login_limiter.hits.clear()


async def logged_in(core, role="owner", username="boss", telegram_id=None) -> Client:
    await admins.create_admin(core, "test", username, PW, role, telegram_id)
    c = Client(create_app(core))
    r = await c.post("/api/auth/login", {"username": username, "password": PW}, csrf=False)
    assert r.status_code == 200, r.text
    if r.json()["data"]["step"] == "code":
        code = core.messenger.codes[-1][1]
        r = await c.post("/api/auth/verify", {"ticket": r.json()["data"]["ticket"], "code": code}, csrf=False)
        assert r.status_code == 200, r.text
    return c


async def test_requires_login_and_hides_root(core):
    c = Client(create_app(core))
    assert (await c.get("/api/stats/overview")).status_code == 401
    assert (await c.get("/")).text == "OK"
    assert (await c.get("/panel")).status_code == 200


async def test_telegram_code_second_factor(core):
    await admins.create_admin(core, "test", "boss", PW, "owner", 999)
    c = Client(create_app(core))
    r = await c.post("/api/auth/login", {"username": "boss", "password": PW}, csrf=False)
    data = r.json()["data"]
    assert data["step"] == "code"
    assert (await c.get("/api/auth/me")).status_code == 401
    bad = await c.post("/api/auth/verify", {"ticket": data["ticket"], "code": "000000"}, csrf=False)
    assert bad.status_code == 401
    good = await c.post("/api/auth/verify", {"ticket": data["ticket"], "code": core.messenger.codes[-1][1]}, csrf=False)
    assert good.status_code == 200
    me = (await c.get("/api/auth/me")).json()["data"]
    assert me["username"] == "boss" and me["ai_configured"] is True


async def test_csrf_required(core):
    c = await logged_in(core)
    body = {"lvl": 70, "price": "10", "token_id": "X1", "password": "p"}
    assert (await c.post("/api/farms", body, csrf=False)).status_code == 403
    assert (await c.post("/api/farms", body)).status_code == 200


async def test_support_role_limits(core):
    c = await logged_in(core, role="support", username="sup")
    assert (await c.get("/api/payments")).status_code == 200
    assert (await c.get("/api/ai/status")).status_code == 200
    assert (await c.post("/api/farms", {"lvl": 1, "price": "1", "token_id": "a", "password": "b"})).status_code == 403
    assert (await c.get("/api/admins")).status_code == 403
    assert (await c.get("/api/settings")).status_code == 403


async def test_farm_listing_never_exposes_credentials(core):
    c = await logged_in(core)
    r = await c.post("/api/farms/import-text", {"text": "SECRET-TOKEN-1:SecretPw1\nSECRET-TOKEN-2:SecretPw2",
                                               "defaults": {"lvl": 90, "price": "15"}, "preview": False})
    assert r.json()["data"]["inserted"] == 2
    listing = await c.get("/api/farms?status=available")
    assert "SECRET-TOKEN-1" not in listing.text and "SecretPw1" not in listing.text
    assert len(listing.json()["data"]) == 2
    # exact token search still works (by hash)
    found = (await c.get("/api/farms?search=SECRET-TOKEN-2")).json()["data"]
    assert len(found) == 1


async def test_csv_import(core):
    c = await logged_in(core)
    csv = "lvl,price,token_id,password,barn\n100,30,T1,P1,10000\n100,30,T1,P1,10000\nabc,30,T2,P2,1\n".encode()
    r = await c.post("/api/farms/import?preview=true", files={"file": ("a.csv", csv)})
    d = r.json()["data"]
    assert d["valid"] == 1 and d["duplicates_in_file"] and d["errors"]
    r = await c.post("/api/farms/import", files={"file": ("a.csv", csv)})
    assert r.json()["data"]["inserted"] == 1


async def test_payment_review_via_api(core):
    c = await logged_in(core)
    await make_customer(core, 5)
    await add_farms(core, 1)
    o, p = await paid_flow(core, 5)
    pend = (await c.get("/api/payments?status=pending")).json()["data"]
    assert [x["id"] for x in pend] == [p["id"]]
    r1 = await c.post(f"/api/payments/{p['id']}/approve", {})
    r2 = await c.post(f"/api/payments/{p['id']}/approve", {})
    assert r1.status_code == 200 and r2.status_code == 400
    od = (await c.get(f"/api/orders/{o['id']}")).json()["data"]
    assert od["status"] == "delivered" and "token_enc" not in str(od)
    audit = (await c.get("/api/audit?action=payment.")).json()["data"]
    assert any(a["action"] == "payment.approve" for a in audit)
    s = (await c.get("/api/stats/overview")).json()["data"]
    assert s["sales"][0]["revenue"] == "30.00" or float(s["sales"][0]["revenue"]) == 30


async def test_order_reject_requires_reason_and_notifies(core):
    c = await logged_in(core)
    await make_customer(core, 6)
    await add_farms(core, 1)
    o, p = await paid_flow(core, 6)
    assert (await c.post(f"/api/orders/{o['id']}/reject", {"reason": ""})).status_code == 400
    r = await c.post(f"/api/orders/{o['id']}/reject", {"reason": "بيانات الدفع غير صحيحة"})
    assert r.status_code == 200
    assert (await orders.get_order(core, o["id"]))["status"] == "rejected"
    assert core.messenger.customer_msgs[-1][1] == "order_rejected"


async def test_chat_takeover_and_message(core):
    c = await logged_in(core)
    await make_customer(core, 7)
    r = await c.post("/api/customers/7/message", {"text": "مرحبا من الإدارة"})
    assert r.status_code == 200
    assert core.messenger.texts[-1] == (7, "مرحبا من الإدارة")
    cust = (await c.get("/api/customers/7")).json()["data"]
    assert cust["ai_paused"] and cust["messages"][-1]["role"] == "admin"
    assert [x["id"] for x in (await c.get("/api/customers?waiting=true")).json()["data"]] == [7]
    await c.post("/api/customers/7/ai", {"enabled": True})
    assert not (await c.get("/api/customers/7")).json()["data"]["ai_paused"]


async def test_global_ai_toggle_and_settings(core):
    c = await logged_in(core)
    await c.post("/api/ai/toggle", {"enabled": False})
    assert (await c.get("/api/ai/status")).json()["data"]["enabled"] is False
    r = await c.put("/api/settings", {"reservation_minutes": "2"})
    assert r.status_code == 400
    r = await c.put("/api/settings", {"reservation_minutes": "45", "warranty_policy": "ضمان 24 ساعة"})
    assert r.status_code == 200
    s = {x["key"]: x["value"] for x in (await c.get("/api/settings")).json()["data"]}
    assert s["reservation_minutes"] == "45" and s["warranty_policy"] == "ضمان 24 ساعة"


async def test_methods_crud(core):
    c = await logged_in(core)
    r = await c.post("/api/methods", {"name": "Binance Pay 2", "kind": "binance_pay", "account": "555000111",
                                      "currency": "USDT", "require_txid": True, "is_active": True})
    assert r.status_code == 200, r.text
    mid = r.json()["data"]["id"]
    assert len((await c.get("/api/methods")).json()["data"]) == 2
    assert (await c.delete(f"/api/methods/{mid}")).status_code == 200
