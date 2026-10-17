"""Simple per-user token bucket to keep the bot responsive under flood."""

from __future__ import annotations

import contextlib
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.i18n import i18n


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._warned: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)
        cfg: Settings = data["cfg"]
        if tg_user.id in cfg.admins:
            return await handler(event, data)
        is_callback = isinstance(event, CallbackQuery)
        is_message = isinstance(event, Message)
        if not (is_callback or is_message):
            return await handler(event, data)
        limit = cfg.throttle_callbacks if is_callback else cfg.throttle_messages
        window = max(1, cfg.throttle_window)
        now = time.monotonic()
        bucket = self._hits[tg_user.id]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            if now - self._warned.get(tg_user.id, 0) > 15:
                self._warned[tg_user.id] = now
                lang = (data.get("user").language if data.get("user") else None) or "fa"
                text = i18n.get(lang, "access.throttle")
                with contextlib.suppress(Exception):
                    if is_callback:
                        await event.answer(text, show_alert=False)
                    else:
                        await event.answer(text)
            return None
        bucket.append(now)
        if len(self._hits) > 5000:
            self._prune(now, window)
        return await handler(event, data)

    def _prune(self, now: float, window: int) -> None:
        stale = [key for key, bucket in self._hits.items() if not bucket or now - bucket[-1] > window * 4]
        for key in stale:
            self._hits.pop(key, None)
            self._warned.pop(key, None)
