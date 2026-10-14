"""Entry point: runs the Telegram bot, the API/web panel and background jobs.

    python -m app            # MODE=all (default) — bot + API in one process
    MODE=bot python -m app   # bot + background jobs only
    MODE=api python -m app   # API + web panel only
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import uvicorn
from aiogram.types import FSInputFile

from .api.server import create_app
from .bot.setup import attach_messenger, create_bot, create_dispatcher, set_commands
from .config import Config
from .core import Core, StoreError
from .db import create_pool, migrate, reset_old_schema
from .security import Vault
from .services import admins, backup, orders, system

log = logging.getLogger("app")


async def bootstrap_admin(core: Core) -> None:
    """Create the first web owner from INITIAL_ADMIN_* env vars when no admin exists yet."""
    if await core.pool.fetchval("SELECT count(*) FROM admins"):
        return
    user = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
    pw = os.environ.get("INITIAL_ADMIN_PASSWORD", "").strip()
    if not user or not pw:
        log.warning("No web admin exists. Set INITIAL_ADMIN_USERNAME/INITIAL_ADMIN_PASSWORD "
                    "or run: python -m scripts.create_admin")
        return
    tid = os.environ.get("INITIAL_ADMIN_TELEGRAM_ID", "").strip() or None
    if tid is None and core.config.owner_ids:
        tid = str(sorted(core.config.owner_ids)[0])
    try:
        await admins.create_admin(core, "system", user, pw, "owner", int(tid) if tid else None)
        log.info("initial owner '%s' created", user)
    except StoreError as e:
        log.error("cannot create initial admin: %s", e.message)


async def jobs(core: Core, bot) -> None:
    last_backup = None
    while True:
        try:
            await orders.maintenance(core)
            await core.pool.execute("DELETE FROM login_codes WHERE expires_at < now() - interval '1 day'")
            due = core.config.backup_every_hours > 0 and (
                last_backup is None or
                (datetime.now(timezone.utc) - last_backup).total_seconds() >= core.config.backup_every_hours * 3600)
            if due:
                last_backup = datetime.now(timezone.utc)
                try:
                    path = await backup.make_backup(core)
                    if core.config.backup_to_telegram:
                        for owner in sorted(core.config.owner_ids):
                            await bot.send_document(owner, FSInputFile(path),
                                                    caption=f"نسخة احتياطية تلقائية: {path.name}")
                except StoreError as e:
                    await system.raise_alert(core, "error", "backup_failed", e.message, perm="backup")
                except Exception as e:
                    log.exception("backup job failed")
                    await system.raise_alert(core, "error", "backup_failed", f"فشل النسخ الاحتياطي: {e}",
                                             perm="backup")
        except Exception:
            log.exception("maintenance job failed")
        await asyncio.sleep(30)


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    pool = await create_pool(cfg.database_url)
    if cfg.reset_db and await reset_old_schema(pool):
        log.warning("old store wiped (RESET_DB). Remove RESET_DB from the environment.")
    applied = await migrate(pool)
    if applied:
        log.info("migrations applied: %s", applied)
    core = Core(pool, Vault(cfg.encryption_key), cfg)
    await bootstrap_admin(core)
    bot = create_bot(cfg.bot_token)
    attach_messenger(core, bot)

    tasks = []
    if cfg.mode in ("all", "bot"):
        dp = create_dispatcher(core)
        await set_commands(bot)
        await bot.delete_webhook(drop_pending_updates=False)
        tasks.append(dp.start_polling(bot, handle_signals=False,
                                      allowed_updates=dp.resolve_used_update_types()))
        tasks.append(jobs(core, bot))
        me = await bot.get_me()
        log.info("bot @%s started", me.username)
    if cfg.mode in ("all", "api"):
        server = uvicorn.Server(uvicorn.Config(create_app(core, bot), host="0.0.0.0", port=cfg.port,
                                               proxy_headers=True, forwarded_allow_ips="*", log_level="info"))
        tasks.append(server.serve())
        log.info("admin panel at %s%s", cfg.public_url or f"http://localhost:{cfg.port}", cfg.panel_path)
    try:
        await asyncio.gather(*tasks)
    finally:
        await bot.session.close()
        await pool.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
