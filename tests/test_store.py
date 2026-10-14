"""Selling, reservation, payment and delivery rules against a real PostgreSQL database."""
from __future__ import annotations

import asyncio

import pytest

from app.core import StoreError
from app.services import farms, orders, payments, stats
from tests.conftest import add_farms, make_customer, method_id, offer_code, paid_flow


async def farm_status(core, ids):
    return {r["id"]: r["status"] for r in await core.pool.fetch("SELECT id, status FROM farms WHERE id = ANY($1::bigint[])", ids)}


# ------------------------------------------------------------------ catalog
async def test_duplicate_token_rejected(core):
    await add_farms(core, 1)
    with pytest.raises(StoreError) as e:
        await farms.create_farm(core, "t", {"lvl": 5, "price": "1", "token_id": "TOK100-0", "password": "x"})
    assert e.value.code == "duplicate"


async def test_import_text_dedup_and_preview(core):
    items = [{"line": 1, "token_id": "A1", "password": "p"}, {"line": 2, "token_id": "A1", "password": "p"},
             {"line": 3, "token_id": "A2", "password": "p"}]
    rep = await farms.import_farms(core, "t", items, defaults={"lvl": 80, "price": "12"}, preview=True)
    assert rep["valid"] == 2 and len(rep["duplicates_in_file"]) == 1
    assert await core.pool.fetchval("SELECT count(*) FROM farms") == 0
    rep = await farms.import_farms(core, "t", items, defaults={"lvl": 80, "price": "12"})
    assert rep["inserted"] == 2
    rep = await farms.import_farms(core, "t", items[2:], defaults={"lvl": 80, "price": "12"}, preview=True)
    assert rep["valid"] == 0 and len(rep["duplicates_in_db"]) == 1


async def test_credentials_encrypted_at_rest(core):
    f = (await add_farms(core, 1))[0]
    raw = await core.pool.fetchrow("SELECT * FROM farms WHERE id=$1", f["id"])
    assert b"TOK100-0" not in bytes(raw["token_enc"], "utf8") if isinstance(raw["token_enc"], str) else b"TOK100-0" not in raw["token_enc"]
    assert "token_enc" not in f and "password_enc" not in f


async def test_search_groups_identical_farms(core):
    await add_farms(core, 3, lvl=100, price="30")
    await add_farms(core, 2, lvl=50, price="10", prefix="B")
    offers = await farms.search_offers(core)
    assert {(o["lvl"], o["available"]) for o in offers} == {(100, 3), (50, 2)}
    assert [o["lvl"] for o in await farms.search_offers(core, max_price=15)] == [50]


# ------------------------------------------------------------------ orders
async def test_prepare_does_not_reserve(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 2)
    o = await orders.prepare(core, 1, await offer_code(core), 2)
    assert o["status"] == "pending_confirmation" and str(o["total"]) == "60.00"
    assert set((await farm_status(core, [f["id"] for f in fs])).values()) == {"available"}


async def test_prepare_rejects_more_than_stock(core):
    await make_customer(core, 1)
    await add_farms(core, 2)
    with pytest.raises(StoreError) as e:
        await orders.prepare(core, 1, await offer_code(core), 3)
    assert e.value.code == "out_of_stock"


async def test_bad_offer_code(core):
    await make_customer(core, 1)
    with pytest.raises(StoreError) as e:
        await orders.prepare(core, 1, "Fdeadbee", 1)
    assert e.value.code == "no_offer"


async def test_confirm_reserves_and_is_idempotent(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 3)
    o = await orders.prepare(core, 1, await offer_code(core), 2)
    c = await orders.confirm(core, 1, o["id"])
    assert c["status"] == "awaiting_payment" and c["reserved_until"]
    st = await farm_status(core, [f["id"] for f in fs])
    assert sorted(st.values()) == ["available", "reserved", "reserved"]
    with pytest.raises(StoreError) as e:
        await orders.confirm(core, 1, o["id"])
    assert e.value.code == "already"
    assert await core.pool.fetchval("SELECT count(*) FROM order_items") == 2


