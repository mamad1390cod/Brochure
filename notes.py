"""
Note submission flow handler for Bot-File-School.
Manages the step-by-step note submission process.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

import models
import keyboards
from utils import format_note_info, get_file_type_emoji, escape_html
from logger import logger

router = Router()


# ─── FSM States for Note Submission ──────────────────────────────────────────

class SubmitNoteFlow(StatesGroup):
    selecting_field = State()
    selecting_subject = State()
    selecting_chapter = State()
    entering_title = State()
    entering_description = State()
    entering_pages = State()
    sending_file = State()
    confirm = State()


# ─── Callback Handlers ──────────────────────────────────────────────────────

@router.callback_query(F.data == "submit_note_start")
async def submit_note_start_handler(callback: CallbackQuery, state: FSMContext):
    """Start the note submission flow - select field."""
    await callback.answer()
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "❌ هیچ رشته‌ای ثبت نشده است. لطفاً بعداً تلاش کنید.",
            reply_markup=await keyboards.main_menu_keyboard_for(callback.from_user.id),
        )
        return
    await state.set_state(SubmitNoteFlow.selecting_field)
    await callback.message.edit_text(
        "📚 <b>ثبت جزوه جدید</b>\n\n"
        "مرحله ۱ از ۶: رشته تحصیلی را انتخاب کنید:",
        reply_markup=keyboards.submit_field_keyboard(fields),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("submit_field:"))
async def submit_select_field(callback: CallbackQuery, state: FSMContext):
    """Field selected, now show subjects."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    field = await models.get_field_by_id(field_id)
    if not field:
        await callback.answer("❌ رشته یافت نشد!", show_alert=True)
        return

    await state.update_data(field_id=field_id, field_name=field["name"])
    subjects = await models.get_subjects_by_field(field_id)
    if not subjects:
        await callback.message.edit_text(
            f"📚 رشته: <b>{field['name']}</b>\n\n"
            f"❌ هیچ درسی برای این رشته ثبت نشده است.\n"
            f"لطفاً بعداً تلاش کنید.",
            reply_markup=keyboards.submit_field_keyboard(
                await models.get_fields()
            ),
            parse_mode="HTML",
        )
        return

    await state.set_state(SubmitNoteFlow.selecting_subject)
    await callback.message.edit_text(
        f"📚 رشته: <b>{field['name']}</b>\n\n"
        f"مرحله ۲ از ۶: درس را انتخاب کنید:",
        reply_markup=keyboards.submit_subject_keyboard(subjects, field_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("submit_subject:"))
async def submit_select_subject(callback: CallbackQuery, state: FSMContext):
    """Subject selected, now show chapters."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    if not subject:
        await callback.answer("❌ درس یافت نشد!", show_alert=True)
        return

    await state.update_data(subject_id=subject_id, subject_name=subject["name"])
    chapters = await models.get_chapters_by_subject(subject_id)

    await state.set_state(SubmitNoteFlow.selecting_chapter)
    data = await state.get_data()
    await callback.message.edit_text(
        f"📚 رشته: <b>{data.get('field_name', '')}</b>\n"
        f"📖 درس: <b>{subject['name']}</b>\n\n"
        f"مرحله ۳ از ۶: فصل را انتخاب کنید:",
        reply_markup=keyboards.submit_chapter_keyboard(chapters, subject_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("submit_chapter:"))
async def submit_select_chapter(callback: CallbackQuery, state: FSMContext):
    """Chapter selected, move to title input."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    chapter = await models.get_chapter_by_id(chapter_id)
    if not chapter:
        await callback.answer("❌ فصل یافت نشد!", show_alert=True)
        return

    await state.update_data(chapter_id=chapter_id, chapter_name=chapter["name"])
    await state.set_state(SubmitNoteFlow.entering_title)
    data = await state.get_data()
    await callback.message.edit_text(
        f"📚 رشته: <b>{data.get('field_name', '')}</b>\n"
        f"📖 درس: <b>{data.get('subject_name', '')}</b>\n"
        f"📕 فصل: <b>{chapter['name']}</b>\n\n"
        f"مرحله ۴ از ۶: عنوان جزوه را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("submit_cancel"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("submit_no_chapter:"))
async def submit_no_chapter(callback: CallbackQuery, state: FSMContext):
    """Skip chapter selection."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    await state.update_data(chapter_id=None, chapter_name=None)
    await state.set_state(SubmitNoteFlow.entering_title)
    data = await state.get_data()
    await callback.message.edit_text(
        f"📚 رشته: <b>{data.get('field_name', '')}</b>\n"
        f"📖 درس: <b>{data.get('subject_name', '')}</b>\n"
        f"📕 فصل: <b>بدون فصل</b>\n\n"
        f"مرحله ۴ از ۶: عنوان جزوه را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("submit_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SubmitNoteFlow.entering_title), F.text)
async def submit_enter_title(message: Message, state: FSMContext):
    """Title entered, move to description."""
    title = message.text.strip()
    if len(title) < 2 or len(title) > 200:
        await message.answer("❌ عنوان باید بین ۲ تا ۲۰۰ کاراکتر باشد. دوباره ارسال کنید:")
        return

    await state.update_data(title=title)
    await state.set_state(SubmitNoteFlow.entering_description)
    await message.answer(
        f"✅ عنوان: <b>{escape_html(title)}</b>\n\n"
        f"مرحله ۵ از ۶: توضیحات جزوه را ارسال کنید\n"
        f"(اختیاری - برای رد کردن عبارت «رد» را ارسال کنید):",
        reply_markup=keyboards.cancel_keyboard("submit_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SubmitNoteFlow.entering_title))
async def submit_enter_title_not_text(message: Message):
    """Ignore non-text messages during title entry."""
    await message.answer("❌ لطفاً عنوان را به‌صورت متن ارسال کنید:")


@router.message(StateFilter(SubmitNoteFlow.entering_description), F.text)
async def submit_enter_description(message: Message, state: FSMContext):
    """Description entered, move to file upload."""
    description = message.text.strip()
    if description == "رد":
        description = ""

    await state.update_data(description=description)
    await state.set_state(SubmitNoteFlow.entering_pages)
    await message.answer(
        f"✅ توضیحات: {escape_html(description) if description else 'بدون توضیحات'}\n\n"
        f"مرحله ۶ از ۶: شماره صفحات را ارسال کنید.\n\n"
        f"فرمت‌های مجاز:\n"
        f"• یک صفحه: <code>15</code>\n"
        f"• محدوده: <code>15-25</code>\n"
        f"• برای رد کردن: <code>رد</code>",
        reply_markup=keyboards.cancel_keyboard("submit_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SubmitNoteFlow.entering_description))
async def submit_enter_description_not_text(message: Message):
    """Ignore non-text messages during description entry."""
    await message.answer("❌ لطفاً توضیحات را به‌صورت متن ارسال کنید:")


@router.message(StateFilter(SubmitNoteFlow.entering_pages), F.text)
async def submit_enter_pages(message: Message, state: FSMContext):
    """Pages entered, now request file."""
    text = message.text.strip()
    page_start = None
    page_end = None

    if text != "رد":
        if "-" in text:
            parts = text.split("-", 1)
            try:
                page_start = int(parts[0].strip())
                page_end = int(parts[1].strip())
                if page_start > page_end:
                    page_start, page_end = page_end, page_start
            except ValueError:
                await message.answer("❌ فرمت نامعتبر. دوباره ارسال کنید:")
                return
        else:
            try:
                page_start = int(text)
            except ValueError:
                await message.answer("❌ فرمت نامعتبر. دوباره ارسال کنید:")
                return

    await state.update_data(page_start=page_start, page_end=page_end)
    await state.set_state(SubmitNoteFlow.sending_file)
    pages_display = (
        f"{page_start} تا {page_end}" if page_start and page_end
        else str(page_start) if page_start else "ندارد"
    )
    await message.answer(
        f"✅ صفحات: {pages_display}\n\n"
        f"📎 الآن فایل جزوه را ارسال کنید:\n"
        f"(عکس، ویدیو، PDF، یا فایل متنی)",
        reply_markup=keyboards.cancel_keyboard("submit_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SubmitNoteFlow.entering_pages))
async def submit_enter_pages_not_text(message: Message):
    """Ignore non-text messages during pages entry."""
    await message.answer("❌ لطفاً شماره صفحات را به‌صورت متن ارسال کنید:")


@router.message(StateFilter(SubmitNoteFlow.sending_file))
async def submit_receive_file(message: Message, state: FSMContext):
    """File received, save note and notify."""
    data = await state.get_data()

    # Guard against a broken/incomplete FSM session
    if not data.get("field_id") or not data.get("subject_id"):
        await state.clear()
        await message.answer(
            "❌ خطایی در جریان ثبت جزوه رخ داد. لطفاً دوباره از منوی اصلی شروع کنید:",
            reply_markup=await keyboards.main_menu_keyboard_for(message.from_user.id),
        )
        return

    # Extract file info from message
    file_id = ""
    file_unique_id = ""
    file_type = ""
    file_name = ""
    mime_type = ""
    file_size = 0

    if message.photo:
        photo = message.photo[-1]  # Largest size
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        file_type = "photo"
        file_size = photo.file_size or 0
        file_name = f"photo_{file_unique_id}.jpg"
        mime_type = "image/jpeg"
    elif message.video:
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        file_type = "video"
        file_name = message.video.file_name or f"video_{file_unique_id}.mp4"
        mime_type = message.video.mime_type or ""
        file_size = message.video.file_size or 0
    elif message.document:
        file_id = message.document.file_id
        file_unique_id = message.document.file_unique_id
        file_type = "document"
        file_name = message.document.file_name or f"document_{file_unique_id}"
        mime_type = message.document.mime_type or ""
        file_size = message.document.file_size or 0
    elif message.audio:
        file_id = message.audio.file_id
        file_unique_id = message.audio.file_unique_id
        file_type = "audio"
        file_name = message.audio.file_name or f"audio_{file_unique_id}"
        mime_type = message.audio.mime_type or ""
        file_size = message.audio.file_size or 0
    elif message.voice:
        file_id = message.voice.file_id
        file_unique_id = message.voice.file_unique_id
        file_type = "voice"
        file_name = f"voice_{file_unique_id}.ogg"
        file_size = message.voice.file_size or 0
    else:
        await message.answer(
            "❌ نوع فایل پشتیبانی نمی‌شود. لطفاً عکس، ویدیو، PDF یا فایل صوتی ارسال کنید:"
        )
        return

    # Check if user is trusted (direct save without admin approval)
    is_trusted = await models.is_allowed_user(message.from_user.id)

    # Note-submit quota (admin-configurable):
    #   note_submit_limit = "" or "free" -> unlimited (old behavior)
    #   note_submit_limit = "5"/"10"/... -> after N notes, submissions by
    #   regular users require admin approval (forced to status='pending').
    quota_forced_pending = False
    limit_raw = (await models.get_setting("note_submit_limit", "")).strip()
    if is_trusted and limit_raw and limit_raw.lower() != "free" and limit_raw.isdigit():
        from permissions import is_admin as _is_admin
        if not await _is_admin(message.from_user.id):
            used = await models.count_user_notes(message.from_user.id)
            if used >= int(limit_raw):
                is_trusted = False
                quota_forced_pending = True

    # Determine status
    status = "approved" if is_trusted else "pending"

    # Always snapshot the file into the admin notification message
    note_data_for_admin = {
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "field_name": data.get("field_name", ""),
        "subject_name": data.get("subject_name", ""),
        "chapter_name": data.get("chapter_name", "بدون فصل"),
        "page_start": data.get("page_start"),
        "page_end": data.get("page_end"),
        "file_type": file_type,
        "submitted_by_name": message.from_user.full_name or message.from_user.username or "",
        "status": status,
    }

    # Save note to database
    note_id = await models.create_note(
        title=data.get("title", ""),
        description=data.get("description", ""),
        field_id=data.get("field_id"),
        subject_id=data.get("subject_id"),
        chapter_id=data.get("chapter_id"),
        page_start=data.get("page_start"),
        page_end=data.get("page_end"),
        file_type=file_type,
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_name=file_name,
        mime_type=mime_type,
        file_size=file_size,
        submitted_by=message.from_user.id,
        submitted_by_name=message.from_user.full_name or message.from_user.username or "",
        status=status,
    )

    # Log the action
    await models.add_log(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        action="submit_note",
        details=f"Note #{note_id}: {data.get('title')} (status: {status})",
    )

    await state.clear()

    if is_trusted:
        # Auto-approved
        await message.answer(
            f"✅ <b>جزوه با موفقیت ثبت شد!</b>\n\n"
            f"📄 {data.get('title')}\n"
            f"📚 {data.get('field_name', '')} → 📖 {data.get('subject_name', '')}\n"
            f"📕 {data.get('chapter_name', 'بدون فصل')}\n\n"
            f"با توجه به دسترسی ویژه شما، جزوه بدون نیاز به تأیید ثبت شد.",
            reply_markup=await keyboards.main_menu_keyboard_for(message.from_user.id),
            parse_mode="HTML",
        )

        # Notify all admins (informational, auto-approved)
        from config import MAIN_ADMIN_ID
        from handlers import bot
        info_text = (
            f"ℹ️ <b>جزوه بدون تأیید ثبت شد</b>\n\n"
            f"👤 کاربر: {message.from_user.full_name or message.from_user.username}\n"
            f"🆔 Chat ID: <code>{message.from_user.id}</code>\n\n"
            f"{format_note_info(note_data_for_admin)}"
        )
        try:
            for aid in {MAIN_ADMIN_ID, *[a["user_id"] for a in await models.get_all_admins()]}:
                try:
                    await bot.send_message(aid, info_text, parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            pass
    else:
        # Pending approval
        quota_note = (
            f"\n📊 سقف ثبت جزوه بدون تأیید پر شده است "
            f"({limit_raw} جزوه)؛ این جزوه نیازمند تأیید ادمین است."
            if quota_forced_pending else ""
        )
        await message.answer(
            f"✅ <b>جزوه ثبت شد!</b>\n\n"
            f"📄 {data.get('title')}\n"
            f"📚 {data.get('field_name', '')} → 📖 {data.get('subject_name', '')}\n"
            f"📕 {data.get('chapter_name', 'بدون فصل')}\n\n"
            f"⏳ جزوه شما به ادمین ارسال شد و پس از تأیید قابل مشاهده خواهد بود."
            f"{quota_note}",
            reply_markup=await keyboards.main_menu_keyboard_for(message.from_user.id),
            parse_mode="HTML",
        )

        # Send to every admin for approval - including the file itself
        from config import MAIN_ADMIN_ID
        from handlers import bot
        admin_text = (
            f"📬 <b>جزوه جدید در انتظار تأیید</b>\n\n"
            f"👤 ارسال‌کننده: {message.from_user.full_name or message.from_user.username}\n"
            f"🆔 Chat ID: <code>{message.from_user.id}</code>\n\n"
            f"{format_note_info(note_data_for_admin)}"
        )
        all_admin_ids = {MAIN_ADMIN_ID, *[a["user_id"] for a in await models.get_all_admins()]}
        for aid in all_admin_ids:
            try:
                sent = await bot.send_message(
                    aid,
                    admin_text,
                    reply_markup=keyboards.note_approval_keyboard(note_id),
                    parse_mode="HTML",
                )
                # Attach the actual file right under the approval message
                try:
                    if file_type == "photo":
                        await bot.send_photo(aid, file_id, caption=f"📎 فایل جزوه: {data.get('title')}")
                    elif file_type == "video":
                        await bot.send_video(aid, file_id, caption=f"📎 فایل جزوه: {data.get('title')}")
                    else:
                        await bot.send_document(aid, file_id, caption=f"📎 فایل جزوه: {data.get('title')}")
                except Exception:
                    pass
            except Exception:
                pass

    logger.info(f"Note #{note_id} submitted by user {message.from_user.id}: {data.get('title')}")


@router.callback_query(F.data == "submit_cancel")
async def submit_cancel_handler(callback: CallbackQuery, state: FSMContext):
    """Cancel note submission."""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "❌ ثبت جزوه لغو شد.",
        reply_markup=await keyboards.main_menu_keyboard_for(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("submit_back_subject:"))
async def submit_back_subject_handler(callback: CallbackQuery, state: FSMContext):
    """Go back to subject selection during submission."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    if subject:
        await state.set_state(SubmitNoteFlow.selecting_subject)
        data = await state.get_data()
        await callback.message.edit_text(
            f"📚 رشته: <b>{data.get('field_name', '')}</b>\n\n"
            f"مرحله ۲ از ۶: درس را انتخاب کنید:",
            reply_markup=keyboards.submit_subject_keyboard(
                await models.get_subjects_by_field(data.get("field_id", 0)),
                data.get("field_id", 0),
            ),
            parse_mode="HTML",
        )
