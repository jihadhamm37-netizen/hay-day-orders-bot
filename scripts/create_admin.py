"""Create or reset a web-panel admin from the server shell.

    python -m scripts.create_admin USERNAME --role owner --telegram-id 123456789
    python -m scripts.create_admin USERNAME --reset-password
"""
import argparse
import asyncio
import getpass
import os

from app.core import Core, StoreError
from app.config import Config
from app.db import create_pool, migrate
from app.security import Vault
from app.services import admins


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("username")
    p.add_argument("--role", default="owner", choices=list(admins.ROLES))
    p.add_argument("--telegram-id", type=int)
    p.add_argument("--reset-password", action="store_true")
    a = p.parse_args()
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    dsn = os.environ["DATABASE_URL"]
    pool = await create_pool(dsn)
    await migrate(pool)
    core = Core(pool, Vault(os.environ["ENCRYPTION_KEY"]),
                Config(bot_token="", database_url=dsn, encryption_key=os.environ["ENCRYPTION_KEY"],
                       jwt_secret=os.environ.get("JWT_SECRET", "x")))
    try:
        if a.reset_password:
            aid = await pool.fetchval("SELECT id FROM admins WHERE username=$1", a.username.lower())
            if not aid:
                raise StoreError("not_found", "admin not found")
            await admins.update_admin(core, "cli", aid, {"password": pw, "is_active": True})
            print("password reset, account unlocked")
        else:
            r = await admins.create_admin(core, "cli", a.username, pw, a.role, a.telegram_id)
            print(f"created admin #{r['id']} {r['username']} ({r['role']})")
    except StoreError as e:
        print("error:", e.message)
    await pool.close()


asyncio.run(main())
