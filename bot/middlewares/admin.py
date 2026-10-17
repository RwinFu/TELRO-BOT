"""Router-level guard that only lets configured admins through."""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.i18n import i18n


class AdminGuard(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        cfg: Settings = data["cfg"]
        tg_user = data.get("event_from_user")
        if tg_user is not None and tg_user.id in cfg.admins:
            return await handler(event, data)
        lang = (data.get("user").language if data.get("user") else None) or "fa"
        text = i18n.get(lang, "access.admin_only")
        with contextlib.suppress(Exception):
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        return None
