"""Application entry point: wire everything together and poll Telegram."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from bot import __version__
from bot.config import Settings, get_settings
from bot.db import Database, Repository
from bot.handlers import admin, ai, download, fallback, groups, image, music, settings, start
from bot.i18n import i18n
from bot.logging_config import setup_logging
from bot.middlewares.force_join import ForceJoinMiddleware
from bot.middlewares.throttle import ThrottlingMiddleware
from bot.middlewares.user import UserMiddleware
from bot.services.ai.client import AIClient
from bot.services.ai.images import ImageService
from bot.services.downloader.direct import DirectDownloader
from bot.services.downloader.engine import DownloadEngine
from bot.services.downloader.inspector import Inspector
from bot.services.downloader.manager import DownloadManager
from bot.services.downloader.sender import MediaSender
from bot.web.health import start_health

log = logging.getLogger(__name__)


def _fa_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description=i18n.get("fa", "commands.start")),
        BotCommand(command="dl", description=i18n.get("fa", "commands.download")),
        BotCommand(command="music", description=i18n.get("fa", "commands.music")),
        BotCommand(command="ai", description=i18n.get("fa", "commands.ai")),
        BotCommand(command="img", description=i18n.get("fa", "commands.image")),
        BotCommand(command="settings", description=i18n.get("fa", "commands.settings")),
        BotCommand(command="account", description=i18n.get("fa", "commands.account")),
        BotCommand(command="help", description=i18n.get("fa", "commands.help")),
    ]


def _en_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description=i18n.get("en", "commands.start")),
        BotCommand(command="dl", description=i18n.get("en", "commands.download")),
        BotCommand(command="music", description=i18n.get("en", "commands.music")),
        BotCommand(command="ai", description=i18n.get("en", "commands.ai")),
        BotCommand(command="img", description=i18n.get("en", "commands.image")),
        BotCommand(command="settings", description=i18n.get("en", "commands.settings")),
        BotCommand(command="account", description=i18n.get("en", "commands.account")),
        BotCommand(command="help", description=i18n.get("en", "commands.help")),
    ]


def build_bot(cfg: Settings) -> Bot:
    api = TelegramAPIServer.from_base(cfg.api_server, is_local=True) if cfg.use_local_api else None
    kwargs = {"api": api} if api is not None else {}
    session = AiohttpSession(proxy=cfg.proxy or None, **kwargs)
    return Bot(
        token=cfg.bot_token.get_secret_value().strip(),
        session=session,
        default=DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True),
    )


async def main() -> None:
    cfg = get_settings()
    setup_logging(cfg.log_level, cfg.log_file)
    log.info("Starting TELRO %s", __version__)

    token = cfg.bot_token.get_secret_value().strip()
    if not token:
        log.error("BOT_TOKEN is missing. Copy .env.example to .env and set BOT_TOKEN.")
        raise SystemExit(1)

    if not cfg.ffmpeg_available:
        log.warning("ffmpeg not found: merging, MP3 conversion and compression are disabled.")
    if not cfg.deno_available:
        log.warning("Deno not found: YouTube may throttle or require a JS runtime. See docs/deploy.md.")
    if not cfg.ai_api_key.get_secret_value().strip():
        log.warning("AI_API_KEY is empty: using the free Pollinations-compatible endpoint (may be rate-limited).")
    if cfg.image_provider.lower() == "openai" and not cfg.image_api_key.get_secret_value().strip():
        log.warning("IMAGE_PROVIDER=openai but IMAGE_API_KEY is empty.")

    bot = build_bot(cfg)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError as exc:
        log.error("Telegram rejected BOT_TOKEN: %s", exc)
        await bot.session.close()
        raise SystemExit(1) from exc
    except Exception as exc:
        log.error("Could not reach Telegram: %s", exc)
        await bot.session.close()
        raise

    cfg.bot_username = me.username or cfg.bot_username
    cfg.bot_name = me.first_name or cfg.bot_name
    log.info("Connected as @%s (id=%s)", cfg.bot_username, me.id)

    db = Database(cfg.db_path)
    await db.connect()
    repo = Repository(db)

    inspector = Inspector(cfg)
    direct = DirectDownloader(cfg)
    engine = DownloadEngine(cfg)
    sender = MediaSender(bot)
    manager = DownloadManager(cfg, repo, bot, inspector, engine, direct, sender)
    ai_client = AIClient(cfg)
    image_service = ImageService(cfg)
    started_at = time.time()

    dp = Dispatcher(storage=MemoryStorage())
    dp.workflow_data.update(
        {
            "cfg": cfg,
            "repo": repo,
            "inspector": inspector,
            "direct": direct,
            "manager": manager,
            "ai_client": ai_client,
            "image_service": image_service,
            "started_at": started_at,
        }
    )

    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(UserMiddleware())
        observer.outer_middleware(ThrottlingMiddleware())
        observer.outer_middleware(ForceJoinMiddleware())

    dp.include_routers(
        start.router,
        settings.router,
        download.router,
        music.router,
        image.router,
        ai.router,
        admin.router,
        groups.router,
        fallback.router,
    )

    @dp.errors()
    async def on_error(event) -> bool:  # type: ignore[no-untyped-def]
        log.exception("Unhandled update error: %s", event.exception)
        return True

    health_runner = await start_health(cfg, started_at, manager)
    cleanup_task = asyncio.create_task(manager.cleanup_loop(), name="cleanup")

    try:
        with contextlib.suppress(Exception):
            await bot.set_my_commands(_fa_commands(), scope=BotCommandScopeDefault())
            await bot.set_my_commands(_en_commands(), scope=BotCommandScopeDefault(), language_code="en")
        log.info(
            "Ready. upload_limit=%s local_api=%s groups=%s",
            cfg.max_upload_label,
            cfg.use_local_api,
            cfg.enable_groups,
        )
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        log.info("Shutting down…")
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task
        await manager.shutdown()
        if health_runner is not None:
            await health_runner.cleanup()
        await ai_client.close()
        await image_service.close()
        await bot.session.close()
        await db.close()
        log.info("Goodbye.")


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":  # pragma: no cover
    run()
