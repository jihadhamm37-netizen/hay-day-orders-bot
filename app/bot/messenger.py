"""Telegram implementation of the Messenger protocol used by the services."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from ..core import Core
from ..services.admins import admin_recipients
from .ui import btn, credentials_kb, credentials_text, kb

log = logging.getLogger(__name__)


def deposit_review_kb(deposit_id: int):
    return kb(
        [btn("✅ قبول", f"a:da:{deposit_id}"), btn("❌ رفض", f"a:dr:{deposit_id}")],
        [btn("✏️ قبول بمبلغ مختلف", f"a:dam:{deposit_id}")],
    )


class TelegramMessenger:
    def __init__(self, bot: Bot, core: Core):
        self.bot = bot
        self.core = core

    async def send_credentials(self, user_id: int, order: dict, login: str, password: str) -> None:
        # Exceptions propagate on purpose: the order must not be marked delivered if this fails.
        await self.bot.send_message(user_id, credentials_text(order, login, password),
                                    reply_markup=credentials_kb(login, password))

    async def notify_user(self, user_id: int, text: str) -> bool:
        try:
            await self.bot.send_message(user_id, text)
            return True
        except TelegramForbiddenError:
            return False
        except TelegramAPIError as e:
            log.warning("notify_user %s failed: %s", user_id, e)
            return False

    async def notify_admins(self, text: str, *, perm: str = "view", photo: str | None = None,
                            reply_markup: Any = None) -> None:
        if isinstance(reply_markup, tuple) and reply_markup[0] == "deposit_review":
            reply_markup = deposit_review_kb(reply_markup[1])
        for admin_id in await admin_recipients(self.core, perm):
            try:
                if photo:
                    await self.bot.send_photo(admin_id, photo, caption=text[:1024], reply_markup=reply_markup)
                else:
                    await self.bot.send_message(admin_id, text, reply_markup=reply_markup)
            except TelegramAPIError as e:
                log.warning("notify admin %s failed: %s", admin_id, e)

    async def send_admin_code(self, telegram_id: int, code: str) -> bool:
        try:
            await self.bot.send_message(
                telegram_id,
                f"🔐 رمز الدخول إلى لوحة التحكم: <code>{code}</code>\nصالح لمدة 5 دقائق. "
                "إذا لم تطلبه فغيّر كلمة المرور فوراً.")
            return True
        except TelegramAPIError as e:
            log.warning("admin code to %s failed: %s", telegram_id, e)
            return False
