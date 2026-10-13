"""Web panel API: authentication, 2FA via Telegram, CSRF, permissions and key actions."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.api.server import create_app, login_limiter
from app.services import admins, deposits, orders, wallet
from tests.asgi_client import Client
from tests.conftest import make_type, make_user

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
    r = await c.get("/")
    assert r.text == "OK"  # nothing reveals the panel location
    assert (await c.get("/panel")).status_code == 200


async def test_wrong_password_and_lockout(core):
    await admins.create_admin(core, "test", "boss", PW, "owner")
    c = Client(create_app(core))
    for _ in range(5):
        r = await c.post("/api/auth/login", {"username": "boss", "password": "nope"}, csrf=False)
        assert r.status_code == 400
    r = await c.post("/api/auth/login", {"username": "boss", "password": PW}, csrf=False)
    assert r.status_code == 400 and "قفل" in r.json()["error"]


async def test_weak_password_rejected(core):
    with pytest.raises(Exception):
        await admins.create_admin(core, "test", "weak", "123456", "admin")


async def test_telegram_code_second_factor(core):
    await admins.create_admin(core, "test", "boss", PW, "owner", telegram_id=555)
    c = Client(create_app(core))
    r = await c.post("/api/auth/login", {"username": "boss", "password": PW}, csrf=False)
    data = r.json()["data"]
    assert data["step"] == "code" and "hd_session" not in c.cookies
    assert core.messenger.codes[-1][0] == 555
    bad = await c.post("/api/auth/verify", {"ticket": data["ticket"], "code": "000000"}, csrf=False)
    assert bad.status_code == 401
    good = await c.post("/api/auth/verify", {"ticket": data["ticket"], "code": core.messenger.codes[-1][1]}, csrf=False)
    # one wrong attempt marks the code row as used=false/attempts+1 — the right code still works
    assert good.status_code == 200 and "hd_session" in c.cookies
    assert (await c.get("/api/auth/me")).json()["data"]["username"] == "boss"


async def test_csrf_required_for_changes(core):
    c = await logged_in(core)
    r = await c.post("/api/types", {"lvl": 70, "barn": 4000, "silo": 3000, "price": "10"}, csrf=False)
    assert r.status_code == 403
    r = await c.post("/api/types", {"lvl": 70, "barn": 4000, "silo": 3000, "price": "10"})
    assert r.status_code == 200 and r.json()["data"]["name"] == "LVL 70"


async def test_support_role_limits(core):
    c = await logged_in(core, role="support", username="helper")
    assert (await c.get("/api/deposits")).status_code == 200
    assert (await c.post("/api/types", {"lvl": 1, "barn": 1, "silo": 1, "price": "1"})).status_code == 403
    assert (await c.get("/api/admins")).status_code == 403
    await make_user(core, 1)
    assert (await c.post("/api/users/1/adjust", {"amount": "5", "reason": "test"})).status_code == 403


async def test_import_preview_then_save_and_no_credentials_leak(core):
    c = await logged_in(core)
    t = (await c.post("/api/types", {"lvl": 80, "barn": 5000, "silo": 4000, "price": "12.5"})).json()["data"]
    csv = b"id,password\nalpha,SecretA1\nbeta,SecretB2\nalpha,dupe\n"
    r = await c.post(f"/api/types/{t['id']}/accounts/csv?preview=true", files={"file": ("a.csv", csv)})
    rep = r.json()["data"]
    assert rep["valid"] == 2 and len(rep["duplicates_in_file"]) == 1
    assert await core.pool.fetchval("SELECT count(*) FROM farm_accounts") == 0  # preview saves nothing
    r = await c.post(f"/api/types/{t['id']}/accounts/csv", files={"file": ("a.csv", csv)})
    assert r.json()["data"]["inserted"] == 2
    r = await c.post(f"/api/types/{t['id']}/accounts", {"text": "gamma:SecretC3\nbeta:x"})
    assert r.json()["data"]["inserted"] == 1
    listing = await c.get(f"/api/accounts?type_id={t['id']}")
    body = listing.text
    assert "Secret" not in body and "alpha" not in body and "login_enc" not in body
    assert len(listing.json()["data"]) == 3


async def test_deposit_approval_via_api_is_single(core):
    c = await logged_in(core)
    await make_user(core, 7)
    d = await deposits.create(core, 7, "40")
    await deposits.attach_photo(core, 7, d["id"], "f", "uniq")
    await deposits.attach_txid(core, 7, d["id"], "M_P_777777")
    await deposits.submit(core, 7, d["id"])
    r1 = await c.post(f"/api/deposits/{d['id']}/approve", {})
    r2 = await c.post(f"/api/deposits/{d['id']}/approve", {})
    assert r1.status_code == 200 and r2.status_code == 400
    assert (await wallet.get_user(core, 7))["balance"] == Decimal("40")
    audit = (await c.get("/api/audit?action=deposit.")).json()["data"]
    assert audit[0]["actor"] == "web:boss"


async def test_adjust_balance_and_refund_via_api(core):
    c = await logged_in(core)
    await make_user(core, 3)
    r = await c.post("/api/users/3/adjust", {"amount": "15", "reason": "تعويض", "idempotency_key": "k1"})
    assert r.status_code == 200
    r = await c.post("/api/users/3/adjust", {"amount": "15", "reason": "تعويض", "idempotency_key": "k1"})
    assert r.status_code == 400  # same click twice
    r = await c.post("/api/users/3/adjust", {"amount": "-100", "reason": "خصم"})
    assert r.status_code == 400
    t = await make_type(core, 1)
    core.messenger.fail_delivery = True
    o = await orders.prepare(core, 3, t["id"], "10")
    await orders.purchase(core, 3, o["id"])
    r = await c.post(f"/api/orders/{o['id']}/refund", {"reason": "فشل التسليم", "restock": True})
    assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"
    u = (await c.get("/api/users/3")).json()["data"]
    assert Decimal(u["balance"]) == Decimal("15")
    assert (await c.get("/api/wallet/reconcile")).json()["data"] == []


async def test_settings_validation(core):
    c = await logged_in(core)
    assert (await c.put("/api/settings", {"binance_pay_id": "abc"})).status_code == 400
    assert (await c.put("/api/settings", {"binance_pay_id": "1127859028", "hide_out_of_stock": True})).status_code == 200
    s = {x["key"]: x["value"] for x in (await c.get("/api/settings")).json()["data"]}
    assert s["hide_out_of_stock"] == "true"


async def test_admin_management_and_session_revocation(core):
    c = await logged_in(core)
    r = await c.post("/api/admins", {"username": "mod1", "password": PW, "role": "admin"})
    mod_id = r.json()["data"]["id"]
    mod = Client(create_app(core))
    await mod.post("/api/auth/login", {"username": "mod1", "password": PW}, csrf=False)
    assert (await mod.get("/api/stats/overview")).status_code == 200
    await c.patch(f"/api/admins/{mod_id}", {"is_active": False})
    assert (await mod.get("/api/stats/overview")).status_code == 401
    owner_id = (await c.get("/api/auth/me")).json()["data"]["id"]
    assert (await c.patch(f"/api/admins/{owner_id}", {"role": "admin"})).status_code == 400  # last owner
