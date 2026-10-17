"""Optional group support: answer when mentioned or replied to."""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot.config import Settings
from bot.db.repository import Repository, User
from bot.handlers.ai import _respond
from bot.i18n import i18n
from bot.services.ai.client import AIClient
from bot.utils.urls import extract_urls

log = logging.getLogger(__name__)
router = Router(name="groups")

GROUP_TYPES = {"group", "supergroup"}


@router.message(F.chat.type.in_(GROUP_TYPES), F.text)
async def group_text(
    message: Message,
    user: User,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
    bot: Bot,
) -> None:
    if not cfg.enable_groups or message.from_user is None or message.from_user.is_bot:
        return
    text = message.text or ""
    if text.startswith("/"):
        return
    username = cfg.bot_username.lower()
    mention = f"@{username}"
    mentioned = mention in text.lower()
    replied = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == bot.id
    )
    if not mentioned and not replied:
        return
    prompt = re.sub(re.escape(mention), "", text, flags=re.IGNORECASE).strip()
    if extract_urls(prompt):
        return  # the download router handles links
    if not prompt:
        await message.reply(i18n.get(user.language, "ai.need_prompt"))
        return
    status = await message.reply(
        i18n.get(user.language, "ai.thinking"),
        link_preview_options={"is_disabled": True},
    )
    await _respond(
        status,
        user,
        prompt,
        cfg=cfg,
        repo=repo,
        ai_client=ai_client,
        remember=False,
    )
