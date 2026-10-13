"""Telegram implementation of the Messenger protocol used by the services."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from ..core import Core
from ..i18n import render
from ..services.admins import admin_recipients
from .ui import btn, credentials_batch_messages, credentials_kb, credentials_text, kb

log = logging.getLogger(__name__)


def deposit_review_kb(deposit_id: int):
    return kb(
        [btn("✅ قبول", f"a:da:{deposit_id}", "success"), btn("❌ رفض", f"a:dr:{deposit_id}", "danger")],
        [btn("✏️ قبول بمبلغ مختلف", f"a:dam:{deposit_id}")],
    )


class TelegramMessenger:
    def __init__(self, bot: Bot, core: Core):
        self.bot = bot
        self.core = core

    async def user_lang(self, user_id: int) -> str:
        return await self.core.pool.fetchval("SELECT lang FROM users WHERE id=$1", user_id) or "ar"

    async def send_credentials(self, user_id: int, order: dict, login: str, password: str) -> None:
        # Exceptions propagate on purpose: the order must not be marked delivered if this fails.
        lang = await self.user_lang(user_id)
        text = credentials_text(order, login, password, lang)
        markup = credentials_kb(login, password, lang)
        photo = order.get("photo")
        if photo:
            try:
                await self.bot.send_photo(user_id, photo, caption=text, reply_markup=markup)
                return
            except TelegramForbiddenError:
                raise
            except TelegramAPIError as e:  # bad/expired file id → fall back to plain text
                log.warning("credentials photo failed (%s), sending text", e)
        await self.bot.send_message(user_id, text, reply_markup=markup)

    async def send_credentials_batch(self, user_id: int, items: list[tuple[dict, str, str]]) -> None:
        """All accounts of one purchase in a single copyable list. Raises if Telegram refuses (not delivered)."""
        lang = await self.user_lang(user_id)
        photo = items[0][0].get("photo")
        if photo:  # decorative only — failure here does not matter
            try:
                await self.bot.send_photo(user_id, photo)
            except TelegramForbiddenError:
                raise
            except TelegramAPIError:
                pass
        for text, markup in credentials_batch_messages(items, lang):
            await self.bot.send_message(user_id, text, reply_markup=markup)

    async def notify_user(self, user_id: int, text: str | None = None, *, key: str | None = None,
                          **params) -> bool:
        try:
            if key:
                text = render(await self.user_lang(user_id), key, params)
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

    async def upload_photo(self, chat_id: int, data: bytes, filename: str = "farm.jpg") -> str:
        """Upload an image once to get a reusable Telegram file_id (used by the web panel)."""
        from aiogram.types import BufferedInputFile
        msg = await self.bot.send_photo(chat_id, BufferedInputFile(data, filename),
                                        caption="🖼 تم رفع الصورة من لوحة التحكم", disable_notification=True)
        return msg.photo[-1].file_id
