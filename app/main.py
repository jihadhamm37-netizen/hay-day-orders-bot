"""Entry point: HD Agent — customer app API + web app, admin panel and background jobs in one process."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import uvicorn

from .api.server import create_app
from .messenger import AppMessenger
from .config import Config
from .core import Core, StoreError
from .db import create_pool, migrate
from .security import Vault, verify_password
from .services import admins, backup, orders, system

log = logging.getLogger("app")


async def ensure_owner(core: Core) -> None:
    """OWNER_USERNAME/OWNER_PASSWORD env vars: create that owner, or reset its password and unlock it.
    Meant to be set once (e.g. a forgotten password) and removed afterwards."""
    user = os.environ.get("OWNER_USERNAME", "").strip().lower()
    pw = os.environ.get("OWNER_PASSWORD", "").strip()
    if not user or not pw:
        return
    a = await core.pool.fetchrow("SELECT * FROM admins WHERE username=$1", user)
    try:
        if not a:
            await admins.create_admin(core, "system", user, pw, "owner")
            log.info("owner '%s' created from OWNER_* env vars", user)
            return
        if verify_password(pw, a["password_hash"]) and a["role"] == "owner" and a["is_active"]:
            return
        await admins.update_admin(core, "system", a["id"], {"password": pw, "role": "owner", "is_active": True})
        await core.pool.execute("UPDATE admins SET failed_logins=0, locked_until=NULL WHERE id=$1", a["id"])
        log.info("owner '%s' password reset from OWNER_* env vars", user)
    except StoreError as e:
        log.error("cannot set owner '%s': %s", user, e.message)


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


async def jobs(core: Core) -> None:
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
                    await backup.make_backup(core)
                except StoreError as e:
                    await system.raise_alert(core, "error", "backup_failed", e.message, perm="backup")
                except Exception as e:
                    log.exception("backup job failed")
                    await system.raise_alert(core, "error", "backup_failed", f"فشل النسخ الاحتياطي: {e}", perm="backup")
        except Exception:
            log.exception("maintenance job failed")
        await asyncio.sleep(30)


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    pool = await create_pool(cfg.database_url)
    applied = await migrate(pool)
    if applied:
        log.info("migrations applied: %s", applied)
    core = Core(pool, Vault(cfg.encryption_key), cfg)
    core.messenger = AppMessenger(core)
    await bootstrap_admin(core)
    await ensure_owner(core)
    server = uvicorn.Server(uvicorn.Config(create_app(core), host="0.0.0.0", port=cfg.port,
                                           proxy_headers=True, forwarded_allow_ips="*", log_level="info"))
    log.info("HD Agent at %s — admin panel at %s", cfg.public_url or f"http://localhost:{cfg.port}", cfg.panel_path)
    try:
        await asyncio.gather(server.serve(), jobs(core))
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
