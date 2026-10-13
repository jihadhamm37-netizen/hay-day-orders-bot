"""Database backups with pg_dump (custom format, compressed)."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..core import Core, StoreError

log = logging.getLogger(__name__)
KEEP = 14


async def make_backup(core: Core) -> Path:
    if not shutil.which("pg_dump"):
        raise StoreError("no_pg_dump", "أداة pg_dump غير مثبتة على الخادم.")
    folder = Path(core.config.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"hayday-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.dump"
    path = folder / name
    dsn = core.config.database_url
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(path), dsn,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        path.unlink(missing_ok=True)
        raise StoreError("backup_failed", f"فشل النسخ الاحتياطي: {err.decode(errors='ignore')[:300]}")
    old = sorted(folder.glob("hayday-*.dump"))[:-KEEP]
    for f in old:
        f.unlink(missing_ok=True)
    log.info("backup created %s (%d bytes)", path, os.path.getsize(path))
    return path


def list_backups(core: Core) -> list[dict]:
    folder = Path(core.config.backup_dir)
    if not folder.exists():
        return []
    return [{"name": f.name, "size": f.stat().st_size,
             "created_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()}
            for f in sorted(folder.glob("hayday-*.dump"), reverse=True)]


def backup_path(core: Core, name: str) -> Path:
    if "/" in name or "\\" in name or not name.startswith("hayday-") or not name.endswith(".dump"):
        raise StoreError("bad_input", "اسم ملف غير صالح.")
    p = Path(core.config.backup_dir) / name
    if not p.exists():
        raise StoreError("not_found", "الملف غير موجود.")
    return p
