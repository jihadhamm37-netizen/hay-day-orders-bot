"""Registers the user on every update, injects the role and blocks banned users."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..core import Core
from ..services.admins import telegram_role
from ..services.wallet import touch_user


class UserMiddleware(BaseMiddleware):
    def __init__(self, core: Core, throttle: float = 0.35):
        self.core = core
        self.throttle = throttle
        self._last: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
        if user is None or user.is_bot or (chat is not None and chat.type != "private"):
            return None  # the store works in private chats only
        # basic flood protection for messages (callbacks are protected by DB guards)
        if isinstance(event, Message) and self.throttle:
            now = time.monotonic()
            if now - self._last.get(user.id, 0) < self.throttle:
                return None
            self._last[user.id] = now
            if len(self._last) > 50_000:
                self._last.clear()
        db_user = await touch_user(self.core, user.id, user.username, user.first_name)
        role = await telegram_role(self.core, user.id)
        if db_user["is_banned"] and not role:
            if isinstance(event, CallbackQuery):
                await event.answer("حسابك موقوف. تواصل مع الدعم.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔️ حسابك موقوف. تواصل مع الدعم الفني.")
            return None
        data["core"] = self.core
        data["db_user"] = db_user
        data["role"] = role
        return await handler(event, data)
