"""
Tasks (تکالیف) router for Bot-File-School.

User side:  "📚 تکالیف" lists active assignments and exposes their details,
weekday, subject, deadline, and optional image.

Admin side: assignments are attached to a field and subject, then capture
title, instructions, weekday, Jalali deadline, and an optional image.

All flows include ❌ لغو عملیات / 🔙 بازگشت buttons and validation.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import models
import keyboards
from utils import escape_html
from logger import logger

router = Router()


class TaskCatAddFlow(StatesGroup):
    waiting_name = State()


class TaskCatRenameFlow(StatesGroup):
    waiting_name = State()


class TaskAddFlow(StatesGroup):
    selecting_field = State()
    selecting_subject = State()
    entering_title = State()
    entering_details = State()
    choosing_day = State()
    entering_deadline = State()
    entering_image = State()


TASK_LIST_PAGE_SIZE = 10
TASK_DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _normalize_digits(value: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    arabic = "٠١٢٣٤٥٦٧٨٩"
    for index, digit in enumerate(persian):
        value = value.replace(digit, str(index))
    for index, digit in enumerate(arabic):
        value = value.replace(digit, str(index))
    return value


def _parse_jalali_deadline(value: str) -> str:
    import jdatetime

    value = _normalize_digits(value.strip()).replace("-", "/")
    try:
        jalali = jdatetime.datetime.strptime(value, "%Y/%m/%d %H:%M")
        local = jalali.togregorian().replace(tzinfo=TEHRAN_TZ)
    except (ValueError, OverflowError) as exc:
        raise ValueError("تاریخ را به شکل ۱۴۰۵/۰۷/۲۵ ۲۳:۵۹ وارد کنید.") from exc
    if local <= datetime.now(TEHRAN_TZ):
        raise ValueError("مهلت تحویل باید در آینده باشد.")
    return local.astimezone(timezone.utc).replace(tzinfo=None).isoformat(
        sep=" ", timespec="seconds"
    )


def _format_deadline(value: str | None) -> str:
    if not value:
        return "تعیین نشده"
    import jdatetime

    utc_value = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    local = utc_value.astimezone(TEHRAN_TZ).replace(tzinfo=None)
    return jdatetime.datetime.fromgregorian(datetime=local).strftime(
        "%Y/%m/%d ساعت %H:%M"
    )


# ─── Helpers ────────────────────────────────────────────────────────────────

def _task_overview_text(tasks: list, page: int) -> str:
    lines = ["📚 <b>تکالیف فعال</b>", f"صفحه {page + 1}", "━━━━━━━━━━━━━━━"]
    for task in tasks:
        lines.append(f"📝 <b>{escape_html(task['title'])}</b>")
        field = task["field_name"] or "رشته ثبت نشده"
        subject = task["subject_name"] or task["category_name"] or "درس ثبت نشده"
        lines.append(f"📚 {escape_html(field)} · 📖 {escape_html(subject)}")
        if task["day_index"] is not None:
            lines.append(f"📅 روز تکلیف: {TASK_DAYS[task['day_index']]}")
        if task["due_at"]:
            lines.append(f"⏰ مهلت: {escape_html(_format_deadline(task['due_at']))}")
        lines.append("━━━━━━━━━━━━━━━")
    return "\n".join(lines)


async def _show_user_tasks(callback: CallbackQuery, page: int) -> None:
    await callback.answer()
    offset = page * TASK_LIST_PAGE_SIZE
    tasks = await models.get_active_tasks(
        limit=TASK_LIST_PAGE_SIZE + 1, offset=offset
    )
    if page > 0 and not tasks:
        await callback.message.answer("این صفحه دیگر تکلیفی ندارد؛ فهرست را تازه کنید.")
        return
    has_more = len(tasks) > TASK_LIST_PAGE_SIZE
    tasks = tasks[:TASK_LIST_PAGE_SIZE]
    if not tasks:
        await callback.message.edit_text(
            "📚 در حال حاضر تکلیف فعالی ثبت نشده است.",
            reply_markup=await keyboards.main_menu_keyboard_for(callback.from_user.id),
        )
        return
    await callback.message.edit_text(
        _task_overview_text(tasks, page),
        reply_markup=keyboards.task_user_list_keyboard(tasks, page, has_more),
        parse_mode="HTML",
    )


async def _show_admin_tasks(
    callback: CallbackQuery, page: int, *, answer_callback: bool = True
) -> None:
    if answer_callback:
        await callback.answer()
    offset = page * TASK_LIST_PAGE_SIZE
    tasks = await models.get_active_tasks(
        limit=TASK_LIST_PAGE_SIZE + 1, offset=offset
    )
    has_more = len(tasks) > TASK_LIST_PAGE_SIZE
    tasks = tasks[:TASK_LIST_PAGE_SIZE]
    if not tasks:
        await callback.message.edit_text(
            "📚 در حال حاضر تکلیف فعالی ثبت نشده است.",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )
        return
    await callback.message.edit_text(
        f"📚 <b>تکالیف ثبت‌شده</b>\nصفحه {page + 1} — برای دیدن جزئیات انتخاب کنید:",
        reply_markup=keyboards.task_admin_list_keyboard(tasks, page, has_more),
        parse_mode="HTML",
    )


def _task_detail_text(task) -> str:
    field = task["field_name"] or "ثبت نشده"
    subject = task["subject_name"] or task["category_name"] or "ثبت نشده"
    day = (
        TASK_DAYS[task["day_index"]]
        if task["day_index"] is not None else "ثبت نشده"
    )
    return (
        f"📝 <b>{escape_html(task['title'])}</b>\n\n"
        f"📚 رشته: {escape_html(field)}\n"
        f"📖 درس: {escape_html(subject)}\n"
        f"📅 روز تکلیف: {day}\n"
        f"⏰ مهلت تحویل: {escape_html(_format_deadline(task['due_at']))}\n"
        f"🖼 تصویر: {'دارد' if task['file_id'] else 'ندارد'}\n\n"
        f"📋 <b>توضیحات</b>\n{escape_html(task['details'] or 'بدون توضیحات')}"
    )


# ─── User Side ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_tasks")
async def menu_tasks_handler(callback: CallbackQuery):
    """Show all tasks grouped by category to any user."""
    await _show_user_tasks(callback, page=0)


@router.callback_query(F.data.startswith("menu_tasks_page:"))
async def menu_tasks_page_handler(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    if page < 0:
        await callback.answer("صفحه نامعتبر است.", show_alert=True)
        return
    await _show_user_tasks(callback, page)


@router.callback_query(F.data.startswith("task_view:"))
async def task_view_handler(callback: CallbackQuery):
    _, raw_task_id, raw_page = callback.data.split(":")
    task_id, page = int(raw_task_id), int(raw_page)
    await models.expire_due_tasks()
    task = await models.get_task_by_id(task_id)
    if not task or not task["is_active"]:
        await callback.answer("این تکلیف دیگر فعال نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        _task_detail_text(task),
        reply_markup=keyboards.task_user_detail_keyboard(
            task_id, page, bool(task["file_id"])
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("task_photo:"))
async def task_photo_handler(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await models.expire_due_tasks()
    task = await models.get_task_by_id(task_id)
    if not task or not task["is_active"] or not task["file_id"]:
        await callback.answer("تصویر این تکلیف در دسترس نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer_photo(
        task["file_id"], caption=f"🖼 {escape_html(task['title'])}"
    )


# ─── Admin: Entry Menu ──────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_tasks")
async def admin_tasks_handler(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "📚 <b>مدیریت تکالیف</b>\n\n"
        "یک گزینه را انتخاب کنید:",
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
        parse_mode="HTML",
    )


# ─── Admin: Add Category ────────────────────────────────────────────────────

@router.callback_query(F.data == "tasks_cat_add")
async def tasks_cat_add_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(TaskCatAddFlow.waiting_name)
    await callback.message.edit_text(
        "➕ <b>ثبت موضوع / دسته‌بندی</b>\n\n"
        "نام دسته‌بندی را ارسال کنید (مثلاً: ریاضی فیزیک):",
        reply_markup=keyboards.task_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(StateFilter(TaskCatAddFlow.waiting_name), F.text)
async def tasks_cat_name_handler(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 80:
        await message.answer(
            "❌ نام دسته‌بندی باید بین ۲ تا ۸۰ کاراکتر باشد. دوباره ارسال کنید:",
            reply_markup=keyboards.task_cancel_keyboard(),
        )
        return
    # Uniqueness check
    existing = await models.get_task_categories()
    if any(c["name"] == name for c in existing):
        await message.answer(
            f"❌ دسته‌بندی «{escape_html(name)}» قبلاً ثبت شده است. نام دیگری بفرستید:",
            reply_markup=keyboards.task_cancel_keyboard(),
        )
        return
    cat_id = await models.create_task_category(name)
    await state.clear()
    await message.answer(
        f"✅ دسته‌بندی «<b>{escape_html(name)}</b>» ثبت شد.\n\n"
        "حالا می‌توانید تکلیف ثبت کنید:",
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "",
        "add_task_category", name,
    )
    logger.info(f"Task category '{name}' (#{cat_id}) added by {message.from_user.id}")


@router.message(StateFilter(TaskCatAddFlow.waiting_name))
async def tasks_cat_name_not_text(message: Message):
    await message.answer("❌ لطفاً نام دسته‌بندی را به‌صورت متن ارسال کنید:")


# ─── Admin: Manage Categories (rename/delete) ──────────────────────────────

@router.callback_query(F.data == "tasks_cats_manage")
async def tasks_cats_manage_handler(callback: CallbackQuery):
    await callback.answer()
    cats = await models.get_task_categories()
    if not cats:
        await callback.message.edit_text(
            "📁 هیچ دسته‌بندی‌ای ثبت نشده است. اول یکی بسازید:",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )
        return
    await callback.message.edit_text(
        "📁 <b>دسته‌بندی‌ها</b>\n\nیکی را برای مدیریت انتخاب کنید:",
        reply_markup=keyboards.task_categories_keyboard(cats, "manage"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_cat_manage:"))
async def tasks_cat_manage_detail(callback: CallbackQuery):
    await callback.answer()
    cat_id = int(callback.data.split(":")[1])
    cat = await models.get_task_category_by_id(cat_id)
    if not cat:
        await callback.answer("❌ دسته‌بندی یافت نشد!", show_alert=True)
        return
    count = len(await models.get_tasks_by_category(cat_id))
    await callback.message.edit_text(
        f"📁 <b>{escape_html(cat['name'])}</b>\n\n"
        f"📝 تعداد تکالیف فعال: {count}",
        reply_markup=keyboards.task_category_detail_keyboard(cat_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_cat_rename:"))
async def tasks_cat_rename_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cat_id = int(callback.data.split(":")[1])
    await state.set_state(TaskCatRenameFlow.waiting_name)
    await state.update_data(rename_cat_id=cat_id)
    await callback.message.edit_text(
        "✏️ نام جدید دسته‌بندی را ارسال کنید:",
        reply_markup=keyboards.task_cancel_keyboard(),
    )


@router.message(StateFilter(TaskCatRenameFlow.waiting_name), F.text)
async def tasks_cat_rename_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 80:
        await message.answer("❌ نام باید بین ۲ تا ۸۰ کاراکتر باشد. دوباره ارسال کنید:")
        return
    data = await state.get_data()
    cat_id = data.get("rename_cat_id")
    await models.rename_task_category(cat_id, name)
    await state.clear()
    await message.answer(
        f"✅ دسته‌بندی به «<b>{escape_html(name)}</b>» تغییر یافت.",
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "",
        "rename_task_category", f"#{cat_id}: {name}",
    )


@router.callback_query(F.data.startswith("tasks_cat_delete:"))
async def tasks_cat_delete_handler(callback: CallbackQuery):
    """Delete a category AND its tasks (cascade)."""
    await callback.answer()
    cat_id = int(callback.data.split(":")[1])
    cat = await models.get_task_category_by_id(cat_id)
    if not cat:
        await callback.answer("❌ دسته‌بندی یافت نشد!", show_alert=True)
        return
    removed = await models.delete_task_category(cat_id)
    await callback.answer(
        f"🗑 دسته‌بندی و {removed} تکلیف آن حذف شد.", show_alert=True)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "",
        "delete_task_category", f"{cat['name']} ({removed} tasks)",
    )
    cats = await models.get_task_categories()
    if cats:
        await callback.message.edit_text(
            "📁 <b>دسته‌بندی‌ها</b>",
            reply_markup=keyboards.task_categories_keyboard(cats, "manage"),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "📁 همه دسته‌بندی‌ها حذف شدند.",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )


# ─── Admin: Add Task ────────────────────────────────────────────────────────

@router.callback_query(F.data == "tasks_task_add")
async def tasks_task_add_handler(callback: CallbackQuery, state: FSMContext):
    """Start assignment creation by selecting its field."""
    await callback.answer()
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "❌ ابتدا رشته و درس را از بخش مدیریت رشته‌ها ثبت کنید.",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )
        return
    await state.set_state(TaskAddFlow.selecting_field)
    await state.update_data(task_category_id=None, task_category_name=None)
    await callback.message.edit_text(
        "📚 <b>انتخاب رشته تکلیف</b>",
        reply_markup=keyboards.task_fields_keyboard(fields),
        parse_mode="HTML",
    )


async def _show_task_subjects(
    callback: CallbackQuery, state: FSMContext, field_id: int, category_id: int | None = None
) -> None:
    field = await models.get_field_by_id(field_id)
    if not field:
        await callback.message.answer("❌ رشته پیدا نشد.")
        return
    subjects = await models.get_subjects_by_field(field_id)
    if not subjects:
        await callback.message.answer("❌ برای این رشته درسی ثبت نشده است.")
        return
    await state.set_state(TaskAddFlow.selecting_subject)
    await state.update_data(
        task_field_id=field_id,
        task_field_name=field["name"],
        task_category_id=category_id,
    )
    await callback.message.edit_text(
        f"📚 رشته: <b>{escape_html(field['name'])}</b>\n\n"
        "📖 درس تکلیف را انتخاب کنید:",
        reply_markup=keyboards.task_subjects_keyboard(subjects),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_field:"))
async def tasks_field_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != TaskAddFlow.selecting_field.state:
        await callback.answer("ابتدا ثبت تکلیف را شروع کنید.", show_alert=True)
        return
    await callback.answer()
    field_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    await _show_task_subjects(
        callback, state, field_id, data.get("task_category_id")
    )


@router.callback_query(F.data.startswith("tasks_subject:"))
async def tasks_subject_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != TaskAddFlow.selecting_subject.state:
        await callback.answer("ابتدا رشته تکلیف را انتخاب کنید.", show_alert=True)
        return
    subject_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    subject = await models.get_subject_by_id(subject_id)
    if not subject or subject["field_id"] != data.get("task_field_id"):
        await callback.answer("این درس با رشته انتخاب‌شده هماهنگ نیست.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(
        task_subject_id=subject_id, task_subject_name=subject["name"]
    )
    await state.set_state(TaskAddFlow.entering_title)
    await callback.message.edit_text(
        f"📚 رشته: <b>{escape_html(data['task_field_name'])}</b>\n"
        f"📖 درس: <b>{escape_html(subject['name'])}</b>\n\n"
        "📝 عنوان تکلیف را ارسال کنید:",
        reply_markup=keyboards.task_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_cat_pick:"))
async def tasks_cat_picked_handler(callback: CallbackQuery, state: FSMContext):
    """Compatibility path for old category keyboards; continue with field/subject."""
    await callback.answer()
    cat_id = int(callback.data.split(":")[1])
    cat = await models.get_task_category_by_id(cat_id)
    if not cat:
        await callback.answer("❌ دسته‌بندی یافت نشد!", show_alert=True)
        return
    await state.update_data(task_category_id=cat_id, task_category_name=cat["name"])
    await state.set_state(TaskAddFlow.selecting_field)
    fields = await models.get_fields()
    if not fields:
        await callback.message.edit_text(
            "❌ ابتدا رشته و درس را از بخش مدیریت رشته‌ها ثبت کنید.",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )
        return
    await callback.message.edit_text(
        f"📁 دسته‌بندی: <b>{escape_html(cat['name'])}</b>\n\n"
        "📚 رشته تکلیف را انتخاب کنید:",
        reply_markup=keyboards.task_fields_keyboard(fields),
        parse_mode="HTML",
    )


@router.message(StateFilter(TaskAddFlow.entering_title), F.text)
async def tasks_task_title_handler(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 3 or len(title) > 200:
        await message.answer(
            "❌ عنوان باید بین ۳ تا ۲۰۰ کاراکتر باشد. دوباره ارسال کنید:",
            reply_markup=keyboards.task_cancel_keyboard(),
        )
        return
    await state.update_data(task_title=title)
    await state.set_state(TaskAddFlow.entering_details)
    await message.answer(
        f"✅ عنوان: <b>{escape_html(title)}</b>\n\n"
        "📋 توضیحات تکلیف را ارسال کنید:",
        reply_markup=keyboards.task_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(StateFilter(TaskAddFlow.entering_title))
async def tasks_task_title_not_text(message: Message):
    await message.answer("❌ لطفاً عنوان را به‌صورت متن ارسال کنید:")


@router.message(StateFilter(TaskAddFlow.entering_details), F.text)
async def tasks_task_details_handler(message: Message, state: FSMContext):
    details = message.text.strip()
    if len(details) < 3 or len(details) > 2000:
        await message.answer(
            "❌ جزئیات باید بین ۳ تا ۲۰۰۰ کاراکتر باشد. دوباره ارسال کنید:",
            reply_markup=keyboards.task_cancel_keyboard(),
        )
        return
    await state.update_data(task_details=details)
    await state.set_state(TaskAddFlow.choosing_day)
    await message.answer(
        "📅 روزی که تکلیف برای آن تعیین شده را انتخاب کنید:",
        reply_markup=keyboards.task_days_keyboard(),
        parse_mode="HTML",
    )


@router.message(StateFilter(TaskAddFlow.entering_details))
async def tasks_task_details_not_text(message: Message):
    await message.answer("❌ لطفاً جزئیات را به‌صورت متن ارسال کنید:")


@router.callback_query(F.data.startswith("tasks_day:"))
async def tasks_day_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != TaskAddFlow.choosing_day.state:
        await callback.answer("ابتدا توضیحات تکلیف را ثبت کنید.", show_alert=True)
        return
    day_index = int(callback.data.split(":")[1])
    if not 0 <= day_index < len(TASK_DAYS):
        await callback.answer("روز نامعتبر است.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(task_day_index=day_index)
    await state.set_state(TaskAddFlow.entering_deadline)
    await callback.message.edit_text(
        f"📅 روز تکلیف: <b>{TASK_DAYS[day_index]}</b>\n\n"
        "⏰ مهلت تحویل را به تقویم شمسی و ساعت تهران بفرستید.\n"
        "نمونه: <code>۱۴۰۵/۰۷/۲۵ ۲۳:۵۹</code>",
        reply_markup=keyboards.task_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(StateFilter(TaskAddFlow.entering_deadline), F.text)
async def tasks_deadline_handler(message: Message, state: FSMContext):
    try:
        due_at = _parse_jalali_deadline(message.text)
    except ValueError as exc:
        await message.answer(f"❌ {escape_html(str(exc))}\nدوباره تلاش کنید:")
        return
    await state.update_data(task_due_at=due_at)
    await state.set_state(TaskAddFlow.entering_image)
    await message.answer(
        "🖼 تصویر تکلیف را ارسال کنید؛ اگر تصویر ندارد، «رد» را بفرستید.",
        reply_markup=keyboards.task_cancel_keyboard(),
    )


@router.message(StateFilter(TaskAddFlow.entering_deadline))
async def tasks_deadline_not_text(message: Message):
    await message.answer("❌ مهلت را به‌صورت متن و طبق نمونه ارسال کنید.")


async def _save_task(message: Message, state: FSMContext, file_id: str | None) -> None:
    data = await state.get_data()
    category_id = data.get("task_category_id")
    if category_id is None:
        category_id = await models.get_or_create_task_category(
            f"{data['task_field_name']} / {data['task_subject_name']}"
        )
    task_id = await models.create_task(
        category_id,
        data["task_title"],
        data["task_details"],
        message.from_user.id,
        field_id=data["task_field_id"],
        subject_id=data["task_subject_id"],
        day_index=data["task_day_index"],
        due_at=data["task_due_at"],
        file_id=file_id,
    )
    summary_task = {
        "id": task_id,
        "title": data["task_title"],
        "details": data["task_details"],
        "field_name": data["task_field_name"],
        "subject_name": data["task_subject_name"],
        "day_index": data["task_day_index"],
        "due_at": data["task_due_at"],
        "file_id": file_id,
        "category_name": data.get("task_category_name", ""),
    }
    await state.clear()
    await message.answer(
        f"✅ <b>تکلیف ثبت شد</b>\n\n{_task_detail_text(summary_task)}",
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "",
        "add_task", f"#{task_id}: {data['task_title']}",
    )
    logger.info(f"Task #{task_id} created by {message.from_user.id}: {data['task_title']}")


@router.message(StateFilter(TaskAddFlow.entering_image), F.photo)
async def tasks_image_photo_handler(message: Message, state: FSMContext):
    await _save_task(message, state, message.photo[-1].file_id)


@router.message(StateFilter(TaskAddFlow.entering_image), F.document)
async def tasks_image_document_handler(message: Message, state: FSMContext):
    document = message.document
    if not (document.mime_type or "").lower().startswith("image/"):
        await message.answer("❌ لطفاً یک تصویر بفرستید یا «رد» را برای بدون تصویر ارسال کنید.")
        return
    await _save_task(message, state, document.file_id)


@router.message(StateFilter(TaskAddFlow.entering_image), F.text)
async def tasks_skip_image_handler(message: Message, state: FSMContext):
    if (message.text or "").strip().casefold() not in {"رد", "بدون عکس", "بدون تصویر"}:
        await message.answer("برای تکمیل، تصویر بفرستید یا عبارت «رد» را ارسال کنید.")
        return
    await _save_task(message, state, None)


@router.message(StateFilter(TaskAddFlow.entering_image))
async def tasks_image_invalid_handler(message: Message):
    await message.answer("❌ نوع فایل پشتیبانی نمی‌شود؛ تصویر بفرستید یا «رد» را ارسال کنید.")


# ─── Admin: List / Delete Tasks ─────────────────────────────────────────────

@router.callback_query(F.data == "tasks_admin_list")
async def tasks_admin_list_handler(callback: CallbackQuery):
    await _show_admin_tasks(callback, page=0)


@router.callback_query(F.data.startswith("tasks_admin_page:"))
async def tasks_admin_page_handler(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    if page < 0:
        await callback.answer("صفحه نامعتبر است.", show_alert=True)
        return
    await _show_admin_tasks(callback, page)


@router.callback_query(F.data.startswith("tasks_admin_view:"))
async def tasks_admin_view_handler(callback: CallbackQuery):
    _, raw_task_id, raw_page = callback.data.split(":")
    task_id, page = int(raw_task_id), int(raw_page)
    await models.expire_due_tasks()
    task = await models.get_task_by_id(task_id)
    if not task or not task["is_active"]:
        await callback.answer("این تکلیف دیگر فعال نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        _task_detail_text(task),
        reply_markup=keyboards.task_admin_detail_keyboard(task_id, page),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_task_delete:"))
async def tasks_task_delete_handler(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    task = await models.get_task_by_id(task_id)
    if not task:
        await callback.answer("❌ تکلیف یافت نشد!", show_alert=True)
        return
    if not task["is_active"]:
        await callback.answer("این تکلیف دیگر فعال نیست.", show_alert=True)
        return
    await models.delete_task(task_id)
    await callback.answer("🗑 تکلیف حذف شد.", show_alert=True)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "",
        "delete_task", f"#{task_id}: {task['title']}",
    )
    await _show_admin_tasks(callback, page=0, answer_callback=False)


# ─── Cancel ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tasks_flow_cancel")
async def tasks_flow_cancel_handler(callback: CallbackQuery, state: FSMContext):
    """Cancel any tasks FSM flow - nothing is saved."""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "❌ عملیات لغو شد. هیچ چیزی ثبت نشد.",
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
    )
