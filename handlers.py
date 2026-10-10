"""
Main handlers for Bot-File-School.
Handles /start, /help, and general user interactions.
"""

from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import models
import keyboards
from config import ALLOWED_GROUP_ID, MAIN_ADMIN_ID
from permissions import is_admin
from utils import escape_html
from logger import logger
from navigation import pop_previous_step, restore_previous_screen


class UserChapterSearch(StatesGroup):
    waiting_query = State()

# Global bot instance (set in main.py)
bot: Bot | None = None

router = Router()


def set_bot_instance(bot_instance: Bot):
    """Set the global bot instance."""
    global bot
    bot = bot_instance


# ─── /start Command ──────────────────────────────────────────────────────────

@router.message(Command("cl"))
async def back_command_handler(message: Message, state: FSMContext):
    """Return to the previous recorded screen and restore its FSM data."""
    step = pop_previous_step(message.chat.id, message.from_user.id)
    if step is None:
        await message.answer("↩️ مرحله قبلی برای بازگشت وجود ندارد.")
        return

    current_data = await state.get_data()
    if step.state and step.state.startswith("FileToolsFlow:"):
        paths = set(current_data.get("img_paths", []))
        restored_paths = set(step.data.get("img_paths", []))
        step.data["img_paths"] = [
            path for path in step.data.get("img_paths", [])
            if path in paths and Path(path).exists()
        ]
        for path in paths - restored_paths:
            Path(path).unlink(missing_ok=True)

    await state.set_data(step.data)
    await state.set_state(step.state)
    if step.screen is None or not await restore_previous_screen(message, step.screen):
        await message.answer("↩️ به مرحله قبلی برگشتید؛ اطلاعات همان مرحله را دوباره ارسال کنید.")


