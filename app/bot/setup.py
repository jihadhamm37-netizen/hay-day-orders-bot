"""Bot / dispatcher assembly."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, Message, TelegramObject

from ..core import Core, StoreError
from ..services import customers as cust_svc
from ..services.admins import telegram_role
from . import admin_tg, handlers
from .messenger import TelegramMessenger
from .texts import tt

log = logging.getLogger(__name__)


class CustomerMiddleware(BaseMiddleware):
    def __init__(self, core: Core, throttle: float = 0.5):
        self.core, self.throttle = core, throttle
        self._last: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
        if user is None or user.is_bot or (chat is not None and chat.type != "private"):
            return None
        if isinstance(event, Message) and self.throttle:
            now = time.monotonic()
            if now - self._last.get(user.id, 0) < self.throttle:
                return None
            self._last[user.id] = now
            if len(self._last) > 50_000:
                self._last.clear()
        guess = "ar" if (user.language_code or "ar").lower().startswith("ar") else "en"
        customer = await cust_svc.touch(self.core, user.id, user.username, user.first_name, guess)
        lang = customer["lang"]
        if isinstance(event, Message) and event.text and not event.text.startswith("/"):
            detected = cust_svc.detect_lang(event.text)
            if detected and detected != lang:
                await cust_svc.set_lang(self.core, user.id, detected)
                lang = detected
        role = await telegram_role(self.core, user.id)
        if customer["is_banned"] and not role:
            if isinstance(event, Message):
                await event.answer(tt(lang, "banned"))
            return None
        data.update(core=self.core, customer=customer, lang=lang, role=role)
        return await handler(event, data)


def create_bot(token: str, **kwargs) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True), **kwargs)


def create_dispatcher(core: Core, throttle: float = 0.5) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    mw = CustomerMiddleware(core, throttle)
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    for r in (admin_tg.router, handlers.router):
        r._parent_router = None
    dp.include_router(admin_tg.router)
    dp.include_router(handlers.router)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        exc, upd = event.exception, event.update
        msg = exc.message if isinstance(exc, StoreError) else "حدث خطأ غير متوقع، حاول مرة أخرى."
        if not isinstance(exc, StoreError):
            log.exception("unhandled error", exc_info=exc)
        try:
            if upd.callback_query:
                await upd.callback_query.answer(msg[:200], show_alert=True)
            elif upd.message:
                await upd.message.answer(msg)
        except Exception:
            pass
        return True

    return dp


def attach_messenger(core: Core, bot: Bot) -> None:
    core.messenger = TelegramMessenger(bot, core)


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands([BotCommand(command="start", description="Start / البداية")])
