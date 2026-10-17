"""Last-resort handlers so the bot never stays silent in private chats."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.db.repository import User
from bot.i18n import i18n
from bot.keyboards.inline import main_menu
from bot.utils.telegram import answer_callback

router = Router(name="fallback")


@router.message(F.chat.type == "private")
async def on_unknown(message: Message, user: User, is_admin: bool) -> None:
    if message.text and message.text.startswith("/"):
        text = i18n.get(user.language, "fallback.text")
    elif message.text:
        text = i18n.get(user.language, "fallback.text")
    else:
        text = i18n.get(user.language, "fallback.unsupported")
    await message.answer(
        text,
        reply_markup=main_menu(user.language, is_admin=is_admin),
        link_preview_options={"is_disabled": True},
    )


@router.callback_query()
async def on_unknown_callback(callback: CallbackQuery) -> None:
    await answer_callback(callback)