@router.message(Command("start", "help", "راهنما"))
async def start_handler(message: Message, state: FSMContext):
    """Show the user menu to everyone and the admin entry to valid admins."""
    # /start always cancels any half-finished input flow
    if state:
        current_state = await state.get_state()
        if current_state and current_state.startswith("FileToolsFlow:"):
            from filetools import cleanup_filetools_state
            await cleanup_filetools_state(state)
        await state.clear()
    user = message.from_user

    # Optional group restriction: only respond inside the allowed group or private chats
    if (
        ALLOWED_GROUP_ID is not None
        and message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
        and message.chat.id != ALLOWED_GROUP_ID
    ):
        return

    try:
        await models.upsert_user(user.id, user.username or "", user.full_name or "")
        has_admin_access = await is_admin(user.id)
        await message.answer(
            f"👋 سلام <b>{escape_html(user.full_name)}</b>!\n\n"
            "به ربات مدیریت جزوه‌های مدرسه خوش آمدید! 📚\n\n"
            "با این ربات می‌توانید:\n"
            "• جزوه‌ها را بر اساس رشته، درس و فصل مشاهده کنید\n"
            "• جزوه‌ها را جستجو کنید\n"
            "• جزوه جدید ثبت کنید\n\n"
            "برای بازگشت به مرحله قبلی در هر زمان /cl را ارسال کنید.\n\n"
            "از منوی زیر استفاده کنید:",
            reply_markup=keyboards.main_menu_keyboard(
                has_admin_access=has_admin_access
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Could not process /start for Telegram user %s", user.id)
        try:
            await message.answer(
                "❌ شروع ربات موقتاً با خطا روبه‌رو شد. لطفاً کمی بعد دوباره /start را بزنید."
            )
        except Exception:
            logger.exception("Could not send /start failure notice to user %s", user.id)
        return

    logger.info("User %s (@%s) started the bot", user.id, user.username or "")


# ─── Persian Command: جزوه ──────────────────────────────────────────────────

@router.message(Command("جزوه"))
async def jozve_command(message: Message, state: FSMContext):
    """Handle Persian /جزوه command - start note submission."""
    from notes import SubmitNoteFlow

    fields = await models.get_fields()
    if not fields:
        await message.answer(
            "❌ هیچ رشته‌ای ثبت نشده است. لطفاً بعداً تلاش کنید.",
            reply_markup=await keyboards.main_menu_keyboard_for(message.from_user.id),
        )
        return

    await state.set_state(SubmitNoteFlow.selecting_field)
    await message.answer(
        "📚 <b>ثبت جزوه جدید</b>\n\n"
        "مرحله ۱ از ۶: رشته تحصیلی را انتخاب کنید:",
        reply_markup=keyboards.submit_field_keyboard(fields),
        parse_mode="HTML",
    )


@router.message(F.text == "جزوه اضافه میکنم")
async def jozve_text_handler(message: Message, state: FSMContext):
    """Handle text 'جزوه اضافه میکنم' - start note submission."""
    await jozve_command(message, state)


# ─── File Tools / Schedule Menus (Regular Users) ─────────────────────────────

@router.callback_query(F.data == "menu_tools")
async def menu_tools_handler(callback: CallbackQuery, state: FSMContext):
    """Show general file tools menu (PDF tools for everyone)."""
    await callback.answer()
    from filetools import _remember_back
    await _remember_back(state, "menu_main")   # user came from main menu
    await callback.message.edit_text(
        "🛠 <b>ابزارهای فایل</b>\n\n"
        "این ابزارها برای همه کاربران فعال است:",
        reply_markup=keyboards.file_tools_keyboard("menu_main"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_schedule")
async def menu_schedule_handler(callback: CallbackQuery):
    """Open the weekly schedule grid (delegates to schedule.py)."""
    from schedule import menu_schedule_handler as sched_handler
    await sched_handler(callback)


# ─── Fields Menu (Regular Users) ──────────────────────────────────────────────

@router.callback_query(F.data == "menu_fields")
async def menu_fields_handler(callback: CallbackQuery):
    """Show fields for browsing notes."""
    await callback.answer()
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "📚 هیچ رشته‌ای ثبت نشده است.",
            reply_markup=await keyboards.main_menu_keyboard_for(callback.from_user.id),
            parse_mode="HTML",
        )
        return

    await callback.message.edit_text(
        "📚 <b>رشته‌های تحصیلی</b>\n\n"
        "رشته موردنظر را انتخاب کنید:",
        reply_markup=keyboards.user_fields_keyboard(fields),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("user_field:"))
async def user_field_view_handler(callback: CallbackQuery):
    """User views a field's subjects."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    field = await models.get_field_by_id(field_id)
    if not field:
        await callback.answer("❌ رشته یافت نشد!", show_alert=True)
        return

    subjects = await models.get_subjects_by_field(field_id)
    if not subjects:
        await callback.message.edit_text(
            f"📚 رشته: <b>{field['name']}</b>\n\n"
            "❌ هیچ درسی ثبت نشده است.",
            reply_markup=keyboards.user_fields_keyboard(await models.get_fields()),
            parse_mode="HTML",
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {subject['name']}",
                callback_data=f"user_subject:{subject['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu_fields"),
    )

    await callback.message.edit_text(
        f"📚 رشته: <b>{field['name']}</b>\n\n"
        f"📖 <b>درس‌ها</b>:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("user_subject:"))
async def user_subject_handler(callback: CallbackQuery):
    """User views a subject's chapters and notes."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    if not subject:
        await callback.answer("❌ درس یافت نشد!", show_alert=True)
        return

    chapters = await models.get_chapters_by_subject(subject_id)
    notes = await models.get_approved_notes(subject_id=subject_id, limit=10)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()

    # Show chapters
    for chapter in chapters:
        kb.row(
            InlineKeyboardButton(
                text=f"📕 {chapter['name']}",
                callback_data=f"user_chapter:{chapter['id']}",
            )
        )

    # Show recent notes
    for note in notes[:5]:
        title = note["title"][:25] + "..." if len(note["title"]) > 25 else note["title"]
        kb.row(
            InlineKeyboardButton(
                text=f"📄 {title}",
                callback_data=f"user_note:{note['id']}",
            )
        )

    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"user_field_back:{subject['field_id']}"),
    )

    await callback.message.edit_text(
        f"📖 درس: <b>{subject['name']}</b>\n\n"
        f"📕 فصل‌ها: {len(chapters)}\n"
        f"📄 جزوه‌ها: آخرین جزوه‌ها نمایش داده شده‌اند",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("user_chapter:"))
async def user_chapter_handler(callback: CallbackQuery):
    """User views a chapter's notes."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    chapter = await models.get_chapter_by_id(chapter_id)
    if not chapter:
        await callback.answer("❌ فصل یافت نشد!", show_alert=True)
        return

    notes = await models.get_approved_notes(chapter_id=chapter_id, limit=200)

    from utils import note_file_label
    kb = InlineKeyboardBuilder()

    if not notes:
        kb.row(InlineKeyboardButton(text="⚪ فایلی در این فصل نیست", callback_data="noop"))
    for note in notes:
        kb.row(
            InlineKeyboardButton(
                text=note_file_label(note),
                callback_data=f"user_note:{note['id']}",
            )
        )

    if notes:
        kb.row(InlineKeyboardButton(
            text="🔍 جستجوی فایل", callback_data=f"user_chapter_search:{chapter_id}"))
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"user_subject:{chapter['subject_id']}"),
    )

    await callback.message.edit_text(
        f"📕 فصل: <b>{chapter['name']}</b>\n\n"
        f"📁 همه فایل‌ها ({len(notes)}) — نام | حجم:\n"
        f"<i>روی فایل کلیک کنید تا جزئیات و دانلود نمایش داده شود</i>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("user_chapter_search:"))
async def user_chapter_search_start(callback: CallbackQuery, state: FSMContext):
    """Ask the user for a file-name search query inside this chapter."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    await state.set_state(UserChapterSearch.waiting_query)
    await state.update_data(search_chapter_id=chapter_id)
    await callback.message.edit_text(
        "🔍 <b>جستجوی فایل در فصل</b>\n\n"
        "نام یا بخشی از نام فایل را ارسال کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ انصراف",
                callback_data=f"user_chapter:{chapter_id}")],
        ]),
        parse_mode="HTML",
    )


