"""Reports: sales, revenue, profit, stock and activity."""
from __future__ import annotations

from ..core import Core, rows


async def overview(core: Core) -> dict:
    p = core.pool
    sales = rows(await p.fetch(
        "SELECT o.currency, count(DISTINCT o.id) AS orders, coalesce(sum(i.price),0) AS revenue, "
        "coalesce(sum(i.price - coalesce(i.cost, 0)),0) AS profit, count(i.id) AS farms, "
        "coalesce(sum(i.price) FILTER (WHERE o.delivered_at >= date_trunc('day', now())),0) AS today, "
        "coalesce(sum(i.price) FILTER (WHERE o.delivered_at >= now() - interval '30 days'),0) AS month, "
        "count(i.id) FILTER (WHERE i.cost IS NULL) AS farms_without_cost "
        "FROM orders o JOIN order_items i ON i.order_id=o.id AND i.active WHERE o.status='delivered' GROUP BY o.currency"))
    by_status = {r["status"]: r["n"] for r in await p.fetch("SELECT status, count(*) AS n FROM orders GROUP BY status")}
    stock = dict(await p.fetchrow(
        "SELECT count(*) FILTER (WHERE status='available') AS available, count(*) FILTER (WHERE status='reserved') AS reserved, "
        "count(*) FILTER (WHERE status='sold') AS sold, count(*) FILTER (WHERE status='disabled') AS disabled FROM farms"))
    cust = dict(await p.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE created_at >= date_trunc('day', now())) AS new_today, "
        "count(*) FILTER (WHERE ai_paused) AS taken_over, "
        "count(*) FILTER (WHERE last_message_at >= now() - interval '24 hours') AS active_24h FROM customers"))
    pending_payments = await p.fetchval("SELECT count(*) FROM payments WHERE status='pending'")
    unread = await p.fetchval("SELECT count(*) FROM alerts WHERE NOT is_read")
    return {"sales": sales, "orders_by_status": by_status, "stock": stock, "customers": cust,
            "pending_payments": pending_payments, "unread_alerts": unread}


async def daily(core: Core, days: int = 30) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT d::date AS day, "
        "coalesce((SELECT sum(i.price) FROM orders o JOIN order_items i ON i.order_id=o.id AND i.active "
        "  WHERE o.status='delivered' AND o.delivered_at::date = d::date),0) AS revenue, "
        "coalesce((SELECT sum(i.price - coalesce(i.cost,0)) FROM orders o JOIN order_items i ON i.order_id=o.id AND i.active "
        "  WHERE o.status='delivered' AND o.delivered_at::date = d::date),0) AS profit, "
        "(SELECT count(*) FROM orders o WHERE o.status='delivered' AND o.delivered_at::date = d::date) AS orders "
        "FROM generate_series(current_date - ($1::int - 1), current_date, interval '1 day') d ORDER BY d", days))


async def top_levels(core: Core, limit: int = 10) -> list[dict]:
    return rows(await core.pool.fetch(
        "SELECT (o.offer->>'lvl')::int AS lvl, count(i.id) AS farms, sum(i.price) AS revenue, o.currency "
        "FROM orders o JOIN order_items i ON i.order_id=o.id AND i.active WHERE o.status='delivered' "
        "GROUP BY 1, o.currency ORDER BY revenue DESC LIMIT $1", limit))
