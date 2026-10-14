"""PostgreSQL connection pool and migration runner."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(dsn: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    # Railway gives postgres:// URLs; asyncpg accepts both schemes.
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, init=_init_conn,
                                     command_timeout=60)


async def reset_old_schema(pool: asyncpg.Pool) -> bool:
    """One-time wipe of the previous (menu-based) store when RESET_DB=true.

    Only runs if the old schema is detected (wallet_transactions table), so leaving RESET_DB on is harmless.
    """
    async with pool.acquire() as conn:
        old = await conn.fetchval("SELECT to_regclass('public.wallet_transactions') IS NOT NULL")
        if not old:
            return False
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        log.warning("RESET_DB: previous store schema and all its data were dropped")
        return True


async def migrate(pool: asyncpg.Pool) -> list[str]:
    """Apply every migrations/*.sql file not yet applied, in order, each in a transaction."""
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        # serialize concurrent starters (bot + api replicas)
        await conn.execute("SELECT pg_advisory_lock(727001)")
        try:
            done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                async with conn.transaction():
                    await conn.execute(path.read_text(encoding="utf-8"))
                    await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", path.name)
                applied.append(path.name)
                log.info("applied migration %s", path.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(727001)")
    return applied
