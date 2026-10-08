"""
Admin panel handlers for Bot-File-School.
Handles admin authentication, management, and all admin operations.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

import secrets

import models
import keyboards
import security
from config import MAIN_ADMIN_ID, ADMIN_PASSWORD, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES
from permissions import check_permission, is_admin, is_main_admin, is_owner, PERMISSIONS, DEFAULT_ADMIN_PERMISSIONS
from utils import format_note_info, format_page_range, escape_html
from middleware import AdminAuthMiddleware
from logger import logger
import convert
from pathlib import Path

router = Router()

# Guard every handler on this router: authentication + permissions
router.callback_query.middleware(AdminAuthMiddleware())
router.message.middleware(AdminAuthMiddleware())


# ─── FSM States ───────────────────────────────────────────────────────────────

class AdminLogin(StatesGroup):
    waiting_password = State()


class AdminAddFlow(StatesGroup):
    entering_user_id = State()
    entering_username = State()
    entering_full_name = State()
    entering_password = State()


class FieldAddFlow(StatesGroup):
    entering_name = State()


class FieldEditFlow(StatesGroup):
    entering_name = State()


class SubjectAddFlow(StatesGroup):
    entering_name = State()


class SubjectEditFlow(StatesGroup):
    entering_name = State()


class ChapterAddFlow(StatesGroup):
    entering_name = State()


class ChapterEditFlow(StatesGroup):
    entering_name = State()


class NoteEditFlow(StatesGroup):
    entering_title = State()
    entering_description = State()
    entering_pages = State()


class PasswordChangeFlow(StatesGroup):
    entering_password = State()


class AllowedUserAddFlow(StatesGroup):
    entering_user_id = State()
    entering_name = State()


class SchedEditFlow(StatesGroup):
    waiting_content = State()   # entering text for one schedule cell (day list)
    waiting_single_cell = State()  # entering text for one exact cell


class AdminConvertFlow(StatesGroup):
    waiting_files = State()     # admin collects images or docs
    entering_name = State()


class OnlineClassFlow(StatesGroup):
    waiting_title = State()
    waiting_time = State()
    waiting_link = State()


class ChapterSearchFlow(StatesGroup):
    waiting_query = State()


class NoteLimitFlow(StatesGroup):
    waiting_number = State()


class ClassEditFlow(StatesGroup):
    waiting_value = State()   # generic single-value edit (title/time/...)


# ─── Admin Authentication ────────────────────────────────────────────────────

async def _ensure_owner_in_db(user_id: int, user) -> None:
    """Make sure an owner (main or DB-flagged) has a DB admin row."""
    admin = await models.get_admin_by_user_id(user_id)
    if not admin:
        from security import hash_password
        await models.create_admin(
            user_id=user_id,
            username=user.username or "",
            full_name=user.full_name or "",
            password_hash=hash_password(ADMIN_PASSWORD),
            is_main_admin=True,
        )
        admin = await models.get_admin_by_user_id(user_id)
        await models.set_admin_permissions(admin["id"], list(PERMISSIONS.keys()))


@router.callback_query(F.data == "admin_login")
async def admin_login_handler(callback: CallbackQuery, state: FSMContext):
    """Start admin login flow.
    Owner (MAIN_ADMIN_ID or DB is_main_admin) skips the password form
    entirely - identity is verified by Telegram user ID + project config."""
    await callback.answer()

    user_id = callback.from_user.id

    # Already authenticated in this session - go straight to panel
    if security.admin_sessions.is_authenticated(user_id):
        await callback.message.edit_text(
            "✅ <b>پنل مدیریت</b>\n\n"
            "به پنل مدیریت خوش آمدید!",
            reply_markup=await keyboards.admin_main_menu_keyboard_for(user_id),
            parse_mode="HTML",
        )
        return

    # ── Owner auto-login: no password, no button flow ──
    if await is_owner(user_id):
        await _ensure_owner_in_db(user_id, callback.from_user)
        security.admin_sessions.login(user_id)
        security.rate_limiter.reset(user_id)
        await callback.message.edit_text(
            "👑 <b>پنل مدیریت (Owner)</b>\n\n"
            "به عنوان Owner شناسایی شدید — ورود مستقیم بدون رمز.",
            reply_markup=await keyboards.admin_main_menu_keyboard_for(user_id),
            parse_mode="HTML",
        )
        logger.info(f"Owner auto-login: {user_id}")
        return

    # Check rate limiting
    if security.rate_limiter.is_locked(user_id):
        remaining = security.rate_limiter.get_remaining_time(user_id)
        await callback.answer(
            f"🔒 حساب شما قفل شده است. {remaining} ثانیه دیگر تلاش کنید.",
            show_alert=True,
        )
        return

    await state.set_state(AdminLogin.waiting_password)
    await callback.message.edit_text(
        "🔐 <b>ورود به پنل مدیریت</b>\n\n"
        "لطفاً رمز عبور ادمین را ارسال کنید\n"
        "<i>(حروف بزرگ/کوچک تفاوتی ندارد):</i>",
        reply_markup=keyboards.cancel_keyboard("admin_login"),
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminLogin.waiting_password))
async def admin_login_password(message: Message, state: FSMContext):
    """Verify admin password."""
    user_id = message.from_user.id
    password = message.text.strip()

    # Check if this is the main admin (case-insensitive password compare)
    if user_id == MAIN_ADMIN_ID:
        if secrets.compare_digest(password.casefold(), ADMIN_PASSWORD.casefold()):
            security.rate_limiter.reset(user_id)
            security.admin_sessions.login(user_id)
            await state.clear()
            try:
                await message.delete()  # Do not keep the password in chat history
            except Exception:
                pass
            # Ensure main admin exists in DB
            admin = await models.get_admin_by_user_id(user_id)
            if not admin:
                from security import hash_password
                await models.create_admin(
                    user_id=user_id,
                    username=message.from_user.username or "",
                    full_name=message.from_user.full_name or "",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    is_main_admin=True,
                )
                # Grant all permissions
                admin = await models.get_admin_by_user_id(user_id)
                await models.set_admin_permissions(admin["id"], list(PERMISSIONS.keys()))
            await message.answer(
                "✅ <b>ورود موفق!</b>\n\n"
                "ادمین اصلی، به پنل مدیریت خوش آمدید!",
                reply_markup=keyboards.admin_main_menu_keyboard(),
                parse_mode="HTML",
            )
            logger.info(f"Main admin logged in: {user_id}")
            return
        else:
            security.rate_limiter.record_attempt(user_id)
            attempts_left = MAX_LOGIN_ATTEMPTS - (
                security.rate_limiter._attempts.get(user_id, (0, 0))[0]
                if user_id in security.rate_limiter._attempts else 0
            )
            await message.answer(
                f"❌ رمز اشتباه است. ({attempts_left} تلاش باقی‌مانده)\n"
                f"دوباره وارد کنید:",
            )
            return

    # Check database admin
    admin = await models.get_admin_by_user_id(user_id)
    if admin and security.verify_password(password, admin["password_hash"]):
        security.rate_limiter.reset(user_id)
        security.admin_sessions.login(user_id)
        await state.clear()
        try:
            await message.delete()  # Do not keep the password in chat history
        except Exception:
            pass
        await message.answer(
            "✅ <b>ورود موفق!</b>\n\n"
            + ("👑 Owner، به پنل مدیریت خوش آمدید!"
               if admin["is_main_admin"] else "به پنل مدیریت خوش آمدید!"),
            reply_markup=keyboards.admin_main_menu_keyboard(),
            parse_mode="HTML",
        )
        logger.info(f"Admin logged in: {user_id} ({admin['username']})")
    else:
        security.rate_limiter.record_attempt(user_id)
        remaining_attempts = MAX_LOGIN_ATTEMPTS - (
            security.rate_limiter._attempts.get(user_id, (0, 0))[0]
            if user_id in security.rate_limiter._attempts else 0
        )
        if remaining_attempts <= 0:
            await message.answer(
                "🔒 حساب شما به دلیل تلاش‌های مکرر قفل شده است.\n"
                f"لطفاً {LOGIN_LOCKOUT_MINUTES} دقیقه دیگر تلاش کنید."
            )
            await state.clear()
        else:
            await message.answer(
                f"❌ رمز اشتباه است. ({remaining_attempts} تلاش باقی‌مانده)\n"
                f"دوباره وارد کنید:"
            )


@router.callback_query(F.data == "admin_logout")
async def admin_logout_handler(callback: CallbackQuery, state: FSMContext):
    """Logout from admin panel."""
    await callback.answer()
    await state.clear()
    security.admin_sessions.logout(callback.from_user.id)
    await callback.message.edit_text(
        "👋 از پنل مدیریت خارج شدید.",
        reply_markup=keyboards.main_menu_keyboard(),
    )


# ─── Field Management (Admin) ────────────────────────────────────────────────

@router.callback_query(F.data == "admin_fields")
async def admin_fields_handler(callback: CallbackQuery):
    """Show field management."""
    await callback.answer()
    fields = await models.get_fields()
    await callback.message.edit_text(
        "📚 <b>مدیریت رشته‌ها</b>\n\n"
        "رشته موردنظر را انتخاب کنید:",
        reply_markup=keyboards.fields_list_keyboard(fields),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("field_view:"))
async def field_view_handler(callback: CallbackQuery):
    """View a specific field."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    field = await models.get_field_by_id(field_id)
    if not field:
        await callback.answer("❌ رشته یافت نشد!", show_alert=True)
        return

    subjects_count = len(await models.get_subjects_by_field(field_id))
    notes_count = await models.count_notes(status="approved", field_id=field_id)

    await callback.message.edit_text(
        f"📚 <b>{field['name']}</b>\n\n"
        f"📖 تعداد درس‌ها: {subjects_count}\n"
        f"📄 تعداد جزوه‌ها: {notes_count}",
        reply_markup=keyboards.field_detail_keyboard(field_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "field_add")
async def field_add_handler(callback: CallbackQuery, state: FSMContext):
    """Add new field(s) - each line = one field."""
    await callback.answer()
    await state.set_state(FieldAddFlow.entering_name)
    await callback.message.edit_text(
        "➕ <b>افزودن رشته جدید</b>\n\n"
        "نام رشته تحصیلی را ارسال کنید.\n"
        "هر خط = یک رشته جداگانه:\n\n"
        "ریاضی\n"
        "تجربی\n"
        "انسانی",
        reply_markup=keyboards.cancel_keyboard("admin_fields"),
        parse_mode="HTML",
    )


@router.message(StateFilter(FieldAddFlow.entering_name))
async def field_add_name(message: Message, state: FSMContext):
    """Save new field name - supports bulk import with comma or space separation."""
    text = message.text.strip()

    # Split by newlines (Enter) or commas
    import re
    names = [n.strip() for n in re.split(r'[,،\n]+', text) if n.strip()]

    if not names:
        await message.answer("❌ لطفاً حداقل یک نام وارد کنید:")
        return

    # Validate all names
    for name in names:
        if len(name) < 2:
            await message.answer(f"❌ نام «{name}» باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
            return

    # Create all fields
    created = []
    for name in names:
        field_id = await models.create_field(name)
        created.append((field_id, name))

    await state.clear()

    # Show buttons for each created field
    kb = InlineKeyboardBuilder()
    for fid, name in created:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {name}",
                callback_data=f"field_view:{fid}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_fields"),
    )

    names_text = "\n".join(f"  📚 {escape_html(n)}" for _, n in created)
    await message.answer(
        f"✅ <b>{len(created)} رشته با موفقیت اضافه شد:</b>\n\n"
        f"{names_text}",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "add_field", f"Fields: {', '.join(n for _, n in created)}"
    )
    logger.info(f"Fields added: {created} by admin {message.from_user.id}")


