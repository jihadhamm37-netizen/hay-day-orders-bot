"""Shared application context used by both the bot and the API."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol

import asyncpg

from .config import Config
from .security import Vault

log = logging.getLogger(__name__)


class StoreError(Exception):
    """Business-rule failure with an Arabic message safe to show to the user."""

    def __init__(self, code: str, message: str, **params):
        super().__init__(message)
        self.code = code
        self.message = message
        self.params = params


class Messenger(Protocol):
    """Implemented by the bot layer — everything that talks to Telegram."""

    async def send_credentials(self, user_id: int, order: dict, login: str, password: str) -> None: ...
    async def notify_user(self, user_id: int, text: str | None = None, *, key: str | None = None,
                          **params) -> bool: ...
    async def notify_admins(self, text: str, *, perm: str = "view", photo: str | None = None,
                            reply_markup: Any = None) -> None: ...
    async def send_admin_code(self, telegram_id: int, code: str) -> bool: ...


@dataclass
class Core:
    pool: asyncpg.Pool
    vault: Vault
    config: Config
    messenger: Messenger | None = None
    _settings_cache: dict = field(default_factory=dict)


# ------------------------------------------------------------------ money
CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Parse a positive or negative USDT amount with at most 2 decimals."""
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise StoreError("bad_amount", "المبلغ غير صالح.")
    if not d.is_finite():
        raise StoreError("bad_amount", "المبلغ غير صالح.")
    q = d.quantize(CENT, rounding=ROUND_HALF_UP)
    if q != d:
        raise StoreError("bad_amount", "المبلغ يقبل منزلتين عشريتين كحد أقصى.")
    if abs(q) > Decimal("1000000"):
        raise StoreError("bad_amount", "المبلغ كبير جداً.")
    return q


def fmt(amount: Any) -> str:
    d = Decimal(amount).quantize(CENT)
    s = f"{d:,.2f}"
    return s


def row(r: asyncpg.Record | None) -> dict | None:
    return dict(r) if r is not None else None


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]
