"""User registration, bans, maintenance mode and daily quota reset."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.db.repository import Repository
from bot.i18n import i18n
from bot.utils.time import today_key

BANNED_NOTICE_INTERVAL = 3600
MAINTENANCE_CACHE_TTL = 20


class UserMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._notice: dict[int, float] = {}
        self._maintenance_cache: tuple[float, bool] | None = None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        repo: Repository = data["repo"]
        cfg: Settings = data["cfg"]

        user = await repo.upsert_user(
            tg_user.id,
            tg_user.username,
            tg_user.first_name or tg_user.full_name or str(tg_user.id),
            language=None,
        )
        await repo.reset_daily(user.id)
        if user.usage_date != today_key():
            refreshed = await repo.get_user(user.id)
            if refreshed is not None:
                user = refreshed
        data["user"] = user
        is_admin = tg_user.id in cfg.admins
        data["is_admin"] = is_admin

        if user.is_banned and not is_admin:
            now = time.monotonic()
            if now - self._notice.get(user.id, 0) > BANNED_NOTICE_INTERVAL:
                self._notice[user.id] = now
                text = i18n.get(user.language, "access.banned")
                if isinstance(event, Message):
                    with contextlib.suppress(Exception):
                        await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    with contextlib.suppress(Exception):
                        await event.answer(text, show_alert=True)
            return None

        maintenance = await self._maintenance(repo)
        if maintenance and not is_admin:
            text = i18n.get(user.language, "access.maintenance")
            if isinstance(event, Message):
                with contextlib.suppress(Exception):
                    await event.answer(text)
            elif isinstance(event, CallbackQuery):
                with contextlib.suppress(Exception):
                    await event.answer(text, show_alert=True)
            return None

        return await handler(event, data)

    async def _maintenance(self, repo: Repository) -> bool:
        now = time.monotonic()
        if self._maintenance_cache and now - self._maintenance_cache[0] < MAINTENANCE_CACHE_TTL:
            return self._maintenance_cache[1]
        value = await repo.get_bool_setting("maintenance", False)
        self._maintenance_cache = (now, value)
        return value

    def invalidate(self) -> None:
        self._maintenance_cache = None
