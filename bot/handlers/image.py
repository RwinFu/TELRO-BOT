"""AI image generation with aspect-ratio picker."""

from __future__ import annotations

import contextlib
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, LinkPreviewOptions, Message

from bot.db.repository import User
from bot.handlers.states import ChatStates
from bot.i18n import i18n
from bot.keyboards.inline import aspect_keyboard, back_menu, image_result, simple_back
from bot.services.ai.images import ImageService
from bot.services.downloader.errors import ImageError
from bot.utils.formatting import truncate
from bot.utils.telegram import answer_callback, safe_delete, safe_edit
from bot.utils.text import esc
from bot.utils.urls import extract_urls

log = logging.getLogger(__name__)
router = Router(name="image")

_busy: set[int] = set()
ASPECT_NAMES = {"square": "1:1", "landscape": "16:9", "portrait": "9:16", "story": "9:16"}


@router.message(Command("img", "image", "imagine"))
async def cmd_image(
    message: Message,
    command,
    user: User,
    state: FSMContext,
) -> None:
    prompt = (command.args or "").strip()
    if not prompt and message.reply_to_message is not None:
        prompt = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if prompt:
        await _ask_aspect(message, prompt, user, state)
        return
    await state.set_state(ChatStates.image)
    await state.update_data(image_prompt=None)
    await message.answer(
        f"{i18n.get(user.language, 'image.title')}\n\n{i18n.get(user.language, 'image.intro')}",
        reply_markup=back_menu(user.language),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.callback_query(F.data == "menu:image")
async def cb_image(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(ChatStates.image)
    await state.update_data(image_prompt=None)
    text = f"{i18n.get(user.language, 'image.title')}\n\n{i18n.get(user.language, 'image.intro')}"
    if callback.message is not None:
        await safe_edit(callback.message, text, back_menu(user.language))
    await answer_callback(callback)


@router.message(ChatStates.image, F.text, ~F.text.startswith("/"))
async def on_prompt(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    if not text or extract_urls(text):
        return
    await _ask_aspect(message, text, user, state)


async def _ask_aspect(message: Message, prompt: str, user: User, state: FSMContext) -> None:
    await state.set_state(ChatStates.image)
    await state.update_data(image_prompt=prompt, image_aspect="square", image_last=None)
    text = (
        f"{i18n.get(user.language, 'image.title')}\n\n"
        f"📝 <b>{esc(truncate(prompt, 400))}</b>\n\n"
        f"{i18n.get(user.language, 'image.choose_aspect')}"
    )
    await message.answer(
        text,
        reply_markup=aspect_keyboard(user.language),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.callback_query(F.data.startswith("img:aspect:"))
async def cb_aspect(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    image_service: ImageService,
) -> None:
    aspect = (callback.data or "").split(":", 2)[-1]
    data = await state.get_data()
    prompt = data.get("image_prompt")
    if not prompt:
        await answer_callback(callback, i18n.get(user.language, "image.prompt"), alert=True)
        return
    await state.update_data(image_aspect=aspect)
    await answer_callback(callback)
    await _generate(callback, prompt, aspect, user, state, image_service, edit_message=True)


@router.callback_query(F.data == "img:again")
async def cb_again(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    image_service: ImageService,
) -> None:
    data = await state.get_data()
    last = data.get("image_last") or {}
    prompt = last.get("prompt") or data.get("image_prompt")
    aspect = last.get("aspect") or data.get("image_aspect") or "square"
    if not prompt:
        await answer_callback(callback, i18n.get(user.language, "image.prompt"), alert=True)
        return
    await answer_callback(callback)
    await _generate(callback, prompt, aspect, user, state, image_service, edit_message=False)


@router.callback_query(F.data == "img:new")
async def cb_new(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(ChatStates.image)
    await state.update_data(image_prompt=None)
    await answer_callback(callback)
    if callback.message is not None:
        await safe_edit(
            callback.message,
            i18n.get(user.language, "image.prompt"),
            simple_back(user.language),
        )


async def _generate(
    callback: CallbackQuery,
    prompt: str,
    aspect: str,
    user: User,
    state: FSMContext,
    image_service: ImageService,
    *,
    edit_message: bool,
) -> None:
    lang = user.language
    if user.id in _busy:
        await answer_callback(callback, i18n.get(lang, "image.too_many"), alert=True)
        return
    _busy.add(user.id)
    status: Message | None = None
    try:
        text = i18n.get(lang, "image.generating", prompt=esc(truncate(prompt, 300)))
        if edit_message and callback.message is not None:
            await safe_edit(callback.message, text)
            status = callback.message
        elif callback.message is not None:
            status = await callback.message.answer(text)
        generated = await image_service.generate(prompt, aspect)
        caption = i18n.get(
            lang,
            "image.ready",
            prompt=esc(truncate(prompt, 350)),
            aspect=ASPECT_NAMES.get(generated.aspect, generated.aspect),
            provider=generated.provider.title(),
        )[:1024]
        if callback.message is None:
            return
        await callback.message.answer_photo(
            photo=FSInputFile(generated.path),
            caption=caption,
            reply_markup=image_result(lang),
        )
        await state.update_data(
            image_last={"prompt": prompt, "aspect": aspect},
            image_prompt=prompt,
            image_aspect=aspect,
        )
        await safe_delete(status)
    except ImageError as exc:
        error_text = i18n.get(lang, "image.error")
        message = i18n.get(lang, exc.key)
        text = f"{error_text}\n\n<i>{esc(message)}</i>"
        if status is not None:
            await safe_edit(status, text, simple_back(lang))
        elif callback.message is not None:
            await callback.message.answer(text, reply_markup=simple_back(lang))
    except Exception:
        log.exception("image generation failed")
        if status is not None:
            await safe_edit(status, i18n.get(lang, "image.error"), simple_back(lang))
    finally:
        _busy.discard(user.id)
        with contextlib.suppress(Exception):
            if "generated" in locals() and generated.path.exists():
                generated.path.unlink()
