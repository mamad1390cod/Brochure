"""
Bot-File-School - Telegram Bot for Managing School Notes (جزوه)
==============================================================

A professional, modular Telegram bot for managing, categorizing,
and searching class notes for 10th grade students.

Architecture: Field (رشته) → Subject (درس) → Chapter (فصل) → Note (جزوه)

Usage:
    1. Copy .env.example to .env and fill in values
    2. pip install -r requirements.txt
    3. python main.py
"""

import asyncio

from logger import logger

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.client.default import DefaultBotProperties

try:
    from config import BOT_TOKEN
except Exception:
    logger.exception("Bot configuration could not be loaded.")
    raise
from database import init_database
from handlers import router as main_router, set_bot_instance
from notes import router as notes_router
from admin import router as admin_router
from inline import router as inline_router
from schedule import router as schedule_router
from filetools import router as filetools_router
from tasks import router as tasks_router
from pdfmenu import router as pdfmenu_router
from groupbot import router as groupbot_router
from scheduler import start_backup_scheduler, start_scheduler, stop_backup_scheduler
from nudge import start_nudge_scheduler
from classnotifier import start_class_notifier
from middleware import (
    AdminAuthMiddleware,
    StateCleanupMiddleware,
    UsageMiddleware,
)
from pdfbot import pdf_bot_manager
from callback_ownership import (
    InlineKeyboardOwnershipMiddleware,
    InlineKeyboardOwnershipSessionMiddleware,
)
from navigation import BackNavigationMiddleware


async def on_startup(bot: Bot):
    """Run on bot startup."""
    logger.info("=" * 50)
    logger.info("Bot-File-School starting up...")
    logger.info("=" * 50)

    # Initialize database
    await init_database()
    logger.info("Database initialized.")

    # Set bot commands (Telegram only accepts a-z, 0-9 and _ in command names;
    # the Persian /جزوه command still works when typed but cannot appear here)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="شروع / منوی اصلی"),
            BotCommand(command="help", description="راهنما"),
            BotCommand(command="cl", description="بازگشت به مرحله قبل"),
        ])
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")

    start_backup_scheduler(bot)
    logger.info("Bot is ready!")


async def on_shutdown(bot: Bot):
    """Run on bot shutdown."""
    await stop_backup_scheduler()
    # Note: dp.start_polling() closes the bot session itself;
    # closing it here again would raise. Only log.
    logger.info("Bot-File-School shutting down...")


# Global dispatcher instance for FSM state checking from handlers
dp: Dispatcher | None = None


async def main():
    """Main entry point."""
    global dp

    try:
        logger.info("Preparing Bot-File-School.")
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        set_bot_instance(bot)
        dp = Dispatcher()

        bot.session.middleware.register(InlineKeyboardOwnershipSessionMiddleware())
        dp.message.outer_middleware(InlineKeyboardOwnershipMiddleware())
        dp.callback_query.outer_middleware(InlineKeyboardOwnershipMiddleware())
        dp.message.outer_middleware(BackNavigationMiddleware())
        dp.callback_query.outer_middleware(BackNavigationMiddleware())
        dp.callback_query.outer_middleware(StateCleanupMiddleware())

        admin_guard = AdminAuthMiddleware(guard_all=False)
        tasks_router.callback_query.middleware(admin_guard)
        tasks_router.message.middleware(admin_guard)

        usage_mw = UsageMiddleware()
        for router in (
            notes_router, schedule_router, filetools_router,
            tasks_router, pdfmenu_router, main_router,
        ):
            router.message.middleware(usage_mw)
            router.callback_query.middleware(usage_mw)

        dp.include_router(inline_router)
        # /start and /help must run before FSM routers; otherwise an in-progress
        # text-input state can consume the command as ordinary form input.
        dp.include_router(main_router)
        dp.include_router(notes_router)
        dp.include_router(admin_router)
        dp.include_router(schedule_router)
        dp.include_router(filetools_router)
        dp.include_router(tasks_router)
        dp.include_router(pdfmenu_router)
        dp.include_router(groupbot_router)

        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)

        start_scheduler()
        start_nudge_scheduler(bot)
        start_class_notifier(bot)
        pdf_bot_manager.start()

        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    except Exception as exc:
        if "database is locked" in str(exc).lower():
            logger.exception(
                "Bot stopped because the database is locked. Check for another "
                "bot instance, cloud sync, antivirus activity, or stale SQLite "
                "WAL/SHM files."
            )
        else:
            logger.exception("Bot startup or polling failed.")
        raise
    finally:
        pdf_bot_manager.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