@router.message(UserChapterSearch.waiting_query, F.text)
async def user_chapter_search_query(message: Message, state: FSMContext):
    query = message.text.strip()[:100]
    data = await state.get_data()
    chapter_id = int(data.get("search_chapter_id", 0))
    await state.clear()
    chapter = await models.get_chapter_by_id(chapter_id)
    notes = await models.search_chapter_notes(chapter_id, query, approved_only=True)

    from utils import note_file_label
    kb = InlineKeyboardBuilder()
    if not notes:
        kb.row(InlineKeyboardButton(
            text=f"⚪ نتیجه‌ای برای «{query[:20]}» نیست", callback_data="noop"))
    for note in notes:
        kb.row(InlineKeyboardButton(
            text=note_file_label(note),
            callback_data=f"user_note:{note['id']}",
        ))
    back = f"user_subject:{chapter['subject_id']}" if chapter else "menu_fields"
    kb.row(InlineKeyboardButton(text="🔄 همه فایل‌ها", callback_data=f"user_chapter:{chapter_id}"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back))
    await message.answer(
        f"🔍 جستجوی «{escape_html(query)}» در فصل "
        f"<b>{escape_html(chapter['name'] if chapter else '')}</b>\n\n"
        f"📁 {len(notes)} فایل پیدا شد:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("user_note:"))
async def user_note_handler(callback: CallbackQuery):
    """User views a note's details and can download."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)

    # Only approved, active notes are visible to regular users
    if not note or note["status"] != "approved" or not note["is_active"]:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    field = await models.get_field_by_id(note["field_id"])
    subject = await models.get_subject_by_id(note["subject_id"])
    chapter = await models.get_chapter_by_id(note["chapter_id"]) if note["chapter_id"] else None

    from utils import format_note_info, format_page_range
    note_data = {
        "title": note["title"],
        "description": note["description"],
        "field_name": field["name"] if field else "",
        "subject_name": subject["name"] if subject else "",
        "chapter_name": chapter["name"] if chapter else "بدون فصل",
        "page_start": note["page_start"],
        "page_end": note["page_end"],
        "file_type": note["file_type"],
        "file_size": note["file_size"],
        "created_at": note["created_at"],
        "submitted_by_name": note["submitted_by_name"],
        "status": note["status"],
    }

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 دریافت جزوه", callback_data=f"user_download:{note_id}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"menu_fields")],
    ])

    await callback.message.edit_text(
        format_note_info(note_data),
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("user_download:"))
async def user_download_handler(callback: CallbackQuery):
    """Send note file to user."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)

    # Only approved, active notes can be downloaded by regular users
    if not note or not note["file_id"] or note["status"] != "approved" or not note["is_active"]:
        await callback.answer("❌ فایل یافت نشد!", show_alert=True)
        return

    try:
        if note["file_type"] == "photo":
            await callback.message.answer_photo(note["file_id"], caption=f"📄 {note['title']}")
        elif note["file_type"] == "video":
            await callback.message.answer_video(note["file_id"], caption=f"📄 {note['title']}")
        elif note["file_type"] in ("document", "audio"):
            await callback.message.answer_document(note["file_id"], caption=f"📄 {note['title']}")
        elif note["file_type"] == "voice":
            await callback.message.answer_voice(note["file_id"], caption=f"📄 {note['title']}")
        else:
            await callback.message.answer_document(note["file_id"], caption=f"📄 {note['title']}")
    except Exception as e:
        await callback.answer(f"❌ خطا در ارسال فایل: {e}", show_alert=True)


@router.callback_query(F.data.startswith("user_field_back:"))
async def user_field_back_handler(callback: CallbackQuery):
    """Back to field view - show subjects of the field."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    field = await models.get_field_by_id(field_id)
    if not field:
        await callback.message.edit_text(
            "📚 <b>رشته‌های تحصیلی</b>",
            reply_markup=keyboards.user_fields_keyboard(await models.get_fields()),
            parse_mode="HTML",
        )
        return

    subjects = await models.get_subjects_by_field(field_id)
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {subject['name']}",
                callback_data=f"user_subject:{subject['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu_fields"),
    )

    await callback.message.edit_text(
        f"📚 رشته: <b>{field['name']}</b>\n\n📖 <b>درس‌ها</b>:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── Search Menu ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_search")
async def menu_search_handler(callback: CallbackQuery):
    """Show search instructions."""
    await callback.answer()
    bot_username = "BotName"
    try:
        me = await callback.message.bot.get_me()
        bot_username = me.username or bot_username
    except Exception:
        pass

    await callback.message.edit_text(
        "🔎 <b>جستجوی جزوه</b>\n\n"
        "جستجو از طریق Inline Mode تلگرام انجام می‌شود.\n"
        "در هر چتی نام ربات را تایپ کنید و کلمه کلیدی را بنویسید:\n\n"
        f"<code>@{bot_username} ریاضی</code>\n\n"
        "جستجو در عنوان، توضیحات، نام رشته، درس و فصل انجام می‌شود.",
        reply_markup=await keyboards.main_menu_keyboard_for(callback.from_user.id),
        parse_mode="HTML",
    )


# Text search is REMOVED - search only works via Inline Mode
# This prevents text input from being intercepted during FSM flows


@router.callback_query(F.data == "menu_main")
async def menu_main_handler(callback: CallbackQuery):
    """Return to main menu."""
    await callback.answer()
    await callback.message.edit_text(
        "📚 <b>منوی اصلی</b>\n\n"
        "گزینه‌ای را انتخاب کنید:",
        reply_markup=await keyboards.main_menu_keyboard_for(callback.from_user.id),
        parse_mode="HTML",
    )
