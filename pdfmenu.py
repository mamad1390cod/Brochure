"""
Callback handlers for the user-facing "📄 ساخت PDF" option.

Reuses the EXISTING PDF tools (filetools.py / convert.py) - the PDF
generation logic is NOT rewritten. If the optional standalone PDF bot
(bot1cc.py, PDF_BOT_PATH env) is configured and running, users are
routed to it as well (deeplink/help message).

Since Bot1 is a separate Telegram bot (separate token/polling), the
integration approach is a guided handoff: the main bot shows the PDF
menu with the built-in tools, and - when Bot1 is alive - a link/button
pointing to the standalone bot so the user can use its full workflow.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards
from config import PDF_BOT_ENABLED, PDF_BOT_USERNAME
from pdfbot import pdf_bot_manager
from logger import logger

router = Router()


@router.callback_query(F.data == "menu_make_pdf")
async def menu_make_pdf_handler(callback: CallbackQuery, state=None):
    """📄 ساخت PDF - entry point for users."""
    await callback.answer()
    try:
        from filetools import _remember_back
        if state:
            await _remember_back(state, "menu_main")
    except Exception:
        pass
    kb = InlineKeyboardBuilder()

    bot1_alive = pdf_bot_manager.is_running() if PDF_BOT_ENABLED else False

    text = (
        "📄 <b>ساخت PDF</b>\n\n"
        "ابزارهای ساخت PDF را انتخاب کنید:\n\n"
        "🖼 چند عکس را به یک PDF تبدیل کنید\n"
        "📄 فایل Word را به PDF تبدیل کنید\n"
        "📝 فایل PDF را به Word تبدیل کنید"
    )

    if bot1_alive:
        # The standalone PDF bot is running - offer a handoff to it too.
        if PDF_BOT_USERNAME:
            url = f"https://t.me/{PDF_BOT_USERNAME}"
            kb.row(InlineKeyboardButton(
                text="🤖 ربات PDF پیشرفته", url=url))
            text += "\n\n💡 برای امکانات بیشتر، ربات PDF پیشرفته را هم باز کنید."
        else:
            text += "\n\n💡 ربات PDF پیشرفته روی سرور فعال است."
        logger.debug(f"{user_log(callback)} opened PDF menu (bot1 running)")
    else:
        logger.debug(f"{user_log(callback)} opened PDF menu (builtin only)")

    kb.row(InlineKeyboardButton(
        text="🖼 تصاویر → PDF", callback_data="tool_images_pdf"))
    kb.row(InlineKeyboardButton(
        text="📄 Word → PDF", callback_data="tool_word_pdf"),
        InlineKeyboardButton(text="📝 PDF → Word", callback_data="tool_pdf_word"),
    )
    kb.row(InlineKeyboardButton(
        text="🔙 منوی اصلی", callback_data="menu_main"))

    await callback.message.edit_text(
        text, reply_markup=kb.as_markup(), parse_mode="HTML")


def user_log(callback: CallbackQuery) -> str:
    return f"user {callback.from_user.id}"
