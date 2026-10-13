"""Dashboard numbers."""
from __future__ import annotations

from ..core import Core, rows


async def overview(core: Core) -> dict:
    p = core.pool
    sales = await p.fetchrow(
        "SELECT COUNT(*) FILTER (WHERE status='completed') AS completed, "
        "COALESCE(SUM(price) FILTER (WHERE status='completed'),0) AS revenue, "
        "COUNT(*) FILTER (WHERE status='completed' AND delivered_at >= date_trunc('day', now())) AS today_count, "
        "COALESCE(SUM(price) FILTER (WHERE status='completed' AND delivered_at >= date_trunc('day', now())),0) AS today_revenue, "
        "COALESCE(SUM(price) FILTER (WHERE status='completed' AND delivered_at >= now()-interval '30 days'),0) AS month_revenue, "
        "COUNT(*) FILTER (WHERE status='needs_review') AS needs_review, "
        "COUNT(*) FILTER (WHERE status='processing') AS processing "
        "FROM orders")
    dep = await p.fetchrow(
        "SELECT COALESCE(SUM(credited_amount) FILTER (WHERE status='approved'),0) AS total_deposited, "
        "COUNT(*) FILTER (WHERE status='under_review') AS pending_review, "
        "COALESCE(SUM(amount) FILTER (WHERE status='under_review'),0) AS pending_amount, "
        "COALESCE(SUM(credited_amount) FILTER (WHERE status='approved' AND reviewed_at >= date_trunc('day', now())),0) AS today_deposited "
        "FROM deposits")
    users = await p.fetchrow(
        "SELECT COUNT(*) AS users, COALESCE(SUM(balance),0) AS balances, "
        "COUNT(*) FILTER (WHERE balance>0) AS with_balance, "
        "COUNT(*) FILTER (WHERE created_at >= date_trunc('day', now())) AS new_today FROM users")
    stock = await p.fetchrow(
        "SELECT COUNT(*) FILTER (WHERE a.status='available' AND t.is_active) AS available, "
        "COUNT(*) FILTER (WHERE a.status='sold') AS sold, COUNT(*) FILTER (WHERE a.status='reserved') AS reserved, "
        "COUNT(*) FILTER (WHERE a.status='disabled') AS disabled, "
        "COALESCE(SUM(COALESCE(a.custom_price,t.price)) FILTER (WHERE a.status='available' AND t.is_active),0) AS stock_value "
        "FROM farm_accounts a JOIN farm_types t ON t.id=a.type_id")
    out_types = await p.fetchval(
        "SELECT COUNT(*) FROM farm_types t WHERE t.is_active AND NOT EXISTS "
        "(SELECT 1 FROM farm_accounts a WHERE a.type_id=t.id AND a.status='available')")
    adjustments = await p.fetchrow(
        "SELECT COALESCE(SUM(amount) FILTER (WHERE kind='admin_credit'),0) AS credits, "
        "COALESCE(-SUM(amount) FILTER (WHERE kind='admin_debit'),0) AS debits, "
        "COALESCE(SUM(amount) FILTER (WHERE kind='refund'),0) AS refunds FROM wallet_transactions")
    unread = await p.fetchval("SELECT COUNT(*) FROM alerts WHERE NOT is_read")
    return {"sales": dict(sales), "deposits": dict(dep), "users": dict(users), "stock": dict(stock),
            "out_of_stock_types": out_types, "adjustments": dict(adjustments), "unread_alerts": unread}


async def daily(core: Core, days: int = 30) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT d::date AS day, "
        "COALESCE((SELECT SUM(price) FROM orders o WHERE o.status='completed' AND o.delivered_at::date = d::date),0) AS revenue, "
        "(SELECT COUNT(*) FROM orders o WHERE o.status='completed' AND o.delivered_at::date = d::date) AS sales, "
        "COALESCE((SELECT SUM(credited_amount) FROM deposits x WHERE x.status='approved' AND x.reviewed_at::date = d::date),0) AS deposits "
        "FROM generate_series(current_date - ($1::int - 1), current_date, interval '1 day') d ORDER BY d", days))


async def top_types(core: Core, limit: int = 10) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT t.id, t.name, t.lvl, COUNT(o.id) AS sales, COALESCE(SUM(o.price),0) AS revenue "
        "FROM farm_types t JOIN orders o ON o.type_id=t.id AND o.status='completed' "
        "GROUP BY t.id ORDER BY revenue DESC LIMIT $1", limit))
