"""Bot / dispatcher assembly."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from ..core import Core, StoreError
from . import admin, customer
from .messenger import TelegramMessenger
from .middlewares import UserMiddleware

log = logging.getLogger(__name__)


def create_bot(token: str, **kwargs) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
               **kwargs)


def create_dispatcher(core: Core, throttle: float = 0.35) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    mw = UserMiddleware(core, throttle)
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    for r in (admin.router, customer.router):
        r._parent_router = None          # allow re-creating the dispatcher (tests, restarts)
    dp.include_router(admin.router)      # admin first: its states/buttons win
    dp.include_router(customer.router)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        exc = event.exception
        upd = event.update
        if isinstance(exc, StoreError):
            msg = f"⚠️ {exc.message}"
        else:
            log.exception("unhandled error", exc_info=exc)
            msg = "⚠️ حدث خطأ غير متوقع. حاول مرة أخرى أو تواصل مع الدعم."
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
    await bot.set_my_commands([
        BotCommand(command="start", description="القائمة الرئيسية"),
        BotCommand(command="cancel", description="إلغاء العملية الحالية"),
    ])
