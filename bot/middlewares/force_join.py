"""Optional forced channel membership with a short in-memory cache."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.db.repository import User
from bot.i18n import i18n
from bot.keyboards.inline import force_join_required

log = logging.getLogger(__name__)

CACHE_TTL = 300


class ForceJoinMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._cache: dict[tuple[int, str], tuple[float, bool]] = {}
        self._broken: set[str] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        cfg: Settings = data["cfg"]
        channels = cfg.join_channels
        if not channels:
            return await handler(event, data)
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data in {"join:check"}:
            return await handler(event, data)
        if isinstance(event, Message) and event.text and event.text.startswith(("/start", "/help")):
            return await handler(event, data)
        user: User | None = data.get("user")
        tg_user = data.get("event_from_user")
        if user is None or tg_user is None:
            return await handler(event, data)
        if tg_user.id in cfg.admins:
            return await handler(event, data)

        missing: list[str] = []
        for channel in channels:
            if await self._is_member(data["bot"], tg_user.id, channel):
                continue
            missing.append(channel)
        if not missing:
            return await handler(event, data)

        lang = user.language
        text = f"{i18n.get(lang, 'join.title')}\n\n{i18n.get(lang, 'join.body')}"
        keyboard = force_join_required(lang, channels)
        with contextlib.suppress(Exception):
            if isinstance(event, Message):
                await event.answer(text, reply_markup=keyboard)
            else:
                await event.answer(i18n.get(lang, "join.not_member"), show_alert=True)
        return None

    async def _is_member(self, bot: Bot, user_id: int, channel: str) -> bool:
        now = time.monotonic()
        cached = self._cache.get((user_id, channel))
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]
        if channel in self._broken:
            return True
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        except TelegramBadRequest as exc:
            log.warning("Force-join check failed for %s: %s", channel, exc)
            self._broken.add(channel)
            return True
        except Exception as exc:  # network issues should never lock users out
            log.warning("Force-join network error for %s: %s", channel, exc)
            return True
        status = getattr(member, "status", "")
        is_member = str(status) in {
            "ChatMemberStatus.MEMBER",
            "ChatMemberStatus.ADMINISTRATOR",
            "ChatMemberStatus.CREATOR",
            "member",
            "administrator",
            "creator",
        }
        self._cache[(user_id, channel)] = (now, is_member)
        return is_member
