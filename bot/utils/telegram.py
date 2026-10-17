"""Small helpers around aiogram objects."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from collections.abc import Iterable, Sequence
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.constants import TG_CAPTION_LIMIT, TG_TEXT_LIMIT
from bot.utils.text import split_html

log = logging.getLogger(__name__)


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    disable_preview: bool = True,
) -> bool:
    """Edit a message whether it has text or a caption. Never raises."""
    if not text:
        return False
    if message.photo or message.video or message.animation or message.document:
        text = text[:TG_CAPTION_LIMIT]
        try:
            await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return True
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return True
            if "no caption" in str(exc).lower() or "there is no caption" in str(exc).lower():
                pass
            else:
                log.debug("edit_caption failed: %s", exc)
        except TelegramForbiddenError:
            return False
    try:
        await message.edit_text(
            text=text[:TG_TEXT_LIMIT],
            reply_markup=reply_markup,
            parse_mode="HTML",
            link_preview_options={"is_disabled": disable_preview},
        )
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        return await safe_edit(message, text, reply_markup, disable_preview=disable_preview)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return True
        log.debug("edit_text failed: %s", exc)
        return False
    except TelegramForbiddenError:
        return False


async def answer_callback(callback: CallbackQuery, text: str | None = None, *, alert: bool = False) -> None:
    with contextlib.suppress(Exception):
        await callback.answer(text=text, show_alert=alert)


async def safe_delete(message: Message | None) -> None:
    if message is None:
        return
    with contextlib.suppress(Exception):
        await message.delete()


async def send_long(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_preview: bool = True,
) -> list[Message]:
    """Send markdown-ish text split over several messages."""
    chunks = split_html(text)
    sent: list[Message] = []
    for index, chunk in enumerate(chunks):
        sent.append(
            await message.answer(
                chunk,
                reply_markup=reply_markup if index == len(chunks) - 1 else None,
                link_preview_options={"is_disabled": disable_preview},
            )
        )
    return sent


async def typing_loop(bot: Bot, chat_id: int, stop: asyncio.Event, interval: float = 4.5) -> None:
    """Keep the “typing…” indicator alive until ``stop`` is set."""
    while not stop.is_set():
        with contextlib.suppress(Exception):
            await bot.send_chat_action(chat_id, "typing")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue


def chunks(sequence: Sequence[Any] | Iterable[Any], size: int) -> list[list[Any]]:
    items = list(sequence)
    return [items[index : index + size] for index in range(0, len(items), size)]


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def media_group_caption(text: str) -> str:
    return text[:TG_CAPTION_LIMIT]