async def test_concurrent_confirm_never_double_sells(core):
    """10 customers race for 3 farms: exactly 3 get them, no farm is reserved twice."""
    await add_farms(core, 3)
    code = await offer_code(core)
    ids = []
    for cid in range(1, 11):
        await make_customer(core, cid)
        ids.append((cid, (await orders.prepare(core, cid, code, 1))["id"]))
    res = await asyncio.gather(*[orders.confirm(core, cid, oid) for cid, oid in ids], return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    assert len(ok) == 3
    assert all(isinstance(r, StoreError) and r.code == "out_of_stock" for r in res if isinstance(r, Exception))
    assert await core.pool.fetchval("SELECT count(DISTINCT farm_id) FROM order_items WHERE active") == 3
    assert await core.pool.fetchval("SELECT count(*) FROM order_items WHERE active") == 3


async def test_cannot_confirm_someone_elses_order(core):
    await make_customer(core, 1)
    await make_customer(core, 2)
    await add_farms(core, 1)
    o = await orders.prepare(core, 1, await offer_code(core), 1)
    with pytest.raises(StoreError) as e:
        await orders.confirm(core, 2, o["id"])
    assert e.value.code == "not_found"


async def test_reservation_expiry_releases_farms(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 2)
    o = await orders.prepare(core, 1, await offer_code(core), 2)
    await orders.confirm(core, 1, o["id"])
    await core.pool.execute("UPDATE orders SET reserved_until = now() - interval '1 minute' WHERE id=$1", o["id"])
    r = await orders.maintenance(core)
    assert r["expired_reservations"] == 1
    assert (await orders.get_order(core, o["id"]))["status"] == "cancelled"
    assert set((await farm_status(core, [f["id"] for f in fs])).values()) == {"available"}
    assert core.messenger.customer_msgs[-1][1] == "order_cancelled"


async def test_proof_pauses_expiry(core):
    """Once a proof is sent, the reservation is not released by the timer (admin decides)."""
    await make_customer(core, 1)
    await add_farms(core, 1)
    o, p = await paid_flow(core, 1)
    await core.pool.execute("UPDATE orders SET reserved_until = now() - interval '1 minute' WHERE id=$1", o["id"])
    await orders.maintenance(core)
    assert (await orders.get_order(core, o["id"]))["status"] == "payment_review"


async def test_customer_cancel_releases(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 1)
    o = await orders.prepare(core, 1, await offer_code(core), 1)
    await orders.confirm(core, 1, o["id"])
    await orders.cancel_by_customer(core, 1, o["ref"])
    assert (await farm_status(core, [fs[0]["id"]]))[fs[0]["id"]] == "available"


async def test_max_open_orders(core):
    await make_customer(core, 1)
    await add_farms(core, 10)
    code = await offer_code(core)
    for _ in range(3):
        o = await orders.prepare(core, 1, code, 1)
        await orders.confirm(core, 1, o["id"])
    with pytest.raises(StoreError) as e:
        await orders.prepare(core, 1, code, 1)
    assert e.value.code == "too_many_open"


# ---------------------------------------------------------------- payments
async def test_full_sale_approve_delivers(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 3)
    o, p = await paid_flow(core, 1, qty=2)
    assert (await orders.get_order(core, o["id"]))["status"] == "payment_review"
    assert core.messenger.delivered == []          # nothing sensitive before payment approval
    await payments.approve(core, "admin", p["id"])
    o2 = await orders.get_order(core, o["id"])
    assert o2["status"] == "delivered" and o2["delivered_at"]
    assert sorted(t for _, t, _ in core.messenger.delivered) == ["TOK100-0", "TOK100-1"]
    st = await farm_status(core, [f["id"] for f in fs])
    assert sorted(st.values()) == ["available", "sold", "sold"]
    s = await stats.overview(core)
    usdt = s["sales"][0]
    assert str(usdt["revenue"]) == "60.00" and str(usdt["profit"]) == "20.00"
    # approving twice is impossible
    with pytest.raises(StoreError):
        await payments.approve(core, "admin", p["id"])
    assert len(core.messenger.delivered) == 2


async def test_double_approve_race(core):
    await make_customer(core, 1)
    await add_farms(core, 1)
    _, p = await paid_flow(core, 1)
    res = await asyncio.gather(*[payments.approve(core, "a", p["id"]) for _ in range(5)], return_exceptions=True)
    assert sum(not isinstance(r, Exception) for r in res) == 1
    assert len(core.messenger.delivered) == 1


async def test_same_proof_cannot_pay_two_orders(core):
    await make_customer(core, 1)
    await make_customer(core, 2)
    await add_farms(core, 2)
    await paid_flow(core, 1, proof="SAME")
    with pytest.raises(StoreError) as e:
        await paid_flow(core, 2, proof="SAME")
    assert e.value.code == "proof_reused"


async def test_same_txid_cannot_pay_two_orders(core):
    await make_customer(core, 1)
    await make_customer(core, 2)
    await add_farms(core, 2)
    await paid_flow(core, 1, proof="a", txid="TXSAME999")
    with pytest.raises(StoreError) as e:
        await paid_flow(core, 2, proof="b", txid="TXSAME999")
    assert e.value.code == "proof_reused"


async def test_reject_lets_customer_retry_then_approve(core):
    await make_customer(core, 1)
    await add_farms(core, 1)
    o, p = await paid_flow(core, 1, proof="bad")
    await payments.reject(core, "admin", p["id"], "لم يصل المبلغ")
    assert (await orders.get_order(core, o["id"]))["status"] == "awaiting_payment"
    assert core.messenger.customer_msgs[-1][1] == "payment_rejected"
    r = await payments.submit_proof(core, 1, "file-good", "good")
    p2 = await payments.submit_txid(core, 1, r["payment"]["id"], "TXGOOD123")
    await payments.approve(core, "admin", p2["id"])
    assert (await orders.get_order(core, o["id"]))["status"] == "delivered"


async def test_reject_and_close_order(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 1)
    o, p = await paid_flow(core, 1)
    await payments.reject(core, "admin", p["id"], "إثبات مزور", close_order=True)
    o2 = await orders.get_order(core, o["id"])
    assert o2["status"] == "rejected" and o2["reason"] == "إثبات مزور"
    assert (await farm_status(core, [fs[0]["id"]]))[fs[0]["id"]] == "available"
    assert core.messenger.customer_msgs[-1][1] == "order_rejected"


async def test_reject_requires_reason(core):
    await make_customer(core, 1)
    await add_farms(core, 1)
    _, p = await paid_flow(core, 1)
    with pytest.raises(StoreError) as e:
        await payments.reject(core, "admin", p["id"], "")
    assert e.value.code == "reason_required"


async def test_failed_delivery_is_kept_and_redelivered(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 1)
    o, p = await paid_flow(core, 1)
    core.messenger.fail_delivery = True
    await payments.approve(core, "admin", p["id"])
    o2 = await orders.get_order(core, o["id"])
    assert o2["status"] == "processing" and o2["failure_reason"]
    assert (await farm_status(core, [fs[0]["id"]]))[fs[0]["id"]] == "reserved"   # never released to someone else
    core.messenger.fail_delivery = False
    assert await orders.redeliver(core, "admin", o["id"])
    assert (await orders.get_order(core, o["id"]))["status"] == "delivered"


async def test_restart_resumes_interrupted_delivery(core):
    """Process died after payment was confirmed: the maintenance job delivers it."""
    await make_customer(core, 1)
    await add_farms(core, 1)
    o, p = await paid_flow(core, 1)
    async with core.pool.acquire() as conn:
        await conn.execute("UPDATE payments SET status='approved' WHERE id=$1", p["id"])
        await conn.execute("UPDATE orders SET status='payment_confirmed', updated_at=now() - interval '5 minutes' WHERE id=$1", o["id"])
    await orders.maintenance(core)
    assert (await orders.get_order(core, o["id"]))["status"] == "delivered"
    assert len(core.messenger.delivered) == 1


async def test_admin_cancel_after_payment_confirmed_releases(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 1)
    o, p = await paid_flow(core, 1)
    await orders.admin_cancel(core, "admin", o["id"], "طلب العميل الإلغاء")
    assert (await orders.get_order(core, o["id"]))["status"] == "cancelled"
    assert (await farm_status(core, [fs[0]["id"]]))[fs[0]["id"]] == "available"
    with pytest.raises(StoreError):
        await payments.approve(core, "admin", p["id"])


async def test_sold_farm_cannot_be_edited_or_deleted(core):
    await make_customer(core, 1)
    fs = await add_farms(core, 1)
    _, p = await paid_flow(core, 1)
    await payments.approve(core, "admin", p["id"])
    with pytest.raises(StoreError):
        await farms.update_farm(core, "t", fs[0]["id"], {"price": "1"})
    with pytest.raises(StoreError):
        await farms.delete_farm(core, "t", fs[0]["id"])


async def test_audit_log_is_immutable(core):
    await add_farms(core, 1)
    with pytest.raises(Exception):
        await core.pool.execute("UPDATE audit_log SET action='x'")
    with pytest.raises(Exception):
        await core.pool.execute("DELETE FROM audit_log")


def test_parse_pairs_id_password_blocks():
    text = """ID: 24-40798340
Password: jpae48mntne6h2fxypr339ap6f38dxnmyy4yffy4

ID: 24-40798341
Password: abc:def
TOK-9:pw9
"""
    items = farms.parse_pairs(text)
    assert [(i["token_id"], i["password"]) for i in items] == [
        ("24-40798340", "jpae48mntne6h2fxypr339ap6f38dxnmyy4yffy4"), ("24-40798341", "abc:def"), ("TOK-9", "pw9")]
