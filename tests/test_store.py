"""Money, inventory and purchase safety — run against real PostgreSQL."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import asyncpg
import pytest

from app.core import StoreError
from app.services import catalog, deposits, orders, wallet
from tests.conftest import make_type, make_user

D = Decimal


# ----------------------------------------------------------------- wallet
async def test_balance_only_changes_through_ledger(core):
    await make_user(core, 1, "20")
    with pytest.raises(asyncpg.PostgresError):
        await core.pool.execute("UPDATE users SET balance = 1000 WHERE id=1")
    with pytest.raises(asyncpg.PostgresError):
        await core.pool.execute("INSERT INTO users(id, balance) VALUES (77, 50)")
    assert (await wallet.get_user(core, 1))["balance"] == D("20")
    assert await wallet.reconcile(core) == []


async def test_ledger_is_append_only(core):
    await make_user(core, 1, "5")
    with pytest.raises(asyncpg.PostgresError):
        await core.pool.execute("UPDATE wallet_transactions SET amount=500")
    with pytest.raises(asyncpg.PostgresError):
        await core.pool.execute("DELETE FROM wallet_transactions")


async def test_no_negative_balance_and_reason_required(core):
    await make_user(core, 1, "5")
    with pytest.raises(StoreError) as e:
        await wallet.admin_adjust(core, "test", 1, "-6", "خصم أكبر من الرصيد")
    assert e.value.code == "insufficient_funds"
    with pytest.raises(StoreError):
        await wallet.admin_adjust(core, "test", 1, "1", "")
    tx = await wallet.admin_adjust(core, "test", 1, "-5", "خصم كامل")
    assert tx["balance_after"] == D("0")


async def test_admin_adjust_idempotent(core):
    await make_user(core, 1)
    await wallet.admin_adjust(core, "test", 1, "10", "مكافأة", idempotency_key="same-click")
    with pytest.raises(StoreError) as e:
        await wallet.admin_adjust(core, "test", 1, "10", "مكافأة", idempotency_key="same-click")
    assert e.value.code == "duplicate"
    assert (await wallet.get_user(core, 1))["balance"] == D("10")


# ---------------------------------------------------------------- catalog
async def test_credentials_are_encrypted_and_deduplicated(core):
    t = await make_type(core, 3)
    raw = await core.pool.fetch("SELECT login_enc, password_enc FROM farm_accounts")
    for i, r in enumerate(raw):
        assert f"farm70_{i}" not in r["login_enc"] and f"pw{i}" not in r["password_enc"]
        assert core.vault.decrypt(r["login_enc"]).startswith("farm70_")
    rep = await catalog.add_accounts(core, "test", t["id"], [
        {"line": 1, "login": "FARM70_0", "password": "x"},   # exists already (case-insensitive)
        {"line": 2, "login": "new1", "password": "a"},
        {"line": 3, "login": "new1", "password": "b"},       # duplicate in batch
        {"line": 4, "login": "", "password": "b"},           # error
        {"line": 5, "login": "new2", "password": "c", "price": "-3"},  # bad price
    ])
    assert rep["inserted"] == 1
    assert len(rep["duplicates_in_db"]) == 1 and len(rep["duplicates_in_file"]) == 1 and len(rep["errors"]) == 2


async def test_csv_parsing_with_header_and_semicolons(core):
    data = "id;password;price;note\nabc;123;;\nxyz;456;12.5;vip\n;;\nbad\n".encode()
    items, errors = catalog.parse_csv(data)
    assert [i["login"] for i in items] == ["abc", "xyz"]
    assert items[1]["price"] == "12.5" and items[1]["note"] == "vip"
    assert errors  # the 'bad' line


async def test_sold_account_cannot_be_deleted(core):
    t = await make_type(core, 1)
    await make_user(core, 1, "10")
    o = await orders.prepare(core, 1, t["id"], "10")
    await orders.purchase(core, 1, o["id"])
    acc = await core.pool.fetchval("SELECT id FROM farm_accounts")
    with pytest.raises(StoreError):
        await catalog.delete_account(core, "test", acc)
    with pytest.raises(asyncpg.PostgresError):
        await core.pool.execute("DELETE FROM farm_accounts")


# ---------------------------------------------------------------- purchase
async def test_purchase_happy_path(core):
    t = await make_type(core, 2)
    await make_user(core, 1, "25")
    o = await orders.prepare(core, 1, t["id"], "10")
    assert o["status"] == "pending"
    assert (await wallet.get_user(core, 1))["balance"] == D("25")  # nothing charged before confirm
    done = await orders.purchase(core, 1, o["id"])
    assert done["status"] == "completed" and done["delivered_at"]
    assert (await wallet.get_user(core, 1))["balance"] == D("15")
    assert core.messenger.credentials == [(1, "farm70_0", "pw0")]
    assert await core.pool.fetchval("SELECT status FROM farm_accounts WHERE id=$1", done["account_id"]) == "sold"
    assert any("عملية بيع" in m for m in core.messenger.admin_msgs)
    # buyer can view credentials again; another user cannot
    _, login, pw = await orders.buyer_credentials(core, 1, o["id"])
    assert (login, pw) == ("farm70_0", "pw0")
    with pytest.raises(StoreError):
        await orders.buyer_credentials(core, 2, o["id"])


async def test_double_click_charges_once(core):
    t = await make_type(core, 5)
    await make_user(core, 1, "100")
    o = await orders.prepare(core, 1, t["id"], "10")
    results = await asyncio.gather(*[orders.purchase(core, 1, o["id"]) for _ in range(8)], return_exceptions=True)
    ok = [r for r in results if isinstance(r, dict)]
    assert len(ok) == 1
    assert all(isinstance(r, StoreError) for r in results if not isinstance(r, dict))
    assert (await wallet.get_user(core, 1))["balance"] == D("90")
    assert len(core.messenger.credentials) == 1
    assert await core.pool.fetchval("SELECT count(*) FROM farm_accounts WHERE status='sold'") == 1


async def test_concurrent_buyers_never_share_an_account(core):
    t = await make_type(core, 5)
    buyers = list(range(100, 130))
    for b in buyers:
        await make_user(core, b, "10")
    prepared = [await orders.prepare(core, b, t["id"], "10") for b in buyers]
    results = await asyncio.gather(*[orders.purchase(core, o["user_id"], o["id"]) for o in prepared],
                                   return_exceptions=True)
    winners = [r for r in results if isinstance(r, dict) and r["status"] == "completed"]
    losers = [r for r in results if isinstance(r, StoreError)]
    assert len(winners) == 5 and len(losers) == 25
    assert all(r.code == "out_of_stock" for r in losers)
    assert len({w["account_id"] for w in winners}) == 5
    # losers keep their money, winners paid exactly once
    for b in buyers:
        bal = (await wallet.get_user(core, b))["balance"]
        assert bal == (D("0") if any(w["user_id"] == b for w in winners) else D("10"))
    assert await wallet.reconcile(core) == []
    assert len({c[1] for c in core.messenger.credentials}) == 5


async def test_insufficient_balance_no_charge_no_reservation(core):
    t = await make_type(core, 1)
    await make_user(core, 1, "9.99")
    with pytest.raises(StoreError) as e:
        await orders.prepare(core, 1, t["id"], "10")
    assert e.value.code == "insufficient_funds"
    # balance drops between prepare and confirm → confirm must fail cleanly
    await make_user(core, 2, "10")
    o = await orders.prepare(core, 2, t["id"], "10")
    await wallet.admin_adjust(core, "test", 2, "-5", "خصم")
    with pytest.raises(StoreError) as e:
        await orders.purchase(core, 2, o["id"])
    assert e.value.code == "insufficient_funds"
    assert await core.pool.fetchval("SELECT status FROM farm_accounts") == "available"
    assert (await orders.get_order(core, o["id"]))["status"] == "cancelled"
    assert (await wallet.get_user(core, 2))["balance"] == D("5")


async def test_delivery_failure_keeps_order_in_review_then_retry(core):
    t = await make_type(core, 1)
    await make_user(core, 1, "10")
    core.messenger.fail_delivery = True
    o = await orders.prepare(core, 1, t["id"], "10")
    res = await orders.purchase(core, 1, o["id"])
    assert res["status"] == "needs_review"
    assert await core.pool.fetchval("SELECT status FROM farm_accounts") == "reserved"
    assert await core.pool.fetchval("SELECT count(*) FROM alerts WHERE kind='delivery_failed'") == 1
    core.messenger.fail_delivery = False
    assert await orders.retry_delivery(core, o["id"], user_id=1)
    assert (await orders.get_order(core, o["id"]))["status"] == "completed"
    assert await core.pool.fetchval("SELECT status FROM farm_accounts") == "sold"
    with pytest.raises(StoreError):  # cannot be re-delivered once completed
        await orders.retry_delivery(core, o["id"], user_id=1)


async def test_refund_once_and_restock(core):
    t = await make_type(core, 1)
    await make_user(core, 1, "10")
    core.messenger.fail_delivery = True
    o = await orders.prepare(core, 1, t["id"], "10")
    await orders.purchase(core, 1, o["id"])
    r = await asyncio.gather(orders.refund(core, "a1", o["id"], "تعذر التسليم", restock=True),
                             orders.refund(core, "a2", o["id"], "تعذر التسليم", restock=True),
                             return_exceptions=True)
    assert sum(isinstance(x, dict) for x in r) == 1
    assert (await wallet.get_user(core, 1))["balance"] == D("10")
    assert await core.pool.fetchval("SELECT status FROM farm_accounts") == "available"
    assert await wallet.reconcile(core) == []


async def test_custom_price_tiers(core):
    t = await make_type(core, 2)
    acc = await core.pool.fetchval("SELECT id FROM farm_accounts ORDER BY id DESC LIMIT 1")
    await catalog.update_account(core, "test", acc, {"custom_price": "15"})
    tiers = await catalog.price_tiers(core, t["id"])
    assert [(x["price"], x["available"]) for x in tiers] == [(D("10"), 1), (D("15"), 1)]
    await make_user(core, 1, "15")
    o = await orders.prepare(core, 1, t["id"], "15")
    done = await orders.purchase(core, 1, o["id"])
    assert done["account_id"] == acc and done["price"] == D("15")
    await catalog.update_type(core, "test", t["id"], {"price": "11"})
    assert [x["price"] for x in await catalog.price_tiers(core, t["id"])] == [D("11")]


async def test_inactive_type_cannot_be_sold(core):
    t = await make_type(core, 2)
    await make_user(core, 1, "50")
    o = await orders.prepare(core, 1, t["id"], "10")
    await catalog.update_type(core, "test", t["id"], {"is_active": False})
    with pytest.raises(StoreError):
        await orders.purchase(core, 1, o["id"])
    assert (await wallet.get_user(core, 1))["balance"] == D("50")
    assert not await catalog.list_types(core, for_customers=True)


async def test_out_of_stock_alert(core):
    t = await make_type(core, 1)
    await make_user(core, 1, "10")
    o = await orders.prepare(core, 1, t["id"], "10")
    await orders.purchase(core, 1, o["id"])
    assert await core.pool.fetchval("SELECT count(*) FROM alerts WHERE kind='out_of_stock'") == 1


# --------------------------------------------------------------- deposits
async def _deposit(core, uid, amount="20", file_uid="F1", txid="M_P_1001"):
    d = await deposits.create(core, uid, amount)
    await deposits.attach_photo(core, uid, d["id"], "file-" + file_uid, file_uid)
    await deposits.attach_txid(core, uid, d["id"], txid)
    return await deposits.submit(core, uid, d["id"])


async def test_deposit_flow_and_single_credit(core):
    await make_user(core, 1)
    d = await _deposit(core, 1)
    assert d["status"] == "under_review"
    assert (await wallet.get_user(core, 1))["balance"] == D("0")
    res = await asyncio.gather(*[deposits.approve(core, f"admin{i}", d["id"]) for i in range(6)], return_exceptions=True)
    assert sum(isinstance(r, dict) for r in res) == 1
    assert (await wallet.get_user(core, 1))["balance"] == D("20")
    with pytest.raises(StoreError):
        await deposits.reject(core, "admin", d["id"], "متأخر")
    assert any("تم قبول" in m for _, m in core.messenger.user_msgs)


async def test_deposit_proof_cannot_be_reused(core):
    await make_user(core, 1)
    await make_user(core, 2)
    await _deposit(core, 1, file_uid="SAME", txid="M_P_555")
    d2 = await deposits.create(core, 2, "20")
    with pytest.raises(StoreError) as e:
        await deposits.attach_photo(core, 2, d2["id"], "x", "SAME")
    assert e.value.code == "proof_reused"
    await deposits.attach_photo(core, 2, d2["id"], "x", "OTHER")
    with pytest.raises(StoreError) as e:
        await deposits.attach_txid(core, 2, d2["id"], "m_p_555")  # case-insensitive
    assert e.value.code == "proof_reused"


async def test_deposit_requires_proof_and_limits(core):
    await make_user(core, 1)
    with pytest.raises(StoreError):
        await deposits.create(core, 1, "0.5")
    with pytest.raises(StoreError):
        await deposits.create(core, 1, "999999")
    d = await deposits.create(core, 1, "10")
    with pytest.raises(StoreError):
        await deposits.submit(core, 1, d["id"])  # no screenshot yet
    await deposits.attach_photo(core, 1, d["id"], "f", "u1")
    with pytest.raises(StoreError):
        await deposits.submit(core, 1, d["id"])  # txid required by default


async def test_deposit_reject_and_partial_approve(core):
    await make_user(core, 1)
    d = await _deposit(core, 1, "30")
    with pytest.raises(StoreError):
        await deposits.reject(core, "admin", d["id"], "")
    await deposits.approve(core, "admin", d["id"], credited="25", note="وصل 25 فقط")
    assert (await wallet.get_user(core, 1))["balance"] == D("25")
    d2 = await _deposit(core, 1, "10", file_uid="F2", txid="M_P_2002")
    await deposits.reject(core, "admin", d2["id"], "لم يصل المبلغ")
    assert (await wallet.get_user(core, 1))["balance"] == D("25")


async def test_binance_matcher():
    from datetime import datetime, timezone
    from app.services.binance import match
    created = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    ms = int(created.timestamp() * 1000) + 60_000
    txs = [{"transactionId": "M_P_123", "currency": "USDT", "amount": "20", "transactionTime": ms,
            "receiverInfo": {"binanceId": "1127859028"}}]
    assert match(txs, "M_P_123", D("20"), created, "1127859028")[0]
    assert not match(txs, "M_P_123", D("25"), created, "1127859028")[0]
    assert not match(txs, "M_P_999", D("20"), created, "1127859028")[0]
    assert not match([{**txs[0], "amount": "-20"}], "M_P_123", D("20"), created)[0]
    assert not match(txs, "M_P_123", D("20"), created, "555")[0]


async def test_maintenance_flags_stuck_orders(core):
    t = await make_type(core, 2)
    await make_user(core, 1, "10")
    o = await orders.prepare(core, 1, t["id"], "10")
    await core.pool.execute("UPDATE orders SET created_at = now() - interval '1 hour' WHERE id=$1", o["id"])
    r = await orders.maintenance(core)
    assert r["expired"] == 1
    # simulate a crash right after charging
    o2 = await orders.prepare(core, 1, t["id"], "10")
    await orders._confirm(core, 1, o2["id"])
    await core.pool.execute("UPDATE orders SET updated_at = now() - interval '1 hour' WHERE id=$1", o2["id"])
    assert (await orders.maintenance(core))["stuck"] == 1
    assert (await orders.get_order(core, o2["id"]))["status"] == "needs_review"


async def test_quantity_is_all_or_nothing_under_concurrency(core):
    t = await make_type(core, 5)
    await make_user(core, 1, "30")
    await make_user(core, 2, "30")
    o1 = await orders.prepare(core, 1, t["id"], "10", qty=3)
    o2 = await orders.prepare(core, 2, t["id"], "10", qty=3)
    assert o1["total"] == D("30") and len(o1["order_ids"]) == 3
    res = await asyncio.gather(orders.purchase(core, 1, o1["id"]), orders.purchase(core, 2, o2["id"]),
                               return_exceptions=True)
    ok = [r for r in res if isinstance(r, dict)]
    bad = [r for r in res if isinstance(r, StoreError)]
    assert len(ok) == 1 and len(bad) == 1 and bad[0].code == "out_of_stock"
    assert len(ok[0]["batch"]) == 3 and all(x["status"] == "completed" for x in ok[0]["batch"])
    balances = sorted([(await wallet.get_user(core, u))["balance"] for u in (1, 2)])
    assert balances == [D("0"), D("30")]          # loser charged nothing
    assert await core.pool.fetchval("SELECT count(*) FROM farm_accounts WHERE status='available'") == 2
    assert await wallet.reconcile(core) == []
    with pytest.raises(StoreError):
        await orders.prepare(core, 1, t["id"], "10", qty=0)


async def test_delete_type_empty_and_with_history(core):
    empty = await catalog.create_type(core, "test", {"lvl": 10, "barn": 1, "silo": 1, "price": "1"})
    r = await catalog.delete_type(core, "test", empty["id"])
    assert r == {"archived": False, "accounts_removed": 0}
    assert not await core.pool.fetchval("SELECT 1 FROM farm_types WHERE id=$1", empty["id"])
    t = await make_type(core, 4)
    await make_user(core, 1, "10")
    o = await orders.prepare(core, 1, t["id"], "10")
    await orders.purchase(core, 1, o["id"])
    r = await catalog.delete_type(core, "test", t["id"])
    assert r == {"archived": True, "accounts_removed": 3}
    assert await core.pool.fetchval("SELECT count(*) FROM farm_accounts WHERE type_id=$1", t["id"]) == 1  # sold kept
    assert (await orders.get_order(core, o["id"]))["status"] == "completed"
    assert not await catalog.list_types(core) and not await catalog.list_types(core, for_customers=True)
    _, login, _ = await orders.buyer_credentials(core, 1, o["id"])   # buyer still sees what he bought
    assert login == "farm70_0"
    with pytest.raises(StoreError):
        await catalog.update_type(core, "test", t["id"], {"is_active": True})


async def test_delete_type_refused_while_delivering(core):
    t = await make_type(core, 2)
    await make_user(core, 1, "10")
    o = await orders.prepare(core, 1, t["id"], "10")
    await orders._confirm(core, 1, o["id"])         # reserved, not yet delivered
    with pytest.raises(StoreError) as e:
        await catalog.delete_type(core, "test", t["id"])
    assert e.value.code == "busy"
