"""AI chat mode with streaming, vision and voice transcription."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import logging
import time
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.config import Settings
from bot.db.repository import Repository, User
from bot.handlers.download import LINK_HINT
from bot.handlers.states import ChatStates
from bot.i18n import i18n
from bot.keyboards.inline import ai_mode, main_menu
from bot.services.ai.client import AIClient, build_messages, build_user_content
from bot.services.ai.prompts import DEFAULT_SYSTEM_PROMPT
from bot.services.downloader.errors import AIError
from bot.utils.formatting import truncate
from bot.utils.telegram import answer_callback, safe_delete, safe_edit, typing_loop
from bot.utils.text import esc, split_html

log = logging.getLogger(__name__)
router = Router(name="ai")

_tasks: dict[int, asyncio.Task[Any]] = {}


async def _reload(repo: Repository, user: User) -> User:
    fresh = await repo.get_user(user.id)
    return fresh or user


@router.message(Command("ai", "chat", "ask"))
async def cmd_ai(
    message: Message,
    command,
    user: User,
    state: FSMContext,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
) -> None:
    prompt = (command.args or "").strip()
    if not prompt and message.reply_to_message is not None:
        prompt = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    await state.set_state(ChatStates.ai)
    if not prompt:
        await message.answer(
            f"{i18n.get(user.language, 'ai.title')}\n\n{i18n.get(user.language, 'ai.intro')}",
            reply_markup=ai_mode(user.language),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return
    _launch(message, prompt, user, cfg=cfg, repo=repo, ai_client=ai_client, remember=True)


@router.callback_query(F.data == "menu:ai")
async def cb_ai(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(ChatStates.ai)
    text = f"{i18n.get(user.language, 'ai.title')}\n\n{i18n.get(user.language, 'ai.intro')}"
    if callback.message is not None:
        await safe_edit(callback.message, text, ai_mode(user.language))
    await answer_callback(callback)


@router.message(ChatStates.ai, F.chat.type == "private", F.text, ~F.text.startswith("/"), ~F.text.regexp(LINK_HINT))
async def on_ai_text(
    message: Message,
    user: User,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    _launch(message, text, user, cfg=cfg, repo=repo, ai_client=ai_client, remember=True)


@router.message(ChatStates.ai, F.chat.type == "private", F.photo)
async def on_ai_photo(
    message: Message,
    user: User,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
    bot: Bot,
) -> None:
    if not cfg.ai_vision:
        await message.answer(i18n.get(user.language, "ai.vision_off"))
        return
    if not message.photo:
        return
    status = await message.answer(i18n.get(user.language, "ai.thinking"), reply_markup=ai_mode(user.language))
    try:
        buffer = io.BytesIO()
        await bot.download(message.photo[-1], destination=buffer)
        raw = buffer.getvalue()
        if len(raw) > 8 * 1024 * 1024:
            await safe_edit(status, i18n.get(user.language, "ai.error"))
            return
        encoded = base64.b64encode(raw).decode()
        prompt = (message.caption or "").strip() or i18n.get(user.language, "ai.image_prompt")
        content = build_user_content(prompt, f"data:image/jpeg;base64,{encoded}")
        await _respond(
            status,
            user,
            prompt,
            cfg=cfg,
            repo=repo,
            ai_client=ai_client,
            content=content,
            remember=True,
        )
    except AIError as exc:
        await safe_edit(status, i18n.get(user.language, exc.key), ai_mode(user.language))
    except Exception:
        log.exception("vision request failed")
        await safe_edit(status, i18n.get(user.language, "ai.error"), ai_mode(user.language))


@router.message(ChatStates.ai, F.chat.type == "private", F.voice)
async def on_ai_voice(
    message: Message,
    user: User,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
    bot: Bot,
) -> None:
    if not cfg.ai_transcribe:
        await message.answer(i18n.get(user.language, "ai.voice_off"))
        return
    status = await message.answer(i18n.get(user.language, "ai.thinking"), reply_markup=ai_mode(user.language))
    try:
        buffer = io.BytesIO()
        await bot.download(message.voice, destination=buffer)
        transcript = await ai_client.transcribe(buffer.getvalue())
        if not transcript:
            await safe_edit(status, i18n.get(user.language, "ai.voice_failed"), ai_mode(user.language))
            return
        await safe_edit(status, f"🎤 <i>{esc(transcript)}</i>", ai_mode(user.language))
        reply = await message.answer("…")
        await _respond(
            reply,
            user,
            transcript,
            cfg=cfg,
            repo=repo,
            ai_client=ai_client,
            remember=True,
        )
        with contextlib.suppress(Exception):
            await status.delete()
    except AIError as exc:
        await safe_edit(status, i18n.get(user.language, exc.key), ai_mode(user.language))
    except Exception:
        log.exception("voice request failed")
        await safe_edit(status, i18n.get(user.language, "ai.voice_failed"), ai_mode(user.language))


def _launch(
    message: Message,
    prompt: str,
    user: User,
    *,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
    remember: bool,
) -> None:
    previous = _tasks.get(user.id)
    if previous and not previous.done():
        previous.cancel()

    async def runner() -> None:
        status = await message.answer(
            i18n.get(user.language, "ai.thinking"),
            reply_markup=ai_mode(user.language),
        )
        await _respond(
            status,
            user,
            prompt,
            cfg=cfg,
            repo=repo,
            ai_client=ai_client,
            remember=remember,
        )

    task = asyncio.create_task(runner(), name=f"ai-{user.id}")
    _tasks[user.id] = task

    def _done(_: asyncio.Task[Any]) -> None:
        if _tasks.get(user.id) is task:
            _tasks.pop(user.id, None)

    task.add_done_callback(_done)


async def _respond(
    status: Message,
    user: User,
    prompt: str,
    *,
    cfg: Settings,
    repo: Repository,
    ai_client: AIClient,
    content: str | list[dict[str, Any]] | None = None,
    remember: bool = True,
) -> None:
    lang = user.language
    if not cfg.ai_enabled:
        await safe_edit(status, i18n.get(lang, "ai.not_configured"), ai_mode(lang))
        return
    allowed, used = await repo.consume_ai(
        user.id, cfg.free_ai_per_day, unlimited=user.is_premium or user.id in cfg.admins
    )
    if not allowed:
        await safe_edit(
            status,
            i18n.get(lang, "ai.quota", used=used, limit=cfg.free_ai_per_day),
            ai_mode(lang),
        )
        return

    stop = asyncio.Event()
    typing = asyncio.create_task(typing_loop(status.bot, status.chat.id, stop))
    buffer: list[str] = []
    last_edit = 0.0
    success = False
    try:
        history = await repo.ai_history(user.id, cfg.ai_history_messages) if remember else []
        system_prompt = cfg.ai_system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
        messages = build_messages(
            system_prompt,
            history,
            content if content is not None else prompt,
            max_chars=cfg.ai_history_chars,
        )
        async for delta in ai_client.stream(messages):
            buffer.append(delta)
            now = time.monotonic()
            if now - last_edit >= 1.2:
                last_edit = now
                partial = "".join(buffer)
                if partial.strip():
                    await safe_edit(status, _partial_html(partial), ai_mode(lang))
        final = "".join(buffer).strip()
        if not final:
            raise AIError("ai.empty")
        success = True
        if remember:
            history_text = prompt if content is None else f"[🖼 photo] {prompt}"
            await repo.ai_add(user.id, "user", history_text[:4000])
            await repo.ai_add(user.id, "assistant", final[:8000])
        await _deliver_final(status, final, lang)
    except asyncio.CancelledError:
        stop.set()
        typing.cancel()
        if not success:
            await repo.refund_ai(user.id)
            await safe_delete(status)
        raise
    except AIError as exc:
        await repo.refund_ai(user.id)
        await safe_edit(status, _error_text(lang, exc), ai_mode(lang))
    except Exception:
        log.exception("AI request failed")
        await repo.refund_ai(user.id)
        await safe_edit(status, i18n.get(lang, "ai.error"), ai_mode(lang))
    finally:
        stop.set()
        typing.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing


def _error_text(lang: str, exc: AIError) -> str:
    message = i18n.get(lang, exc.key)
    if message == exc.key:
        message = i18n.get(lang, "ai.error")
    return f"{i18n.get(lang, 'ai.title')}\n\n{message}"


def _partial_html(text: str) -> str:
    chunks = split_html(truncate(text, 3900) + " ▌")
    return chunks[0] if chunks else esc(text[:100])


async def _deliver_final(status: Message, text: str, lang: str) -> None:
    chunks = split_html(text)
    if not chunks:
        await safe_edit(status, i18n.get(lang, "ai.empty"), ai_mode(lang))
        return
    edited = await safe_edit(status, chunks[0], ai_mode(lang) if len(chunks) == 1 else None)
    if not edited:
        await status.answer(chunks[0])
    for index, chunk in enumerate(chunks[1:]):
        last = index == len(chunks) - 2
        await status.answer(chunk, reply_markup=ai_mode(lang) if last else None)


@router.callback_query(F.data == "ai:reset")
async def cb_ai_reset(callback: CallbackQuery, user: User, repo: Repository) -> None:
    await repo.ai_clear(user.id)
    await answer_callback(callback, i18n.get(user.language, "ai.cleared"))


@router.callback_query(F.data == "ai:exit")
async def cb_ai_exit(callback: CallbackQuery, user: User, state: FSMContext, is_admin: bool) -> None:
    task = _tasks.get(user.id)
    if task and not task.done():
        task.cancel()
    await state.clear()
    if callback.message is not None:
        await safe_edit(
            callback.message,
            i18n.get(user.language, "ai.exit"),
            main_menu(user.language, is_admin=is_admin),
        )
    await answer_callback(callback)


@router.message(Command("reset", "newchat", "clear"))
async def cmd_reset(message: Message, user: User, repo: Repository) -> None:
    await repo.ai_clear(user.id)
    await message.answer(i18n.get(user.language, "ai.cleared"), reply_markup=ai_mode(user.language))