@router.callback_query(F.data.startswith("field_edit:"))
async def field_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Edit a field name."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    await state.update_data(edit_field_id=field_id)
    await state.set_state(FieldEditFlow.entering_name)
    await callback.message.edit_text(
        "✏️ <b>ویرایش رشته</b>\n\n"
        "نام جدید را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard(f"field_view:{field_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(FieldEditFlow.entering_name))
async def field_edit_name(message: Message, state: FSMContext):
    """Save edited field name."""
    name = message.text.strip()
    data = await state.get_data()
    field_id = data.get("edit_field_id")

    if len(name) < 2:
        await message.answer("❌ نام باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
        return

    await models.update_field(field_id, name)
    await state.clear()
    await message.answer(
        f"✅ رشته به «<b>{escape_html(name)}</b>» ویرایش شد.",
        reply_markup=keyboards.fields_list_keyboard(await models.get_fields()),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "edit_field", f"Field #{field_id}: {name}"
    )


@router.callback_query(F.data.startswith("field_delete:"))
async def field_delete_handler(callback: CallbackQuery):
    """Delete a single field."""
    field_id = int(callback.data.split(":")[1])
    field = await models.get_field_by_id(field_id)
    if not field:
        await callback.answer("❌ رشته یافت نشد!", show_alert=True)
        return

    await models.delete_field(field_id)
    await callback.answer(f"🗑 رشته «{field['name']}» حذف شد.", show_alert=True)

    # Show updated list
    fields = await models.get_fields()
    await callback.message.edit_text(
        "📚 <b>مدیریت رشته‌ها</b>\n\nرشته موردنظر را انتخاب کنید:",
        reply_markup=keyboards.fields_list_keyboard(fields),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "delete_field", f"Field: {field['name']}"
    )
    logger.info(f"Field deleted: {field['name']} by admin {callback.from_user.id}")


# ─── Bulk Delete (Fields) ────────────────────────────────────────────────────

@router.callback_query(F.data == "field_bulk_delete")
async def field_bulk_delete_handler(callback: CallbackQuery, state: FSMContext):
    """Show bulk delete interface for fields."""
    await callback.answer()
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "📚 هیچ رشته‌ای وجود ندارد.",
            reply_markup=keyboards.fields_list_keyboard(fields),
            parse_mode="HTML",
        )
        return

    await state.set_data({"bulk_delete_fields": []})
    await callback.message.edit_text(
        "🗑 <b>حذف گروهی رشته‌ها</b>\n\n"
        "رشته‌ای را که می‌خواهید حذف کنید انتخاب کنید:\n"
        "(با کلیک روی نام، علامت ✅ می‌گیرد)",
        reply_markup=keyboards.field_bulk_delete_keyboard(fields),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("field_toggle_delete:"))
async def field_toggle_delete_handler(callback: CallbackQuery, state: FSMContext):
    """Toggle field selection for bulk delete."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("bulk_delete_fields", [])

    if field_id in selected:
        selected.remove(field_id)
    else:
        selected.append(field_id)

    await state.update_data({"bulk_delete_fields": selected})

    # Update keyboard to show selection
    fields = await models.get_fields()
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🗑 حذف همه", callback_data="field_delete_all"),
    )
    for field in fields:
        check = "✅" if field["id"] in selected else "⬜"
        kb.row(
            InlineKeyboardButton(
                text=f"{check} {field['name']}",
                callback_data=f"field_toggle_delete:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text=f"🗑 حذف ({len(selected)})", callback_data="field_confirm_bulk_delete"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_fields"),
    )

    await callback.message.edit_reply_markup(reply_markup=kb.as_markup())


@router.callback_query(F.data == "field_delete_all")
async def field_delete_all_handler(callback: CallbackQuery, state: FSMContext):
    """Delete all fields."""
    await callback.answer()
    fields = await models.get_fields(active_only=False)
    field_ids = [f["id"] for f in fields]

    for fid in field_ids:
        await models.delete_field(fid)

    await state.clear()
    await callback.message.edit_text(
        f"🗑 تمام {len(field_ids)} رشته حذف شد.",
        reply_markup=keyboards.fields_list_keyboard(await models.get_fields()),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "delete_all_fields", f"Count: {len(field_ids)}"
    )


@router.callback_query(F.data == "field_confirm_bulk_delete")
async def field_confirm_bulk_delete_handler(callback: CallbackQuery, state: FSMContext):
    """Confirm and execute bulk field deletion."""
    await callback.answer()
    data = await state.get_data()
    selected = data.get("bulk_delete_fields", [])

    if not selected:
        await callback.answer("❌ هیچ رشته‌ای انتخاب نشده!", show_alert=True)
        return

    deleted_count = 0
    for fid in selected:
        field = await models.get_field_by_id(fid)
        if field:
            await models.delete_field(fid)
            deleted_count += 1

    await state.clear()
    await callback.message.edit_text(
        f"🗑 <b>{deleted_count} رشته انتخاب‌شده حذف شد.</b>",
        reply_markup=keyboards.fields_list_keyboard(await models.get_fields()),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "bulk_delete_fields", f"Count: {deleted_count}"
    )


# ─── Subject Management (Admin - Direct) ─────────────────────────────────────

@router.callback_query(F.data == "admin_subjects")
async def admin_subjects_handler(callback: CallbackQuery):
    """Show all fields to select one for subject management."""
    await callback.answer()
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "📚 هیچ رشته‌ای ثبت نشده است. ابتدا رشته اضافه کنید.",
            reply_markup=keyboards.admin_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}",
                callback_data=f"field_subjects:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"),
    )
    await callback.message.edit_text(
        "📖 <b>مدیریت درس‌ها</b>\n\n"
        "رشته‌ای را که می‌خواهید درس‌های آن را مدیریت کنید انتخاب کنید:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── Chapter Management (Admin - Direct) ─────────────────────────────────────

@router.callback_query(F.data == "admin_chapters")
async def admin_chapters_handler(callback: CallbackQuery):
    """Show all fields to select one for chapter management."""
    await callback.answer()
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "📚 هیچ رشته‌ای ثبت نشده است. ابتدا رشته اضافه کنید.",
            reply_markup=keyboards.admin_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}",
                callback_data=f"admin_chapters_field:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"),
    )
    await callback.message.edit_text(
        "📕 <b>مدیریت فصل‌ها</b>\n\n"
        "رشته‌ای را که می‌خواهید فصل‌های آن را مدیریت کنید انتخاب کنید:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_chapters_field:"))
async def admin_chapters_field_handler(callback: CallbackQuery):
    """Show subjects for chapter management."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    subjects = await models.get_subjects_by_field(field_id)
    if not subjects:
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_chapters"),
        )
        await callback.message.edit_text(
            "📖 هیچ درسی ثبت نشده است.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {subject['name']}",
                callback_data=f"subject_chapters:{subject['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_chapters"),
    )
    await callback.message.edit_text(
        "📕 <b>مدیریت فصل‌ها</b>\n\n"
        "درس موردنظر را انتخاب کنید:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── Subject Notes View ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("subject_notes:"))
async def subject_notes_handler(callback: CallbackQuery):
    """Show notes for a subject."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    if not subject:
        await callback.answer("❌ درس یافت نشد!", show_alert=True)
        return

    notes = await models.get_approved_notes(subject_id=subject_id, limit=20)
    kb = InlineKeyboardBuilder()
    for note in notes:
        title = note["title"][:30] + "..." if len(note["title"]) > 30 else note["title"]
        kb.row(
            InlineKeyboardButton(
                text=f"📄 {title}",
                callback_data=f"note_view:{note['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"subject_view:{subject_id}"),
    )

    await callback.message.edit_text(
        f"📖 درس: <b>{subject['name']}</b>\n\n"
        f"📄 جزوه‌ها ({len(notes)}):",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── Chapter Notes View ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("chapter_notes:"))
async def chapter_notes_handler(callback: CallbackQuery):
    """Show notes for a chapter."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    chapter = await models.get_chapter_by_id(chapter_id)
    if not chapter:
        await callback.answer("❌ فصل یافت نشد!", show_alert=True)
        return

    notes = await models.get_approved_notes(chapter_id=chapter_id, limit=200)
    kb = InlineKeyboardBuilder()
    if not notes:
        kb.row(InlineKeyboardButton(text="⚪ فایلی در این فصل نیست", callback_data="noop"))
    for note in notes:
        from utils import note_file_label
        kb.row(
            InlineKeyboardButton(
                text=note_file_label(note),
                callback_data=f"note_view:{note['id']}",
            )
        )
    if notes:
        kb.row(InlineKeyboardButton(text="🔍 جستجوی فایل", callback_data=f"chapter_search:{chapter_id}"))
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"chapter_view:{chapter_id}"),
    )

    await callback.message.edit_text(
        f"📕 فصل: <b>{chapter['name']}</b>\n\n"
        f"📁 همه فایل‌ها ({len(notes)}) — نام | حجم:\n"
        f"<i>روی فایل کلیک کنید تا جزئیات و دانلود نمایش داده شود</i>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("chapter_search:"))
async def chapter_search_start(callback: CallbackQuery, state: FSMContext):
    """Ask for a file-name search query inside this chapter."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    await state.set_state(ChapterSearchFlow.waiting_query)
    await state.update_data(search_chapter_id=chapter_id)
    await callback.message.edit_text(
        "🔍 <b>جستجوی فایل در فصل</b>\n\n"
        "نام یا بخشی از نام فایل را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("chapter_notes:" + str(chapter_id)),
        parse_mode="HTML",
    )


@router.message(StateFilter(ChapterSearchFlow.waiting_query), F.text)
async def chapter_search_query(message: Message, state: FSMContext):
    query = message.text.strip()[:100]
    data = await state.get_data()
    chapter_id = int(data.get("search_chapter_id", 0))
    await state.clear()
    chapter = await models.get_chapter_by_id(chapter_id)
    notes = await models.search_chapter_notes(chapter_id, query, approved_only=False)
    kb = InlineKeyboardBuilder()
    if not notes:
        kb.row(InlineKeyboardButton(
            text=f"⚪ نتیجه‌ای برای «{query[:20]}» نیست", callback_data="noop"))
    for note in notes:
        from utils import note_file_label
        kb.row(InlineKeyboardButton(
            text=note_file_label(note),
            callback_data=f"note_view:{note['id']}",
        ))
    kb.row(InlineKeyboardButton(text="🔄 همه فایل‌ها", callback_data=f"chapter_notes:{chapter_id}"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"chapter_view:{chapter_id}"))
    await message.answer(
        f"🔍 جستجوی «{escape_html(query)}» در فصل "
        f"<b>{escape_html(chapter['name'] if chapter else '')}</b>\n\n"
        f"📁 {len(notes)} فایل پیدا شد:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── Note Edit (Admin) ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("note_edit:"))
async def note_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Edit a note - title."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    await state.update_data(edit_note_id=note_id)
    await state.set_state(NoteEditFlow.entering_title)
    await callback.message.edit_text(
        f"✏️ <b>ویرایش جزوه</b>\n\n"
        f"عنوان فعلی: <b>{note['title']}</b>\n\n"
        f"عنوان جدید را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard(f"note_view:{note_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(NoteEditFlow.entering_title))
async def note_edit_title(message: Message, state: FSMContext):
    """Save new title."""
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("❌ عنوان باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
        return

    data = await state.get_data()
    note_id = data.get("edit_note_id")
    await models.update_note(note_id, title=title)
    await state.clear()

    await message.answer(
        f"✅ عنوان جزوه به «<b>{escape_html(title)}</b>» تغییر یافت.",
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "edit_note", f"Note #{note_id}: new title '{title}'"
    )


# ─── Settings: Inline Search ─────────────────────────────────────────────────

@router.callback_query(F.data == "setting_inline")
async def setting_inline_handler(callback: CallbackQuery):
    """Show inline search settings."""
    await callback.answer()
    from config import ENABLE_INLINE_SEARCH, INLINE_SEARCH_ALLOWED_USERS
    status = "🟢 فعال" if ENABLE_INLINE_SEARCH else "🔴 غیرفعال"
    users = ", ".join(INLINE_SEARCH_ALLOWED_USERS) if INLINE_SEARCH_ALLOWED_USERS else "همه کاربران"

    await callback.message.edit_text(
        f"🔎 <b>تنظیمات جستجوی Inline</b>\n\n"
        f"وضعیت: {status}\n"
        f"کاربران مجاز: {users}\n\n"
        f"برای تغییر تنظیمات فایل .env را ویرایش کنید.",
        reply_markup=keyboards.settings_keyboard(),
        parse_mode="HTML",
    )


# ─── Allowed User Add ────────────────────────────────────────────────────────

@router.callback_query(F.data == "allowed_user_add")
async def allowed_user_add_handler(callback: CallbackQuery, state: FSMContext):
    """Add a trusted user."""
    await callback.answer()
    await state.set_state(AllowedUserAddFlow.entering_user_id)
    await callback.message.edit_text(
        "➕ <b>افزودن کاربر مجاز</b>\n\n"
        "Telegram ID (عددی) کاربر را ارسال کنید:\n"
        "(کاربر مجاز می‌تواند بدون تأیید ادمین جزوه ثبت کند)",
        reply_markup=keyboards.cancel_keyboard("admin_users"),
        parse_mode="HTML",
    )


@router.message(StateFilter(AllowedUserAddFlow.entering_user_id))
async def allowed_user_id_received(message: Message, state: FSMContext):
    """Get user ID and ask for name."""
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID باید عددی باشد. دوباره ارسال کنید:")
        return

    # Check if already exists
    users = await models.get_allowed_users()
    if any(u["user_id"] == user_id for u in users):
        await message.answer("❌ این کاربر از قبل در لیست مجاز است. ID دیگری ارسال کنید:")
        return

    await state.update_data(new_allowed_user_id=user_id)
    await state.set_state(AllowedUserAddFlow.entering_name)
    await message.answer(
        f"✅ ID: <code>{user_id}</code>\n\n"
        "حالا نام کاربر را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("admin_users"),
        parse_mode="HTML",
    )


@router.message(StateFilter(AllowedUserAddFlow.entering_name))
async def allowed_user_name_received(message: Message, state: FSMContext):
    """Get name and save allowed user."""
    name = message.text.strip()
    data = await state.get_data()
    user_id = data.get("new_allowed_user_id")

    await models.add_allowed_user(
        user_id=user_id,
        username="",
        full_name=name,
        added_by=message.from_user.id,
    )

    await state.clear()
    await message.answer(
        f"✅ کاربر «<b>{escape_html(name)}</b>» (ID: <code>{user_id}</code>) به لیست کاربران مجاز اضافه شد.",
        reply_markup=keyboards.users_management_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "add_allowed_user",
        f"User {user_id}: {name}"
    )


# ─── Subject Management (Admin) ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("field_subjects:"))
async def field_subjects_handler(callback: CallbackQuery):
    """Show subjects for a field."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    field = await models.get_field_by_id(field_id)
    subjects = await models.get_subjects_by_field(field_id)

    kb = keyboards.subjects_list_keyboard(subjects, field_id)
    await callback.message.edit_text(
        f"📚 رشته: <b>{field['name']}</b>\n\n"
        f"📖 <b>درس‌ها</b>:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("subject_add:"))
async def subject_add_handler(callback: CallbackQuery, state: FSMContext):
    """Add subject(s) to a field - supports bulk import."""
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    await state.update_data(add_subject_field_id=field_id)
    await state.set_state(SubjectAddFlow.entering_name)
    await callback.message.edit_text(
        "➕ <b>افزودن درس جدید</b>\n\n"
        "نام درس را ارسال کنید.\n"
        "برای افزودن چند درس با کاما (,) یا خط جدید جدا کنید:\n\n"
        "مثال: فارسی، ریاضی، فیزیک",
        reply_markup=keyboards.cancel_keyboard(f"field_view:{field_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SubjectAddFlow.entering_name))
async def subject_add_name(message: Message, state: FSMContext):
    """Save new subject(s) - supports bulk import."""
    text = message.text.strip()
    data = await state.get_data()
    field_id = data.get("add_subject_field_id")

    # Split by comma or newlines
    import re
    names = [n.strip() for n in re.split(r'[,،\n]+', text) if n.strip()]

    if not names:
        await message.answer("❌ لطفاً حداقل یک نام وارد کنید:")
        return

    for name in names:
        if len(name) < 2:
            await message.answer(f"❌ نام «{name}» باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
            return

    created = []
    for name in names:
        subject_id = await models.create_subject(field_id, name)
        created.append((subject_id, name))

    field = await models.get_field_by_id(field_id)
    await state.clear()

    # Show buttons for each created subject
    kb = InlineKeyboardBuilder()
    for sid, name in created:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {name}",
                callback_data=f"subject_view:{sid}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"field_subjects:{field_id}"),
    )

    names_text = "\n".join(f"  📖 {escape_html(n)}" for _, n in created)
    await message.answer(
        f"✅ <b>{len(created)} درس به رشته «{escape_html(field['name'])}» اضافه شد:</b>\n\n"
        f"{names_text}",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "add_subject", f"Subjects: {', '.join(n for _, n in created)}"
    )


@router.callback_query(F.data.startswith("subject_view:"))
async def subject_view_handler(callback: CallbackQuery):
    """View a subject."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    if not subject:
        await callback.answer("❌ درس یافت نشد!", show_alert=True)
        return

    chapters_count = len(await models.get_chapters_by_subject(subject_id))
    notes_count = await models.count_notes(status="approved", subject_id=subject_id)

    await callback.message.edit_text(
        f"📖 <b>{subject['name']}</b>\n\n"
        f"📕 تعداد فصل‌ها: {chapters_count}\n"
        f"📄 تعداد جزوه‌ها: {notes_count}",
        reply_markup=keyboards.subject_detail_keyboard(subject_id, subject["field_id"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("subject_edit:"))
async def subject_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Edit a subject."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    await state.update_data(edit_subject_id=subject_id)
    await state.set_state(SubjectEditFlow.entering_name)
    await callback.message.edit_text(
        "✏️ <b>ویرایش درس</b>\n\n"
        "نام جدید را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard(f"subject_view:{subject_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SubjectEditFlow.entering_name))
async def subject_edit_name(message: Message, state: FSMContext):
    """Save edited subject."""
    name = message.text.strip()
    data = await state.get_data()
    subject_id = data.get("edit_subject_id")

    if len(name) < 2:
        await message.answer("❌ نام باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
        return

    subject = await models.get_subject_by_id(subject_id)
    await models.update_subject(subject_id, name)
    await state.clear()
    await message.answer(
        f"✅ درس به «<b>{escape_html(name)}</b>» ویرایش شد.",
        reply_markup=keyboards.subject_detail_keyboard(subject_id, subject["field_id"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("subject_delete:"))
async def subject_delete_handler(callback: CallbackQuery):
    """Delete a single subject."""
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    if not subject:
        await callback.answer("❌ درس یافت نشد!", show_alert=True)
        return

    await models.delete_subject(subject_id)
    await callback.answer(f"🗑 درس «{subject['name']}» حذف شد.", show_alert=True)

    # Show updated list
    field = await models.get_field_by_id(subject["field_id"])
    subjects = await models.get_subjects_by_field(subject["field_id"])
    await callback.message.edit_text(
        f"📚 رشته: <b>{field['name']}</b>\n\n📖 <b>درس‌ها</b>:",
        reply_markup=keyboards.subjects_list_keyboard(subjects, subject["field_id"]).as_markup(),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "delete_subject", f"Subject: {subject['name']}"
    )


# ─── Chapter Management (Admin) ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("subject_chapters:"))
async def subject_chapters_handler(callback: CallbackQuery):
    """Show chapters for a subject."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    subject = await models.get_subject_by_id(subject_id)
    chapters = await models.get_chapters_by_subject(subject_id)

    await callback.message.edit_text(
        f"📖 درس: <b>{subject['name']}</b>\n\n"
        f"📕 <b>فصل‌ها</b>:",
        reply_markup=keyboards.chapters_list_keyboard(chapters, subject_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("chapter_add:"))
async def chapter_add_handler(callback: CallbackQuery, state: FSMContext):
    """Add chapter(s) to a subject - supports bulk import."""
    await callback.answer()
    subject_id = int(callback.data.split(":")[1])
    await state.update_data(add_chapter_subject_id=subject_id)
    await state.set_state(ChapterAddFlow.entering_name)
    await callback.message.edit_text(
        "➕ <b>افزودن فصل جدید</b>\n\n"
        "نام فصل را ارسال کنید.\n"
        "برای افزودن چند فصل با کاما (,) یا خط جدید جدا کنید:\n\n"
        "مثال: فصل اول، فصل دوم، فصل سوم",
        reply_markup=keyboards.cancel_keyboard(f"subject_view:{callback.data.split(':')[1]}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(ChapterAddFlow.entering_name))
async def chapter_add_name(message: Message, state: FSMContext):
    """Save new chapter(s) - supports bulk import."""
    text = message.text.strip()
    data = await state.get_data()
    subject_id = data.get("add_chapter_subject_id")

    # Split by comma or newlines
    import re
    names = [n.strip() for n in re.split(r'[,،\n]+', text) if n.strip()]

    if not names:
        await message.answer("❌ لطفاً حداقل یک نام وارد کنید:")
        return

    for name in names:
        if len(name) < 2:
            await message.answer(f"❌ نام «{name}» باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
            return

    created = []
    for name in names:
        chapters = await models.get_chapters_by_subject(subject_id)
        chapter_id = await models.create_chapter(subject_id, name, sort_order=len(chapters))
        created.append((chapter_id, name))

    subject = await models.get_subject_by_id(subject_id)
    await state.clear()

    # Show buttons for each created chapter
    kb = InlineKeyboardBuilder()
    for cid, name in created:
        kb.row(
            InlineKeyboardButton(
                text=f"📕 {name}",
                callback_data=f"chapter_view:{cid}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"subject_chapters:{subject_id}"),
    )

    names_text = "\n".join(f"  📕 {escape_html(n)}" for _, n in created)
    await message.answer(
        f"✅ <b>{len(created)} فصل به درس «{escape_html(subject['name'])}» اضافه شد:</b>\n\n"
        f"{names_text}",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "add_chapter", f"Chapters: {', '.join(n for _, n in created)}"
    )


@router.callback_query(F.data.startswith("chapter_view:"))
async def chapter_view_handler(callback: CallbackQuery):
    """View a chapter."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    chapter = await models.get_chapter_by_id(chapter_id)
    if not chapter:
        await callback.answer("❌ فصل یافت نشد!", show_alert=True)
        return

    notes_count = await models.count_notes(status="approved", chapter_id=chapter_id)
    await callback.message.edit_text(
        f"📕 <b>{chapter['name']}</b>\n\n"
        f"📄 تعداد جزوه‌ها: {notes_count}",
        reply_markup=keyboards.chapter_detail_keyboard(chapter_id, chapter["subject_id"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("chapter_edit:"))
async def chapter_edit_handler(callback: CallbackQuery, state: FSMContext):
    """Edit a chapter."""
    await callback.answer()
    chapter_id = int(callback.data.split(":")[1])
    await state.update_data(edit_chapter_id=chapter_id)
    await state.set_state(ChapterEditFlow.entering_name)
    await callback.message.edit_text(
        "✏️ <b>ویرایش فصل</b>\n\n"
        "نام جدید را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard(f"chapter_view:{chapter_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(ChapterEditFlow.entering_name))
async def chapter_edit_name(message: Message, state: FSMContext):
    """Save edited chapter."""
    name = message.text.strip()
    data = await state.get_data()
    chapter_id = data.get("edit_chapter_id")

    if len(name) < 2:
        await message.answer("❌ نام باید حداقل ۲ کاراکتر باشد. دوباره ارسال کنید:")
        return

    chapter = await models.get_chapter_by_id(chapter_id)
    await models.update_chapter(chapter_id, name)
    await state.clear()
    await message.answer(
        f"✅ فصل به «<b>{escape_html(name)}</b>» ویرایش شد.",
        reply_markup=keyboards.chapters_list_keyboard(
            await models.get_chapters_by_subject(chapter["subject_id"]), chapter["subject_id"]
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("chapter_delete:"))
async def chapter_delete_handler(callback: CallbackQuery):
    """Delete a single chapter."""
    chapter_id = int(callback.data.split(":")[1])
    chapter = await models.get_chapter_by_id(chapter_id)
    if not chapter:
        await callback.answer("❌ فصل یافت نشد!", show_alert=True)
        return

    await models.delete_chapter(chapter_id)
    await callback.answer(f"🗑 فصل «{chapter['name']}» حذف شد.", show_alert=True)

    # Show updated list
    chapters = await models.get_chapters_by_subject(chapter["subject_id"])
    await callback.message.edit_text(
        f"📖 درس: <b>{(await models.get_subject_by_id(chapter['subject_id']))['name']}</b>\n\n📕 <b>فصل‌ها</b>:",
        reply_markup=keyboards.chapters_list_keyboard(chapters, chapter["subject_id"]),
        parse_mode="HTML",
    )


# ─── Notes Management (Admin) ────────────────────────────────────────────────

@router.callback_query(F.data == "admin_notes")
async def admin_notes_handler(callback: CallbackQuery):
    """Show all notes management."""
    await callback.answer()
    notes = await models.get_approved_notes(limit=20)
    await callback.message.edit_text(
        "📄 <b>مدیریت جزوه‌ها</b>\n\n"
        "جزوه موردنظر را انتخاب کنید:",
        reply_markup=keyboards.notes_list_keyboard(notes),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("note_view:"))
async def note_view_handler(callback: CallbackQuery):
    """View a note's details."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    field = await models.get_field_by_id(note["field_id"])
    subject = await models.get_subject_by_id(note["subject_id"])
    chapter = await models.get_chapter_by_id(note["chapter_id"]) if note["chapter_id"] else None

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

    await callback.message.edit_text(
        format_note_info(note_data),
        reply_markup=keyboards.note_detail_keyboard(note_id, context="admin"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("note_download:"))
async def note_download_handler(callback: CallbackQuery):
    """Send the note file to the user."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note or not note["file_id"]:
        await callback.answer("❌ فایل یافت نشد!", show_alert=True)
        return

    file_type = note["file_type"]
    try:
        if file_type == "photo":
            await callback.message.answer_photo(note["file_id"], caption=f"📄 {note['title']}")
        elif file_type == "video":
            await callback.message.answer_video(note["file_id"], caption=f"📄 {note['title']}")
        elif file_type in ("document", "audio"):
            await callback.message.answer_document(note["file_id"], caption=f"📄 {note['title']}")
        elif file_type == "voice":
            await callback.message.answer_voice(note["file_id"], caption=f"📄 {note['title']}")
        else:
            await callback.message.answer_document(note["file_id"], caption=f"📄 {note['title']}")
    except Exception as e:
        await callback.answer(f"❌ خطا در ارسال فایل: {e}", show_alert=True)


@router.callback_query(F.data.startswith("note_delete:"))
async def note_delete_handler(callback: CallbackQuery):
    """Delete a single note."""
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    await models.delete_note(note_id)
    await callback.answer(f"🗑 جزوه «{note['title']}» حذف شد.", show_alert=True)

    # Show updated notes list
    notes = await models.get_approved_notes(limit=20)
    await callback.message.edit_text(
        "📄 <b>مدیریت جزوه‌ها</b>\n\nجزوه موردنظر را انتخاب کنید:",
        reply_markup=keyboards.notes_list_keyboard(notes),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "delete_note", f"Note #{note_id}: {note['title']}"
    )
    logger.info(f"Note #{note_id} deleted by admin {callback.from_user.id}")


@router.callback_query(F.data.startswith("approve:"))
async def approve_note_handler(callback: CallbackQuery):
    """Approve a pending note."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    await models.approve_note(note_id, callback.from_user.id)
    await callback.message.edit_text(
        f"✅ جزوه شماره {note_id} تأیید شد.\n\n"
        f"📄 {note['title']}",
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "approve_note", f"Note #{note_id}: {note['title']}"
    )

    # Notify the submitter
    from handlers import bot
    try:
        await bot.send_message(
            note["submitted_by"],
            f"✅ <b>جزوه شما تأیید شد!</b>\n\n"
            f"📄 {note['title']}\n\n"
            "جزوه شما در سیستم ثبت و در دسترس کاربران قرار گرفت.",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("reject:"))
async def reject_note_handler(callback: CallbackQuery):
    """Reject a pending note."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    await models.reject_note(note_id, callback.from_user.id)
    await callback.message.edit_text(
        f"❌ جزوه شماره {note_id} رد شد.\n\n"
        f"📄 {note['title']}",
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "reject_note", f"Note #{note_id}: {note['title']}"
    )

    # Notify the submitter
    from handlers import bot
    try:
        await bot.send_message(
            note["submitted_by"],
            f"❌ <b>جزوه شما رد شد.</b>\n\n"
            f"📄 {note['title']}\n\n"
            "متأسفانه جزوه شما تأیید نشد.",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin_pending")
async def admin_pending_handler(callback: CallbackQuery):
    """Show pending notes."""
    await callback.answer()
    notes = await models.get_pending_notes()
    if not notes:
        await callback.message.edit_text(
            "✅ هیچ جزوه در انتظار تأییدی وجود ندارد.",
            reply_markup=keyboards.admin_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    text = "⏳ <b>جزوه‌های در انتظار تأیید</b>\n\n"
    for note in notes:
        field = note.get("field_name", "")
        subject = note.get("subject_name", "")
        chapter = note.get("chapter_name", "بدون فصل")
        text += (
            f"📄 <b>{note['title']}</b>\n"
            f"📚 {field} → 📖 {subject} → 📕 {chapter}\n"
            f"👤 {note['submitted_by_name']}\n"
            f"─────────────────\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )


# ─── Admin Management ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_admins")
async def admin_admins_handler(callback: CallbackQuery):
    """Show admin management."""
    await callback.answer()
    admins = await models.get_all_admins()
    await callback.message.edit_text(
        "👨‍💼 <b>مدیریت ادمین‌ها</b>\n\n"
        "ادمین موردنظر را انتخاب کنید:",
        reply_markup=keyboards.admins_list_keyboard(admins),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_add"))
async def admin_add_handler(callback: CallbackQuery, state: FSMContext):
    """Add a new admin."""
    await callback.answer()
    await state.set_state(AdminAddFlow.entering_user_id)
    await callback.message.edit_text(
        "➕ <b>افزودن ادمین جدید</b>\n\n"
        "مرحله ۱ از ۴: Telegram ID ادمین را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("admin_admins"),
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminAddFlow.entering_user_id))
async def admin_add_user_id(message: Message, state: FSMContext):
    """Get new admin's Telegram ID."""
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID باید عددی باشد. دوباره ارسال کنید:")
        return

    # Check if already an admin
    existing = await models.get_admin_by_user_id(user_id)
    if existing:
        await message.answer("❌ این کاربر از قبل ادمین است. ID دیگری ارسال کنید:")
        return

    await state.update_data(new_admin_user_id=user_id)
    await state.set_state(AdminAddFlow.entering_username)
    await message.answer(
        "✅ مرحله ۲ از ۴: Username ادمین را ارسال کنید (بدون @):",
        reply_markup=keyboards.cancel_keyboard("admin_admins"),
    )


@router.message(StateFilter(AdminAddFlow.entering_username))
async def admin_add_username(message: Message, state: FSMContext):
    """Get new admin's username."""
    username = message.text.strip().lstrip("@")
    await state.update_data(new_admin_username=username)
    await state.set_state(AdminAddFlow.entering_full_name)
    await message.answer(
        "✅ مرحله ۳ از ۴: نام کامل ادمین را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("admin_admins"))


@router.message(StateFilter(AdminAddFlow.entering_full_name))
async def admin_add_full_name(message: Message, state: FSMContext):
    """Get new admin's full name."""
    full_name = message.text.strip()
    await state.update_data(new_admin_full_name=full_name)
    await state.set_state(AdminAddFlow.entering_password)
    await message.answer(
        "✅ مرحله ۴ از ۴: رمز عبور ادمین را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("admin_admins"))


@router.message(StateFilter(AdminAddFlow.entering_password))
async def admin_add_password(message: Message, state: FSMContext):
    """Get new admin's password and save."""
    password = message.text.strip()
    if len(password) < 4:
        await message.answer("❌ رمز باید حداقل ۴ کاراکتر باشد. دوباره ارسال کنید:")
        return

    data = await state.get_data()
    password_hash = security.hash_password(password)

    admin_id = await models.create_admin(
        user_id=data["new_admin_user_id"],
        username=data["new_admin_username"],
        full_name=data["new_admin_full_name"],
        password_hash=password_hash,
    )

    # Set default permissions
    await models.set_admin_permissions(admin_id, DEFAULT_ADMIN_PERMISSIONS)

    await state.clear()
    await message.answer(
        f"✅ <b>ادمین جدید اضافه شد!</b>\n\n"
        f"🆔 ID: <code>{data['new_admin_user_id']}</code>\n"
        f"👤 نام: {data['new_admin_full_name']}\n"
        f"📛 Username: @{data['new_admin_username']}\n\n"
        f"دسترسی‌های پیش‌فرض اعمال شدند.",
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "add_admin",
        f"New admin: {data['new_admin_full_name']} (ID: {data['new_admin_user_id']})"
    )
    logger.info(f"New admin added: {data['new_admin_user_id']} by {message.from_user.id}")


@router.callback_query(F.data.startswith("admin_detail:"))
async def admin_detail_handler(callback: CallbackQuery):
    """View admin details."""
    await callback.answer()
    admin_id = int(callback.data.split(":")[1])
    admin = await models.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("❌ ادمین یافت نشد!", show_alert=True)
        return

    perms = await models.get_admin_permissions(admin_id)
    perms_text = "\n".join(
        f"  {'✅' if p in perms else '⬜'} {PERMISSIONS.get(p, p)}"
        for p in PERMISSIONS
    )

    await callback.message.edit_text(
        f"👨‍💼 <b>{admin['full_name'] or admin['username']}</b>\n\n"
        f"🆔 ID: <code>{admin['user_id']}</code>\n"
        f"📛 Username: @{admin['username'] or 'ندارد'}\n"
        f"📊 وضعیت: {'🟢 فعال' if admin['is_active'] else '🔴 غیرفعال'}\n"
        f"⭐ ادمین اصلی: {'بله' if admin['is_main_admin'] else 'خیر'}\n\n"
        f"🔓 <b>دسترسی‌ها</b>:\n{perms_text}",
        reply_markup=keyboards.admin_detail_keyboard(admin_id, bool(admin["is_main_admin"])),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_change_pass:"))
async def admin_change_pass_handler(callback: CallbackQuery, state: FSMContext):
    """Change admin password."""
    await callback.answer()
    admin_id = int(callback.data.split(":")[1])
    await state.update_data(change_pass_admin_id=admin_id)
    await state.set_state(PasswordChangeFlow.entering_password)
    await callback.message.edit_text(
        "🔑 <b>تغییر رمز ادمین</b>\n\n"
        "رمز جدید را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard(f"admin_detail:{admin_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(PasswordChangeFlow.entering_password), F.text)
async def admin_change_password(message: Message, state: FSMContext):
    """Save the new admin password."""
    password = message.text.strip()
    if len(password) < 4:
        await message.answer("❌ رمز باید حداقل ۴ کاراکتر باشد. دوباره ارسال کنید:")
        return

    data = await state.get_data()
    admin_id = data.get("change_pass_admin_id")

    await models.update_admin_password(admin_id, security.hash_password(password))
    await state.clear()

    try:
        await message.delete()  # Do not keep the password in chat history
    except Exception:
        pass

    await message.answer(
        "✅ رمز عبور با موفقیت تغییر کرد.",
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "change_password",
        f"Admin #{admin_id} password changed"
    )
    logger.info(f"Password changed for admin #{admin_id} by {message.from_user.id}")


@router.callback_query(F.data.startswith("admin_perms:"))
async def admin_perms_handler(callback: CallbackQuery):
    """Show admin permissions."""
    await callback.answer()
    admin_id = int(callback.data.split(":")[1])
    perms = await models.get_admin_permissions(admin_id)
    await callback.message.edit_text(
        "🔓 <b>مدیریت دسترسی‌ها</b>\n\n"
        "دکمه‌ها را بزنید تا دسترسی تغییر کند:",
        reply_markup=keyboards.permissions_keyboard(admin_id, perms),
        parse_mode="HTML",
    )


# ─── Owner Management (Owner-only) ────────────────────────────────────────

@router.callback_query(F.data == "admin_owner_add")
async def admin_owner_add_handler(callback: CallbackQuery, state: FSMContext):
    """Promote an existing admin to Owner (Owner-only)."""
    await callback.answer()
    await state.set_state(AdminAddFlow.entering_user_id)
    await state.update_data(promote_to_owner=True)
    await callback.message.edit_text(
        "👑 <b>افزودن Owner جدید</b>\n\n"
        "Telegram ID ادمین فعلی را ارسال کنید تا به Owner ارتقا یابد\n"
        "<i>(Owner باید قبلاً به عنوان ادمین ثبت شده و یک بار وارد شده باشد):</i>",
        reply_markup=keyboards.cancel_keyboard("manage_owners"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "manage_owners")
async def manage_owners_handler(callback: CallbackQuery):
    """List owners with management options (Owner-only)."""
    await callback.answer()
    from permissions import get_owner_ids
    owners = []
    for a in await models.get_all_admins():
        if a["is_main_admin"]:
            owners.append(a)
    text = "👑 <b>مدیریت Ownerها</b>\n\n"
    kb = InlineKeyboardBuilder()
    if not owners:
        text += "هیچ Ownerی در دیتابیس نیست (فقط Owner اصلی از config)."
    for a in owners:
        from config import MAIN_ADMIN_ID
        star = " (اصلی)" if a["user_id"] == MAIN_ADMIN_ID else ""
        text += f"👑 {a['full_name'] or a['username'] or 'ID:' + str(a['user_id'])}{star}\n"
        if a["user_id"] != MAIN_ADMIN_ID:
            kb.row(InlineKeyboardButton(
                text=f"⬇️ سلب Owner از {a['full_name'] or a['username'] or a['user_id']}",
                callback_data=f"owner_demote:{a['id']}",
            ))
    kb.row(InlineKeyboardButton(text="👑 افزودن Owner جدید", callback_data="admin_owner_add"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_admins"))
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("owner_demote:"))
async def owner_demote_handler(callback: CallbackQuery):
    """Revoke owner role (Owner-only; cannot demote the config main)."""
    await callback.answer()
    from config import MAIN_ADMIN_ID
    admin_id = int(callback.data.split(":")[1])
    admin = await models.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("❌ یافت نشد!", show_alert=True)
        return
    if admin["user_id"] == MAIN_ADMIN_ID:
        await callback.answer("❌ Owner اصلی قابل حذف نیست!", show_alert=True)
        return
    from models import toggle_admin_active  # keep active, just demote
    db_conn = None
    # direct update via model helper
    await models.set_admin_owner(admin_id, False)
    security.admin_sessions.logout(admin["user_id"])  # force re-login with new role
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "",
        "demote_owner", f"user {admin['user_id']}"
    )
    await callback.answer("✅ Owner سلب شد (باید دوباره وارد شود).", show_alert=True)
    await manage_owners_handler(callback)


# ─── Logs PDF Export ─────────────────────────────────────────────────────

@router.callback_query(F.data == "logs_pdf")
async def logs_pdf_handler(callback: CallbackQuery):
    """Export recent logs as a tidy PDF file (Owner/export permission)."""
    await callback.answer()
    logs = await models.get_logs(limit=200)
    if not logs:
        await callback.answer("📋 هیچ لاگی برای خروجی وجود ندارد.", show_alert=True)
        return

    from docx import Document
    from docx.shared import Pt
    import tempfile, datetime as _dt
    doc = Document()
    doc.add_heading("گزارش لاگ‌های ربات", level=1)
    p = doc.add_paragraph(f"تعداد: {len(logs)} رکورد — تولید شده در {_dt.datetime.now():%Y-%m-%d %H:%M}")
    p.runs[0].font.size = Pt(9)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for i, h in enumerate(["زمان", "کاربر", "عملیات", "جزئیات", "نتیجه"]):
        hdr[i].text = h
    for log in logs:
        row = table.add_row().cells
        row[0].text = str(log["created_at"])[:19]
        row[1].text = f"{log['username'] or ''}({log['user_id'] or '-'})"
        row[2].text = str(log["action"])[:40]
        row[3].text = (log["details"] or "")[:120]
        row[4].text = "OK"
    out_dir = Path(convert.TEMP_DIR); out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / f"logs_{_dt.datetime.now():%Y%m%d_%H%M%S}.docx"
    doc.save(docx_path)
    try:
        out_pdf = convert.word_to_pdf(docx_path, out_dir)
        await callback.message.answer_document(out_pdf, caption="📤 خروجی PDF لاگ‌ها")
        docx_path.unlink(missing_ok=True)
        out_pdf.unlink(missing_ok=True)
        await models.add_log(callback.from_user.id, callback.from_user.username or "",
                             "export_logs_pdf", f"{len(logs)} rows")
    except RuntimeError as e:
        # LibreOffice missing -> send the DOCX so the admin still gets output
        await callback.message.answer_document(docx_path, caption=f"📤 خروجی لاگ‌ها (Word)\n{e}")
        docx_path.unlink(missing_ok=True)
    except Exception as e:
        await callback.answer(f"❌ خطا در تولید خروجی: {e}", show_alert=True)


@router.callback_query(F.data.startswith("perm_toggle:"))
async def perm_toggle_handler(callback: CallbackQuery):
    """Toggle a permission for an admin."""
    await callback.answer()
    parts = callback.data.split(":")
    admin_id = int(parts[1])
    perm_key = parts[2]

    if perm_key not in PERMISSIONS:
        await callback.answer("❌ دسترسی نامعتبر است!", show_alert=True)
        return

    current_perms = await models.get_admin_permissions(admin_id)
    if perm_key in current_perms:
        current_perms.remove(perm_key)
    else:
        current_perms.append(perm_key)

    await models.set_admin_permissions(admin_id, current_perms)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "change_permissions",
        f"Admin #{admin_id}: {perm_key} -> {'ON' if perm_key in current_perms else 'OFF'}"
    )

    # Refresh keyboard
    await callback.message.edit_reply_markup(
        reply_markup=keyboards.permissions_keyboard(admin_id, current_perms)
    )


@router.callback_query(F.data.startswith("admin_delete:"))
async def admin_delete_handler(callback: CallbackQuery):
    """Delete an admin."""
    await callback.answer()
    admin_id = int(callback.data.split(":")[1])
    admin = await models.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("❌ ادمین یافت نشد!", show_alert=True)
        return

    if admin["is_main_admin"]:
        await callback.answer("❌ ادمین اصلی قابل حذف نیست!", show_alert=True)
        return

    await models.delete_admin(admin_id)
    await callback.answer("✅ ادمین حذف شد!", show_alert=True)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "delete_admin",
        f"Admin: {admin['full_name']} (ID: {admin['user_id']})"
    )


# ─── User Management ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_users")
async def admin_users_handler(callback: CallbackQuery):
    """Show user management."""
    await callback.answer()
    await callback.message.edit_text(
        "👤 <b>مدیریت کاربران</b>\n\n"
        "کاربران مجاز می‌توانند بدون تأیید ادمین جزوه ثبت کنند.",
        reply_markup=keyboards.users_management_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "allowed_users_list")
async def allowed_users_list_handler(callback: CallbackQuery):
    """List allowed users."""
    await callback.answer()
    users = await models.get_allowed_users()
    if not users:
        await callback.message.edit_text(
            "👥 هیچ کاربر مجازی ثبت نشده است.",
            reply_markup=keyboards.users_management_keyboard(),
            parse_mode="HTML",
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for user in users:
        status = "🟢" if user["can_submit_without_approval"] else "🔴"
        name = user["full_name"] or user["username"] or f"ID:{user['user_id']}"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {name}",
                callback_data=f"allowed_detail:{user['user_id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_users"),
    )
    await callback.message.edit_text(
        "👥 <b>کاربران مجاز</b>:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("allowed_detail:"))
async def allowed_detail_handler(callback: CallbackQuery):
    """View allowed user details."""
    await callback.answer()
    user_id = int(callback.data.split(":")[1])
    users = await models.get_allowed_users()
    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await callback.answer("❌ کاربر یافت نشد!", show_alert=True)
        return

    await callback.message.edit_text(
        f"👤 <b>{user['full_name'] or user['username']}</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"📛 Username: @{user['username'] or 'ندارد'}\n"
        f"✅ تأیید خودکار: {'فعال' if user['can_submit_without_approval'] else 'غیرفعال'}",
        reply_markup=keyboards.allowed_user_keyboard(user_id, bool(user["can_submit_without_approval"])),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("allowed_toggle:"))
async def allowed_toggle_handler(callback: CallbackQuery):
    """Toggle allowed user status."""
    await callback.answer()
    user_id = int(callback.data.split(":")[1])
    users = await models.get_allowed_users()
    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await callback.answer("❌ کاربر یافت نشد!", show_alert=True)
        return

    new_status = not bool(user["can_submit_without_approval"])
    await models.toggle_allowed_user(user_id, new_status)
    await callback.answer(
        f"{'✅ فعال' if new_status else '🔴 غیرفعال'} شد!",
        show_alert=True,
    )
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "toggle_allowed_user",
        f"User {user_id}: auto-approve -> {new_status}"
    )


@router.callback_query(F.data.startswith("allowed_remove:"))
async def allowed_remove_handler(callback: CallbackQuery):
    """Remove an allowed user."""
    await callback.answer()
    user_id = int(callback.data.split(":")[1])
    await models.remove_allowed_user(user_id)
    await callback.answer("✅ کاربر حذف شد!", show_alert=True)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "", "remove_allowed_user", f"User {user_id}"
    )


# ─── Logs ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_logs")
async def admin_logs_handler(callback: CallbackQuery):
    """Show recent logs + PDF export button."""
    await callback.answer()
    logs = await models.get_logs(limit=20)
    if not logs:
        await callback.message.edit_text(
            "📋 هیچ لاگی ثبت نشده است.",
            reply_markup=keyboards.admin_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    text = "📋 <b>آخرین عملیات</b>\n\n"
    for log in logs:
        text += (
            f"🕐 {log['created_at']}\n"
            f"👤 {log['username'] or f'ID:{log['user_id']}'}\n"
            f"📌 {log['action']}\n"
            f"📝 {log['details'][:80]}\n"
            f"─────────────────\n"
        )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="📤 خروجی PDF", callback_data="logs_pdf"))
    kb.row(InlineKeyboardButton(
        text="🔙 بازگشت", callback_data="admin_main_back"))

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── Settings ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_settings")
async def admin_settings_handler(callback: CallbackQuery):
    """Show settings panel."""
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>تنظیمات</b>\n\n"
        "گزینه‌ای را انتخاب کنید:",
        reply_markup=keyboards.settings_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "setting_stats")
async def setting_stats_handler(callback: CallbackQuery):
    """Show bot statistics."""
    await callback.answer()
    total_notes = await models.count_notes()
    approved_notes = await models.count_notes("approved")
    pending_notes = await models.count_notes("pending")
    rejected_notes = await models.count_notes("rejected")
    fields = await models.get_fields()
    admins = await models.get_all_admins()
    allowed = await models.get_allowed_users()

    await callback.message.edit_text(
        f"📊 <b>آمار ربات</b>\n\n"
        f"📚 رشته‌ها: {len(fields)}\n"
        f"📄 جزوه‌ها: {total_notes}\n"
        f"  ✅ تأیید شده: {approved_notes}\n"
        f"  ⏳ در انتظار: {pending_notes}\n"
        f"  ❌ رد شده: {rejected_notes}\n"
        f"👨‍💼 ادمین‌ها: {len(admins)}\n"
        f"👥 کاربران مجاز: {len(allowed)}",
        reply_markup=keyboards.settings_keyboard(),
        parse_mode="HTML",
    )


# ─── Weekly Schedule Management (Admin) ───────────────────────────────────

@router.callback_query(F.data == "admin_schedule")
async def admin_schedule_handler(callback: CallbackQuery):
    """Show weekly schedule management menu."""
    await callback.answer()
    await callback.message.edit_text(
        "🗓 <b>مدیریت برنامه هفتگی کلاس</b>\n\n"
        "برنامه به‌صورت ۷ روز (ردیف) × ۷ زنگ (ستون) تعریف می‌شود و برای همه دانش‌آموزان نمایش داده می‌شود.",
        reply_markup=keyboards.admin_schedule_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_schedule_view")
async def admin_schedule_view_handler(callback: CallbackQuery):
    """Admin view: the full weekly plan as a real 8x8 glass-button grid.
    Same table students see, shown inside the admin panel."""
    await callback.answer()
    from schedule import _build_grid, _schedule_kb
    grid = await _build_grid()
    kb = _schedule_kb(grid, admin_user=True)
    await callback.message.edit_text(
        "👁 <b>مشاهده برنامه هفتگی (پنل ادمین)</b>\n\n"
        "روی هر درس کلیک کنید تا جزئیات همان زنگ را ببینید؛\n"
        "روی نام روز برای تکالیف کامل آن روز.",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "sched_edit_start")
async def sched_edit_start_handler(callback: CallbackQuery):
    """Pick a day to edit (global schedule, field_id=None)."""
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش برنامه</b>\n\n"
        "روز موردنظر را انتخاب کنید:",
        reply_markup=keyboards.sched_edit_menu_keyboard(None),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("sched_cell:"))
async def sched_cell_handler(callback: CallbackQuery, state: FSMContext):
    """Edit the content of one day (single text entry for all 7 periods)."""
    await callback.answer()
    _, fid, day = callback.data.split(":")
    field_id = None if fid == "None" else int(fid)
    await state.set_state(SchedEditFlow.waiting_content)
    await state.update_data(sched_field=field_id, sched_day=int(day))
    existing = await models.get_day_tasks(field_id, int(day))
    text = "📝 <b>تنظیم درس‌های روز " + models.DAYS_FA[int(day)] + "</b>\n\n"
    text += "درس‌ها را به‌ترتیب ساعت (زنگ ۱ تا ۷) هرکدام در یک خط ارسال کنید (حداکثر ۷ مورد):\n"
    if existing:
        text += "مقادیر فعلی:\n" + "\n".join(f"• {e}" for e in existing)
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.cancel_keyboard(f"sched_edit_menu:{field_id}"),
        parse_mode="HTML")


@router.callback_query(F.data.startswith("sched_edit_cell:"))
async def sched_edit_cell_handler(callback: CallbackQuery, state: FSMContext):
    """Edit one exact cell (day, period) from the grid view."""
    await callback.answer()
    _, fid, day, col = callback.data.split(":")
    field_id = None if fid == "None" else int(fid)
    day, col = int(day), int(col)
    tasks = await models.get_day_tasks(field_id, day)
    current = tasks[col - 1] if col - 1 < len(tasks) else ""
    await state.set_state(SchedEditFlow.waiting_single_cell)
    await state.update_data(
        sched_field=field_id, sched_day=day, sched_col=col)  # noqa: single cell edit
    await callback.message.answer(
        f"✏️ <b>ویرایش سلول</b>\n"
        f"روز: {models.DAYS_FA[day]} — زنگ {col}\n"
        f"مقدار فعلی: <b>{escape_html(current) or '(خالی)'}</b>\n\n"
        f"متن جدید را ارسال کنید (یا «حذف» برای خالی کردن):",
        reply_markup=keyboards.cancel_keyboard(f"sched_edit_menu:{field_id}"),
        parse_mode="HTML",
    )


@router.message(StateFilter(SchedEditFlow.waiting_single_cell), F.text)
async def sched_single_cell_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    field_id = data.get("sched_field")
    day = int(data.get("sched_day", 0))
    col = int(data.get("sched_col", 1))
    text_in = message.text.strip()
    content = "" if text_in == "حذف" else text_in
    await models.set_schedule_cell(field_id, day, col, content)
    await state.clear()
    await message.answer(
        f"✅ سلول زنگ {col} روز {models.DAYS_FA[day]} ذخیره شد.",
        reply_markup=keyboards.sched_edit_menu_keyboard(field_id),
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "edit_schedule_cell",
        f"day={day} col={col} -> {content or '(empty)'}"
    )


@router.message(StateFilter(SchedEditFlow.waiting_content), F.text)
async def sched_content_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    field_id = data.get("sched_field")
    day = int(data.get("sched_day", 0))
    lines = [ln.strip() for ln in message.text.strip().splitlines() if ln.strip()][: 7]
    if not lines:
        await message.answer("❌ حداقل یک مورد وارد کنید. دوباره ارسال کنید:")
        return
    # Clear that day's old cells then write new ones
    for c in range(1, 8):
        await models.set_schedule_cell(field_id, day, c, "")
    for i, content in enumerate(lines, start=1):
        await models.set_schedule_cell(field_id, day, i, content)
    await state.clear()
    await message.answer(
        f"✅ برنامه {models.DAYS_FA[day]} ذخیره شد ({len(lines)} مورد).",
        reply_markup=keyboards.sched_edit_menu_keyboard(field_id),
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "", "edit_schedule",
        f"day={day} ({len(lines)} items)"
    )


# ─── Online Classes Management (Admin) ────────────────────────────────────

def _classes_kb(classes, day_index: int | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if day_index is None:
        for c in classes:
            kb.row(InlineKeyboardButton(
                text=f"🗑 {models.DAYS_FA[c['day_index']]} — {c['title']}",
                callback_data=f"class_del:{c['id']}",
            ))
        kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_classes"))
    else:
        for c in classes:
            bell = "🔔" if c["notify_enabled"] else "🔕"
            kb.row(InlineKeyboardButton(
                text=f"✏️ {c['title']} ({c['time_text'] or 'بدون ساعت'}) {bell}",
                callback_data=f"class_edit:{c['id']}",
            ))
        kb.row(InlineKeyboardButton(text="➕ افزودن کلاس", callback_data="class_add"))
        kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_classes"))
    return kb.as_markup()


@router.callback_query(F.data == "admin_classes")
async def admin_classes_handler(callback: CallbackQuery):
    """Manage online classes per day."""
    await callback.answer()
    notify_on = (await models.get_setting("goodnight_enabled", "0")) == "1"
    global_notify = (await models.get_setting("class_notify_enabled", "1")) == "1"
    kb = InlineKeyboardBuilder()
    for d, day in enumerate(models.DAYS_FA):
        count = len(await models.get_online_classes(d))
        kb.row(InlineKeyboardButton(
            text=f"{day} ({count} کلاس)",
            callback_data=f"classes_day:{d}",
        ))
    kb.row(InlineKeyboardButton(
        text=("🔔" if global_notify else "🔕") + " اعلان کلاس‌ها: "
             + ("فعال" if global_notify else "غیرفعال"),
        callback_data="class_notify_global",
    ))
    kb.row(InlineKeyboardButton(
        text=("🌙" if notify_on else "⚫") + " پیام شب خوش",
        callback_data="goodnight_menu",
    ))
    kb.row(InlineKeyboardButton(
        text="📣 متن دستور /all", callback_data="all_text_set"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"))
    await callback.message.edit_text(
        "🟢 <b>مدیریت کلاس‌های آنلاین</b>\n\n"
        "روزی را انتخاب کنید تا کلاس‌های آنلاین آن روز را مدیریت کنید:\n"
        "(ساعت کلاس‌ها به وقت ایران ذخیره و برای ارسال به منطقه محلی تبدیل می‌شود)",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("classes_day:"))
async def classes_day_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    d = int(callback.data.split(":")[1])
    await state.update_data(cls_day=d)
    classes = await models.get_online_classes(d)
    await callback.message.edit_text(
        f"🟢 <b>کلاس‌های آنلاین {models.DAYS_FA[d]}</b>\n\n"
        + ("برای ویرایش (نام/ساعت/اعلان/حذف) روی کلاس کلیک کنید:" if classes
           else "هنوز کلاسی ثبت نشده — دکمه افزودن را بزنید:"),
        reply_markup=_classes_kb(classes, d),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "class_add")
async def class_add_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(OnlineClassFlow.waiting_title)
    await callback.message.answer(
        "➕ <b>افزودن کلاس آنلاین</b>\n\n"
        "نام درس/کلاس را ارسال کنید:",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
        parse_mode="HTML",
    )


@router.message(StateFilter(OnlineClassFlow.waiting_title), F.text)
async def class_add_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 2 or len(title) > 100:
        await message.answer("❌ نام باید بین ۲ تا ۱۰۰ کاراکتر باشد:")
        return
    await state.update_data(cls_title=title)
    await state.set_state(OnlineClassFlow.waiting_time)
    await message.answer(
        "⏰ ساعت کلاس را ارسال کنید (مثلاً: ۱۶ تا ۱۸)\n"
        "یا «رد» برای رد کردن:",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
    )


@router.message(StateFilter(OnlineClassFlow.waiting_time), F.text)
async def class_add_time(message: Message, state: FSMContext):
    t = message.text.strip()
    time_text = "" if t == "رد" else t
    start_h = start_m = end_h = None
    if time_text:
        # Accept "16 تا 18", "16:30-18", "16", "16:30" (Tehran time)
        import re as _re
        nums = _re.findall(r"(\d{1,2})[:.]?(\d{2})?", t.replace("۱۶", "16").replace("۱۸", "18"))
        parsed = []
        for h, m in nums[:2]:
            hh, mm = int(h), int(m or 0)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                parsed.append((hh, mm))
        if parsed:
            start_h, start_m = parsed[0]
            if len(parsed) > 1:
                end_h = parsed[1][0]
            time_text = f"{start_h:02d}:{start_m:02d}" + (
                f" تا {end_h:02d}" if end_h is not None else "")
    await state.update_data(cls_time=time_text, cls_start=start_h,
                            cls_start_m=start_m, cls_end=end_h)
    await state.set_state(OnlineClassFlow.waiting_link)
    await message.answer(
        "🔗 لینک جلسه (اختیاری) را ارسال کنید یا «رد»:",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
    )


@router.message(StateFilter(OnlineClassFlow.waiting_link), F.text)
async def class_add_link(message: Message, state: FSMContext):
    link = message.text.strip()
    if link == "رد":
        link = ""
    elif not (link.startswith("http://") or link.startswith("https://")):
        await message.answer("❌ لینک باید با http:// یا https:// شروع شود (یا «رد»):")
        return
    data = await state.get_data()
    day = int(data.get("cls_day", 0))
    cid = await models.add_online_class_full(
        day, data.get("cls_title", ""), data.get("cls_time", ""), link,
        start_hour=data.get("cls_start"), start_minute=data.get("cls_start_m") or 0,
        end_hour=data.get("cls_end"))
    await state.clear()
    await message.answer(
        f"✅ کلاس آنلاین «{escape_html(data.get('cls_title', ''))}» برای "
        f"{models.DAYS_FA[day]} ثبت شد.\n"
        "(برای فعال‌سازی اعلان خودکار، ساعت شروع را دقیق وارد کرده باشید)",
        reply_markup=InlineKeyboardBuilder().as_markup(),
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "",
        "add_online_class", f"day={day}: {data.get('cls_title')}"
    )


@router.callback_query(F.data.startswith("class_del:"))
async def class_del_handler(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.split(":")[1])
    await models.delete_online_class(cid)
    await callback.answer("🗑 کلاس حذف شد.", show_alert=True)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "",
        "delete_online_class", f"id={cid}"
    )
    classes = await models.get_online_classes()
    await callback.message.edit_text(
        "🟢 <b>همه کلاس‌های آنلاین</b>",
        reply_markup=_classes_kb(classes, None),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "sched_clear")
async def sched_clear_handler(callback: CallbackQuery):
    """Clear the whole schedule."""
    await callback.answer()
    await models.clear_schedule()
    await models.add_log(callback.from_user.id, callback.from_user.username or "", "clear_schedule", "all")
    await callback.message.edit_text(
        "🗑 کل برنامه هفتگی پاک شد.",
        reply_markup=keyboards.admin_schedule_keyboard(),
    )


@router.callback_query(F.data == "sched_reset_tasks")
async def sched_reset_tasks_handler(callback: CallbackQuery):
    """Manually reset all users' task statuses for this week."""
    await callback.answer()
    cleared = await models.reset_week_tasks()
    await models.add_log(callback.from_user.id, callback.from_user.username or "", "reset_tasks",
                         f"{cleared} rows")
    await callback.message.edit_text(
        f"✅ {cleared} رکورد تکلیف پاک شد (وضعیت همه کاربران ریست شد).",
        reply_markup=keyboards.admin_schedule_keyboard(),
    )


# ─── Admin File Conversion ──────────────────────────             ──────────────

@router.callback_query(F.data == "admin_convert_start")
async def admin_convert_start_handler(callback: CallbackQuery, state: FSMContext):
    """Admin file conversion menu."""
    await callback.answer()
    from filetools import _remember_back
    await _remember_back(state, "admin_main_back")  # return to admin panel
    await state.update_data(img_paths=[], doc_paths=[])
    await callback.message.edit_text(
        "🛠 <b>تبدیل فایل (پنل ادمین)</b>\n\n"
        "یک حالت را انتخاب کنید یا مستقیم عکس/فایل بفرستید:\n"
        "• چند عکس → PDF\n"
        "• Word → PDF\n"
        "• PDF → Word\n\n"
        "برای جزوه‌های ذخیره‌شده از بخش مدیریت جزوه‌ها دکمه «🖨 PDFسازی» را بزنید.",
        reply_markup=keyboards.file_tools_keyboard("admin_main_back"),
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminConvertFlow.waiting_files), F.photo)
async def admin_convert_photo(message: Message, state: FSMContext):
    import hashlib
    dest = Path(convert.TEMP_DIR); dest.mkdir(parents=True, exist_ok=True)
    fname = f"adm_{hashlib.md5(str(message.message_id).encode()).hexdigest()[:14]}.jpg"
    path = dest / fname
    await message.bot.download(message.photo[-1], destination=path)
    data = await state.get_data()
    paths = data.get("img_paths", []) or []
    paths.append(str(path))
    await state.update_data(img_paths=paths)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"🧷 تبدیل به PDF ({len(paths)} عکس)", callback_data="admin_convert_done"))
    kb.row(InlineKeyboardButton(text="❌ لغو عملیات", callback_data="tools_cancel"))
    await message.answer(f"عکس {len(paths)} اضافه شد. عکس بعدی را بفرستید یا تبدیل را بزنید:", reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin_convert_done")
async def admin_convert_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("img_paths"):
        await callback.answer("❌ عکسی دریافت نشده!", show_alert=True)
        return
    await state.set_state(AdminConvertFlow.entering_name)
    await callback.message.edit_text(
        "✏️ نام فایل خروجی را ارسال کنید (بدون پسوند):",
        reply_markup=keyboards.cancel_keyboard("tools_cancel"),
    )


@router.message(StateFilter(AdminConvertFlow.entering_name), F.text)
async def admin_convert_name(message: Message, state: FSMContext):
    name = convert.safe_name(message.text, "admin_pdf")
    data = await state.get_data()
    out = Path(convert.TEMP_DIR) / f"{name}.pdf"
    try:
        convert.images_to_pdf([Path(p) for p in data["img_paths"]], out)
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ خطا: {e}", reply_markup=keyboards.admin_main_menu_keyboard())
        return
    await state.clear()
    try:
        await message.answer_document(out, caption=f"📄 {name}.pdf ✅")
    finally:
        for p in data["img_paths"]:
            Path(p).unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    await message.answer("🛠", reply_markup=keyboards.admin_main_menu_keyboard())
    await models.add_log(message.from_user.id, message.from_user.username or "", "admin_convert",
                         f"images->pdf ({name})")


# ─── Navigation ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_main_back")
async def admin_main_back_handler(callback: CallbackQuery):
    """Return to admin main menu."""
    await callback.answer()
    await callback.message.edit_text(
        "✅ <b>پنل مدیریت</b>\n\n"
        "به پنل مدیریت خوش آمدید!",
        reply_markup=keyboards.admin_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_fields_back")
async def admin_fields_back_handler(callback: CallbackQuery):
    """Return to admin main menu from fields."""
    await admin_main_back_handler(callback)


@router.callback_query(F.data.startswith("subject_chapters_back:"))
async def subject_chapters_back_handler(callback: CallbackQuery):
    """Back to subject view."""
    subject_id = int(callback.data.split(":")[1])
    await subject_view_handler(callback)


@router.callback_query(F.data.startswith("note_back:"))
async def note_back_handler(callback: CallbackQuery):
    """Back from note view."""
    await callback.answer()
    context = callback.data.split(":")[1]
    if context == "admin":
        notes = await models.get_approved_notes(limit=20)
        await callback.message.edit_text(
            "📄 <b>مدیریت جزوه‌ها</b>\n\n"
            "جزوه موردنظر را انتخاب کنید:",
            reply_markup=keyboards.notes_list_keyboard(notes),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "📚 <b>منوی اصلی</b>",
            reply_markup=keyboards.main_menu_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("submitter_info:"))
async def submitter_info_handler(callback: CallbackQuery):
    """Show submitter info for a pending note."""
    await callback.answer()
    note_id = int(callback.data.split(":")[1])
    note = await models.get_note_by_id(note_id)
    if not note:
        await callback.answer("❌ جزوه یافت نشد!", show_alert=True)
        return

    await callback.message.answer(
        f"👤 <b>اطلاعات ثبت‌کننده</b>\n\n"
        f"📛 نام: {note['submitted_by_name']}\n"
        f"🆔 ID: <code>{note['submitted_by']}</code>\n"
        f"📄 جزوه: {note['title']}",
        parse_mode="HTML",
    )


# ─── Generic Cancel/Confirm Handlers ─────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel:"))
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    """Generic cancel handler - always clears any half-finished flow."""
    await callback.answer("❌ عملیات لغو شد.", show_alert=True)
    await state.clear()


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_handler(callback: CallbackQuery):
    """Generic confirm handler - for delete confirmations."""
    await callback.answer("✅ تأیید شد.", show_alert=True)


# ─── Notes Pagination ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("notes_page:"))
async def notes_page_handler(callback: CallbackQuery):
    """Handle notes pagination."""
    await callback.answer()
    page = int(callback.data.split(":")[1])
    notes = await models.get_approved_notes(limit=20, offset=page * 20)
    has_more = len(notes) == 20

    await callback.message.edit_text(
        f"📄 <b>مدیریت جزوه‌ها</b> (صفحه {page + 1})\n\n"
        "جزوه موردنظر را انتخاب کنید:",
        reply_markup=keyboards.notes_list_keyboard(notes, page=page, has_more=has_more),
        parse_mode="HTML",
    )


# ─── Stats Section (آمار) ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    """Stats menu: top active users + full PDF report."""
    await callback.answer()
    top = await models.get_top_users(5)
    lines = ["📊 <b>آمار ربات</b>\n\n🏆 <b>۵ کاربر برتر (بیشترین استفاده)</b>"]
    if top:
        for i, u in enumerate(top, start=1):
            name = u["username"] and f"@{u['username']}" or (
                u["full_name"] or str(u["user_id"]))
            lines.append(f"{i}. {escape_html(name)} — {u['uses']} استفاده")
    else:
        lines.append("هنوز آماری ثبت نشده است.")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="📤 گزارش کامل PDF", callback_data="stats_pdf"))
    kb.row(InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="admin_stats"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"))
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "stats_pdf")
async def stats_pdf_handler(callback: CallbackQuery):
    """Full stats PDF report (Owner only) - users + activity overview."""
    await callback.answer()
    from permissions import is_owner
    if not await is_owner(callback.from_user.id):
        await callback.answer("❌ فقط Owner به گزارش کامل دسترسی دارد.", show_alert=True)
        return

    stats = await models.get_stats_overview()
    top = await models.get_top_users(10)
    members = await models.get_group_members(
        ALLOWED_GROUP_ID if (ALLOWED_GROUP_ID := _group_id_const()) else 0)

    from docx import Document
    from docx.shared import Pt
    import tempfile, datetime as _dt
    doc = Document()
    doc.add_heading("گزارش آماری ربات", level=1)
    p = doc.add_paragraph(
        f"تولید شده در {_dt.datetime.now():%Y-%m-%d %H:%M}")
    p.runs[0].font.size = Pt(9)

    doc.add_heading("آمار کلی", level=2)
    labels_fa = {
        "users_total": "کل کاربران", "group_members": "اعضای گروه",
        "admins_total": "ادمین‌ها", "notes_total": "کل جزوه‌ها",
        "notes_approved": "جزوه‌های تأییدشده", "notes_pending": "در انتظار تأیید",
        "fields_total": "رشته‌ها", "subjects_total": "درس‌ها",
        "chapters_total": "فصل‌ها", "tasks_total": "تکالیف",
        "online_classes": "کلاس‌های آنلاین", "conversions": "تبدیل فایل‌ها",
        "logs_total": "کل لاگ‌ها", "usage_total": "کل استفاده‌ها",
    }
    t1 = doc.add_table(rows=0, cols=2)
    t1.style = "Light List Accent 1"
    for key, label in labels_fa.items():
        row = t1.add_row().cells
        row[0].text = label
        row[1].text = str(stats.get(key, 0))

    doc.add_heading("اعضای گروه", level=2)
    t2 = doc.add_table(rows=1, cols=4)
    t2.style = "Light Grid Accent 1"
    for i, h in enumerate(["Username", "Telegram UID", "نوع", "استفاده"]):
        t2.rows[0].cells[i].text = h
    uses_by_id = {u["user_id"]: u["uses"] for u in top}
    # fetch usage for every member
    member_users = []
    for m in members:
        member_users.append(m)
    from models import get_db
    db = await get_db()
    usage_rows = await db.execute_fetchall(
        f"SELECT user_id, uses FROM usage_stats WHERE user_id IN "
        f"({','.join('?' * len(member_users)) or '0'})",
        tuple(mu["user_id"] for mu in member_users) or (0,),
    )
    await db.close()
    usage_map = {r["user_id"]: r["uses"] for r in usage_rows}
    for m in member_users:
        row = t2.add_row().cells
        row[0].text = f"@{m['username']}" if m["username"] else (m["full_name"] or "-")
        row[1].text = str(m["user_id"])
        row[2].text = "عضو گروه"
        row[3].text = str(usage_map.get(m["user_id"], 0))

    doc.add_heading("۵ کاربر برتر", level=2)
    t3 = doc.add_table(rows=1, cols=2)
    t3.style = "Light Grid Accent 1"
    t3.rows[0].cells[0].text = "Username"
    t3.rows[0].cells[1].text = "استفاده"
    for i, u in enumerate(top[:5], start=1):
        row = t3.add_row().cells
        row[0].text = f"{i}. @{u['username']}" if u["username"] else f"{i}. {u['full_name']}"
        row[1].text = str(u["uses"])

    out_dir = Path(convert.TEMP_DIR); out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / f"stats_{_dt.datetime.now():%Y%m%d_%H%M%S}.docx"
    doc.save(docx_path)
    try:
        out_pdf = convert.word_to_pdf(docx_path, out_dir)
        await callback.message.answer_document(out_pdf, caption="📊 گزارش آماری ربات (PDF)")
        docx_path.unlink(missing_ok=True)
        out_pdf.unlink(missing_ok=True)
    except RuntimeError as e:
        await callback.message.answer_document(
            docx_path, caption=f"📊 گزارش آماری (Word)\n{e}")
        docx_path.unlink(missing_ok=True)
    except Exception as e:
        await callback.answer(f"❌ خطا: {e}", show_alert=True)
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "export_stats_pdf", "stats report")


def _group_id_const():
    from config import ALLOWED_GROUP_ID
    return ALLOWED_GROUP_ID


# ─── Note Submit Quota (سقف ثبت جزوه کاربران) ─────────────────────────────

NOTE_LIMIT_PRESETS = ["", "5", "10", "20"]  # "" = آزاد / نامحدود


def _limit_label(raw: str) -> str:
    if not raw or raw.lower() == "free":
        return "♻️ حالت آزاد (نامحدود)"
    return f"🔢 حداکثر {raw} جزوه بدون تأیید"


@router.callback_query(F.data == "note_limit_menu")
async def note_limit_menu_handler(callback: CallbackQuery):
    """Configure how many notes regular users may submit without approval."""
    await callback.answer()
    current = await models.get_setting("note_submit_limit", "")
    kb = InlineKeyboardBuilder()
    for v in NOTE_LIMIT_PRESETS:
        mark = "✅ " if current == v or (v == "" and current.lower() == "free") else ""
        kb.row(InlineKeyboardButton(
            text=mark + _limit_label(v),
            callback_data=f"note_limit_set:{v or 'free'}",
        ))
    kb.row(InlineKeyboardButton(text="✏️ عدد دلخواه", callback_data="note_limit_custom"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_users"))
    await callback.message.edit_text(
        "📊 <b>سقف ثبت جزوه کاربران</b>\n\n"
        f"وضعیت فعلی: <b>{_limit_label(current)}</b>\n\n"
        "در حالت محدود، کاربران عادی بعد از رسیدن به سقف، جزوه‌هایشان "
        "نیازمند تأیید ادمین می‌شود:\n"
        "(ادمین‌ها و Owner همیشه آزاد هستند)",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("note_limit_set:"))
async def note_limit_set_handler(callback: CallbackQuery):
    await callback.answer()
    value = callback.data.split(":", 1)[1]
    stored = "" if value == "free" else value
    await models.set_setting("note_submit_limit", stored,
                             "max notes a regular user submits without approval")
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "set_note_limit", stored or "free")
    await callback.answer(f"✅ ثبت شد: {_limit_label(stored)}", show_alert=True)
    await note_limit_menu_handler(callback)


@router.callback_query(F.data == "note_limit_custom")
async def note_limit_custom_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(NoteLimitFlow.waiting_number)
    await callback.message.edit_text(
        "✏️ حداکثر تعداد جزوه بدون تأیید را بفرستید\n"
        "(مثلاً: 7 - یا «آزاد» برای نامحدود):",
        reply_markup=keyboards.cancel_keyboard("note_limit_menu"),
    )


@router.message(StateFilter(NoteLimitFlow.waiting_number), F.text)
async def note_limit_number_handler(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ("آزاد", "free", "نامحدود"):
        stored = ""
    elif text.isdigit() and 1 <= int(text) <= 1000:
        stored = text
    else:
        await message.answer("❌ لطفاً یک عدد بین ۱ تا ۱۰۰۰ یا «آزاد» بفرستید:")
        return
    await models.set_setting("note_submit_limit", stored,
                             "max notes a regular user submits without approval")
    await state.clear()
    await message.answer(
        f"✅ سقف ثبت جزوه: <b>{_limit_label(stored)}</b>",
        parse_mode="HTML",
    )
    await models.add_log(message.from_user.id, message.from_user.username or "",
                         "set_note_limit", stored or "free")


# ─── Online Class Editing + Notification Settings ─────────────────────────

@router.callback_query(F.data.startswith("class_edit:"))
async def class_edit_handler(callback: CallbackQuery):
    """Edit menu for a single online class."""
    await callback.answer()
    cid = int(callback.data.split(":")[1])
    cls = await models.get_online_class_by_id(cid)
    if not cls:
        await callback.answer("❌ کلاس یافت نشد!", show_alert=True)
        return
    from classnotifier import format_class_time, get_tz
    tz = await get_tz()
    bell = "🔔" if cls["notify_enabled"] else "🔕"
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ نام درس", callback_data=f"cls_set:{cid}:title"))
    kb.row(InlineKeyboardButton(text="📅 تغییر روز", callback_data=f"cls_set:{cid}:day"))
    kb.row(InlineKeyboardButton(text="⏰ ساعت شروع (تهران)", callback_data=f"cls_set:{cid}:start"))
    kb.row(InlineKeyboardButton(text="🕐 ساعت پایان (تهران)", callback_data=f"cls_set:{cid}:end"))
    kb.row(InlineKeyboardButton(text="🔗 لینک جلسه", callback_data=f"cls_set:{cid}:link"))
    kb.row(InlineKeyboardButton(
        text=f"{bell} اعلان این کلاس: {'فعال' if cls['notify_enabled'] else 'غیرفعال'}",
        callback_data=f"class_notify_toggle:{cid}",
    ))
    kb.row(InlineKeyboardButton(text="🗑 حذف کلاس", callback_data=f"class_del:{cid}"))
    kb.row(InlineKeyboardButton(
        text="🔙 بازگشت", callback_data=f"classes_day:{cls['day_index']}"))
    await callback.message.edit_text(
        f"🟢 <b>ویرایش کلاس: {escape_html(cls['title'])}</b>\n\n"
        f"📅 روز: {models.DAYS_FA[cls['day_index']]}\n"
        f"⏰ زمان: {format_class_time(cls, tz)}\n"
        f"🔔 اعلان: {'فعال' if cls['notify_enabled'] else 'غیرفعال'}\n"
        f"🔗 لینک: {cls['link'] or '—'}",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("class_notify_toggle:"))
async def class_notify_toggle_handler(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.split(":")[1])
    cls = await models.get_online_class_by_id(cid)
    if not cls:
        await callback.answer("❌ یافت نشد!", show_alert=True)
        return
    new_val = not bool(cls["notify_enabled"])
    await models.set_class_notify(cid, new_val)
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "toggle_class_notify", f"class #{cid} -> {new_val}")
    await callback.answer(f"{'🔔 اعلان فعال' if new_val else '🔕 اعلان غیرفعال'} شد")
    await class_edit_handler(callback)


@router.callback_query(F.data.startswith("cls_set:"))
async def cls_set_handler(callback: CallbackQuery, state: FSMContext):
    """Start editing one field of a class."""
    await callback.answer()
    _, cid, field = callback.data.split(":")
    cid, field = int(cid), field
    prompts = {
        "title": "✏️ نام جدید درس را ارسال کنید:",
        "start": "⏰ ساعت شروع را ارسال کنید (ساعت ایران، مثلاً 16:30 یا 16):",
        "end": "🕐 ساعت پایان را ارسال کنید (ساعت ایران) یا «رد»:",
        "link": "🔗 لینک جدید را ارسال کنید یا «رد»:",
    }
    if field == "day":
        # pick a new day from buttons
        kb = InlineKeyboardBuilder()
        for d, day in enumerate(models.DAYS_FA):
            kb.row(InlineKeyboardButton(text=day, callback_data=f"cls_set_day:{cid}:{d}"))
        kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"class_edit:{cid}"))
        await callback.message.edit_text(
            f"📅 روز جدید برای کلاس را انتخاب کنید:", reply_markup=kb.as_markup())
        return
    await state.set_state(ClassEditFlow.waiting_value)
    await state.update_data(cls_edit_id=cid, cls_edit_field=field)
    await callback.message.edit_text(
        prompts.get(field, "مقدار جدید را ارسال کنید:"),
        reply_markup=keyboards.cancel_keyboard(f"class_edit:{cid}"),
    )


@router.callback_query(F.data.startswith("cls_set_day:"))
async def cls_set_day_handler(callback: CallbackQuery):
    await callback.answer()
    _, cid, d = callback.data.split(":")
    await models.update_online_class(int(cid), day_index=int(d))
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "edit_online_class", f"#{cid} day -> {d}")
    await callback.answer("✅ روز تغییر کرد")
    await class_edit_handler(callback)


@router.message(StateFilter(ClassEditFlow.waiting_value), F.text)
async def class_edit_value_handler(message: Message, state: FSMContext):
    """Single value handler for class edits AND panel settings
    (goodnight time/text, timezone)."""
    text = message.text.strip()
    data = await state.get_data()
    cid = int(data.get("cls_edit_id", 0))
    field = data.get("cls_edit_field", "")
    await state.clear()

    # ── Panel settings (goodnight / timezone) ──
    if cid == 0:
        try:
            if field == "goodnight_time":
                from datetime import time as _t
                _t.fromisoformat(text)
                await models.set_setting("goodnight_time", text, "goodnight send time")
            elif field == "goodnight_text":
                if not 3 <= len(text) <= 500:
                    raise ValueError("متن باید بین ۳ تا ۵۰۰ کاراکتر باشد")
                await models.set_setting("goodnight_text", text, "goodnight message text")
            elif field == "timezone":
                from zoneinfo import ZoneInfo
                ZoneInfo(text)
                await models.set_setting("timezone", text, "project display timezone")
            elif field == "all_reply_text":
                if not 3 <= len(text) <= 300:
                    raise ValueError("متن باید بین ۳ تا ۳۰۰ کاراکتر باشد")
                await models.set_setting("all_reply_text", text, "/all funny reply")
            else:
                return
        except ValueError as e:
            await message.answer(f"❌ {str(e) or 'مقدار نامعتبر'}\nدوباره بفرستید یا انصراف بزنید:")
            return
        await message.answer("✅ ذخیره شد.")
        await models.add_log(message.from_user.id, message.from_user.username or "",
                             "set_setting", f"{field} = {text}")
        return

    # ── Real class edit ──
    try:
        if field == "title":
            if not 2 <= len(text) <= 100:
                raise ValueError("نام باید بین ۲ تا ۱۰۰ کاراکتر باشد")
            await models.update_online_class(cid, title=text)
        elif field in ("start", "end"):
            if text == "رد" and field == "end":
                await models.update_online_class(cid, end_hour=None)
            else:
                parts = text.replace(":", "").replace(".", "")
                if not parts.isdigit() or not (1 <= len(parts) <= 4):
                    raise ValueError("فرمت ساعت: 16 یا 16:30")
                num = int(parts)
                hour, minute = divmod(num, 100) if len(parts) > 2 else (num, 0)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("ساعت باید 0-23 و دقیقه 0-59 باشد")
                if field == "start":
                    await models.update_online_class(
                        cid, start_hour=hour, start_minute=minute,
                        time_text=f"{hour:02d}:{minute:02d}")
                else:
                    await models.update_online_class(cid, end_hour=hour)
        elif field == "link":
            if text == "رد":
                await models.update_online_class(cid, link="")
            elif text.startswith("http://") or text.startswith("https://"):
                await models.update_online_class(cid, link=text)
            else:
                raise ValueError("لینک باید با http:// یا https:// شروع شود")
        else:
            raise ValueError("فیلد نامعتبر")
    except ValueError as e:
        await message.answer(f"❌ {e}\nدوباره تلاش کنید یا انصراف بزنید:")
        return

    await models.add_log(message.from_user.id, message.from_user.username or "",
                         "edit_online_class", f"#{cid} {field} -> {text}")
    await message.answer("✅ ذخیره شد.")


@router.callback_query(F.data == "class_notify_global")
async def class_notify_global_handler(callback: CallbackQuery):
    """Toggle ALL class notifications on/off (info stays in schedule)."""
    await callback.answer()
    current = (await models.get_setting("class_notify_enabled", "1")) == "1"
    new_val = not current
    await models.set_setting("class_notify_enabled", "1" if new_val else "0",
                             "global online-class notifications")
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "toggle_class_notify_global", str(new_val))
    await callback.answer(
        f"{'🔔 اعلان کلاس‌ها فعال شد' if new_val else '🔕 اعلان کلاس‌ها خاموش شد'}",
        show_alert=True)
    await admin_classes_handler(callback)


@router.callback_query(F.data == "all_text_set")
async def all_text_set_handler(callback: CallbackQuery, state: FSMContext):
    """Edit the funny reply line shown under /all mentions."""
    await callback.answer()
    await state.set_state(ClassEditFlow.waiting_value)
    await state.update_data(cls_edit_id=0, cls_edit_field="all_reply_text")
    current = await models.get_setting("all_reply_text", "")
    await callback.message.edit_text(
        "📣 <b>متن زیر تگ‌های /all</b>\n\n"
        f"متن فعلی: <i>{escape_html(current) or '(پیش‌فرض)'}</i>\n\n"
        "متن جدید را بفرستید ({count} به تعداد اعضا تبدیل می‌شود):",
        reply_markup=keyboards.cancel_keyboard("admin_classes"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "goodnight_menu")
async def goodnight_menu_handler(callback: CallbackQuery):
    """Configure the daily goodnight group message."""
    await callback.answer()
    enabled = (await models.get_setting("goodnight_enabled", "0")) == "1"
    hhmm = await models.get_setting("goodnight_time", "22:00")
    text = await models.get_setting("goodnight_text", "")
    tz = await models.get_setting("timezone", "Asia/Muscat")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"{'🌙 روشن' if enabled else '⚫ خاموش'} - سوییچ",
        callback_data="goodnight_toggle",
    ))
    kb.row(InlineKeyboardButton(text=f"⏰ زمان ارسال: {hhmm}",
                                callback_data="goodnight_time_set"))
    kb.row(InlineKeyboardButton(text="✏️ متن پیام", callback_data="goodnight_text_set"))
    kb.row(InlineKeyboardButton(text=f"🌍 منطقه زمانی: {tz}", callback_data="tz_menu"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_classes"))
    await callback.message.edit_text(
        f"🌙 <b>پیام شب خوش (گروه)</b>\n\n"
        f"وضعیت: <b>{'فعال ✅' if enabled else 'غیرفعال ⛔'}</b>\n"
        f"⏰ زمان ارسال: <b>{hhmm}</b> (ساعت محلی {tz})\n"
        f"✏️ متن فعلی: <i>{escape_html(text) or '(پیش‌فرض)'}</i>\n\n"
        "پیام هر روز یک‌بار در گروه ارسال می‌شود.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "goodnight_toggle")
async def goodnight_toggle_handler(callback: CallbackQuery):
    await callback.answer()
    enabled = (await models.get_setting("goodnight_enabled", "0")) == "1"
    await models.set_setting("goodnight_enabled", "0" if enabled else "1",
                             "goodnight message enabled")
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "toggle_goodnight", str(not enabled))
    await goodnight_menu_handler(callback)


@router.callback_query(F.data == "goodnight_time_set")
async def goodnight_time_set_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ClassEditFlow.waiting_value)
    await state.update_data(cls_edit_id=0, cls_edit_field="goodnight_time")
    await callback.message.edit_text(
        "⏰ زمان ارسال پیام شب را بفرستید (ساعت محلی، مثلاً 22:00):",
        reply_markup=keyboards.cancel_keyboard("goodnight_menu"),
    )


@router.callback_query(F.data == "goodnight_text_set")
async def goodnight_text_set_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ClassEditFlow.waiting_value)
    await state.update_data(cls_edit_id=0, cls_edit_field="goodnight_text")
    await callback.message.edit_text(
        "✏️ متن پیام شب را بفرستید:",
        reply_markup=keyboards.cancel_keyboard("goodnight_menu"),
    )


@router.callback_query(F.data == "tz_menu")
async def tz_menu_handler(callback: CallbackQuery):
    """Pick the project display timezone (class times stay in Tehran time)."""
    await callback.answer()
    current = await models.get_setting("timezone", "Asia/Muscat")
    zones = ["Asia/Muscat", "Asia/Tehran", "Asia/Dubai", "Asia/Kolkata",
             "Europe/London", "Europe/Berlin"]
    kb = InlineKeyboardBuilder()
    for z in zones:
        mark = "✅ " if z == current else ""
        kb.row(InlineKeyboardButton(
            text=f"{mark}{z}", callback_data=f"tz_set:{z}"))
    kb.row(InlineKeyboardButton(text="✏️ منطقه دلخواه", callback_data="tz_custom"))
    kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="goodnight_menu"))
    await callback.message.edit_text(
        f"🌍 <b>منطقه زمانی پروژه</b>\n\n"
        f"فعلی: <b>{current}</b>\n\n"
        "زمان کلاس‌ها به ساعت ایران ذخیره می‌شود و برای نمایش/ارسال "
        "به این منطقه تبدیل می‌شود.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tz_set:"))
async def tz_set_handler(callback: CallbackQuery):
    await callback.answer()
    tz = callback.data.split(":", 1)[1]
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        await callback.answer("❌ منطقه زمانی نامعتبر است!", show_alert=True)
        return
    await models.set_setting("timezone", tz, "project display timezone")
    await models.add_log(callback.from_user.id, callback.from_user.username or "",
                         "set_timezone", tz)
    await callback.answer(f"✅ منطقه زمانی: {tz}", show_alert=True)
    await tz_menu_handler(callback)


@router.callback_query(F.data == "tz_custom")
async def tz_custom_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ClassEditFlow.waiting_value)
    await state.update_data(cls_edit_id=0, cls_edit_field="timezone")
    await callback.message.edit_text(
        "🌍 نام منطقه زمانی IANA را بفرستید (مثلاً Asia/Riyadh):",
        reply_markup=keyboards.cancel_keyboard("tz_menu"),
    )

