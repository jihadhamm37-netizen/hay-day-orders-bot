"""Runtime configuration — everything secret comes from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return out


def _bool(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    bot_token: str
    database_url: str
    encryption_key: str               # Fernet key (urlsafe base64, 32 bytes)
    jwt_secret: str
    owner_ids: set[int] = field(default_factory=set)   # Telegram IDs with full rights
    setup_code: str = ""              # one-time /claim code that links the first owner's Telegram
    panel_path: str = "/panel"        # secret URL path of the web dashboard
    public_url: str = ""
    port: int = 8080
    mode: str = "all"                 # all | bot | api
    cookie_secure: bool = True
    session_hours: int = 12
    require_tg_code: bool = False     # web login: 2nd factor sent through the bot
    anthropic_api_key: str = ""
    ai_model: str = "claude-haiku-5-5"
    anthropic_workspace_id: str = ""
    notify_bot_token: str = ""          # optional send-only Telegram bot for staff notifications
    reset_db: bool = False
    backup_dir: str = "/tmp/backups"
    backup_every_hours: int = 24
    backup_to_telegram: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        def need(name: str) -> str:
            v = os.environ.get(name, "").strip()
            if not v:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return v

        mode = os.environ.get("MODE", "all").strip().lower()
        if mode in ("all", "api") and len(os.environ.get("JWT_SECRET", "")) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 random characters (run: python -m scripts.gen_keys)")
        panel = os.environ.get("ADMIN_PANEL_PATH", "/panel").strip() or "/panel"
        if not panel.startswith("/"):
            panel = "/" + panel
        return cls(
            bot_token="",
            database_url=need("DATABASE_URL"),
            encryption_key=need("ENCRYPTION_KEY"),
            jwt_secret=need("JWT_SECRET") if mode in ("all", "api") else os.environ.get("JWT_SECRET", "x"),
            owner_ids=_ids(os.environ.get("OWNER_TELEGRAM_IDS", "")),
            setup_code=os.environ.get("SETUP_CODE", "").strip(),
            panel_path=panel.rstrip("/") or "/panel",
            public_url=os.environ.get("PUBLIC_URL", "").rstrip("/"),
            port=int(os.environ.get("PORT", "8080")),
            mode=mode,
            cookie_secure=_bool(os.environ.get("COOKIE_SECURE"), True),
            session_hours=int(os.environ.get("SESSION_HOURS", "12")),
            require_tg_code=_bool(os.environ.get("REQUIRE_TELEGRAM_CODE"), False),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            ai_model=os.environ.get("AI_MODEL", "claude-haiku-5-5").strip() or "claude-haiku-5-5",
            notify_bot_token=os.environ.get("NOTIFY_BOT_TOKEN", "").strip(),
            anthropic_workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip(),
            reset_db=_bool(os.environ.get("RESET_DB"), False),
            backup_dir=os.environ.get("BACKUP_DIR", "/tmp/backups"),
            backup_every_hours=int(os.environ.get("BACKUP_EVERY_HOURS", "24")),
            backup_to_telegram=_bool(os.environ.get("BACKUP_TO_TELEGRAM"), True),
        )
