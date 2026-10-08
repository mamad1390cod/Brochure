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
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN
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
from scheduler import start_scheduler
from nudge import start_nudge_scheduler
from classnotifier import start_class_notifier
from middleware import UsageMiddleware, StateCleanupMiddleware
from pdfbot import pdf_bot_manager
from logger import logger


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
        ])
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")

    logger.info("Bot is ready!")


async def on_shutdown(bot: Bot):
    """Run on bot shutdown."""
    # Note: dp.start_polling() closes the bot session itself;
    # closing it here again would raise. Only log.
    logger.info("Bot-File-School shutting down...")


# Global dispatcher instance for FSM state checking from handlers
dp: Dispatcher | None = None


async def main():
    """Main entry point."""
    global dp

    # Create bot instance
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Set global bot instance for use in other modules
    set_bot_instance(bot)

    # Create dispatcher
    dp = Dispatcher()

    # Global safety net: tapping any button outside a half-finished input
    # flow cancels that flow (state cleared) so stray text is never swallowed.
    dp.callback_query.outer_middleware(StateCleanupMiddleware())

    # Usage tracking middleware on user-facing routers (NOT the admin router)
    usage_mw = UsageMiddleware()
    for r in (notes_router, schedule_router, filetools_router,
              tasks_router, pdfmenu_router, main_router):
        r.message.middleware(usage_mw)
        r.callback_query.middleware(usage_mw)

    # Register routers (order matters - more specific first).
    # groupbot_router MUST stay last: its catch-all tracker only records
    # unmatched group messages and must never swallow handled ones.
    dp.include_router(inline_router)
    dp.include_router(notes_router)
    dp.include_router(admin_router)
    dp.include_router(schedule_router)
    dp.include_router(filetools_router)
    dp.include_router(tasks_router)
    dp.include_router(pdfmenu_router)
    dp.include_router(main_router)
    dp.include_router(groupbot_router)

    # Register startup/shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start the weekly scheduler (Saturday task reset + admin session expiry)
    start_scheduler()

    # Group nudge scheduler: friendly message if the group is quiet 4+ days
    start_nudge_scheduler(bot)

    # Online class notifications + goodnight message (timezone aware,
    # schedules reloaded from the database after every restart)
    start_class_notifier(bot)

    # Launch the optional standalone PDF bot (bot1cc.py) as a separate process.
    # If PDF_BOT_PATH is not set/valid this is a no-op and the in-app PDF
    # tools keep working. A PDF bot crash never stops the main bot.
    pdf_bot_manager.start()

    # Start polling
    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        if "database is locked" in str(e).lower():
            logger.error(
                "Bot crashed: database is locked!\n"
                "Possible causes and fixes:\n"
                "  1. Another instance of the bot is still running - close it.\n"
                "  2. OneDrive/antivirus is syncing data/school_notes.db - "
                "pause sync or move the project out of the OneDrive folder.\n"
                "  3. Delete stale data/school_notes.db-wal and -shm files, "
                "then start the bot again."
            )
        else:
            logger.error(f"Bot crashed: {e}")
        sys.exit(1)
    finally:
        # Graceful shutdown of the PDF bot process when the main bot exits
        pdf_bot_manager.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
