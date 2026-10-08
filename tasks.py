"""
Tasks (تکالیف) router for Bot-File-School.

User side:  "📚 تکالیف" in the main menu shows all registered tasks,
grouped by category, read live from the database.

Admin side:  "📚 ثبت تکلیف" panel inside the admin panel:
  ➕ ثبت موضوع / دسته‌بندی   (create a category)
  📝 ثبت تکلیف              (pick an existing category, then title, then details)
  📋 مشاهده تکالیف ثبت‌شده   (browse/delete tasks)

All flows include ❌ لغو عملیات / 🔙 بازگشت buttons and validation.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

import models
import keyboards
from permissions import is_admin
from utils import escape_html
from logger import logger

router = Router()


class TaskCatAddFlow(StatesGroup):
    waiting_name = State()


class TaskCatRenameFlow(StatesGroup):
    waiting_name = State()


class TaskAddFlow(StatesGroup):
    entering_title = State()
    entering_details = State()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _format_tasks_for_user(grouped: dict) -> str:
    """Grouped, RTL-friendly display:
    📚 تکالیف
    ━━━━━━━━━━━━━━━
    📐 category
    📝 title
    details
    ━━━━━━━━━━━━━━━
    """
    lines = ["📚 <b>تکالیف</b>", "━━━━━━━━━━━━━━━"]
    for cat, tasks in grouped.items():
        lines.append(f"📁 <b>{escape_html(cat)}</b>")
        for t in tasks:
            lines.append(f"📝 <b>{escape_html(t['title'])}</b>")
            if t["details"]:
                lines.append(escape_html(t["details"]))
            lines.append("")  # blank line between tasks
        lines.append("━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ─── User Side ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_tasks")
async def menu_tasks_handler(callback: CallbackQuery):
    """Show all tasks grouped by category to any user."""
    await callback.answer()
    grouped = await models.get_all_tasks_grouped()
    if not grouped:
        await callback.message.edit_text(
            "📚 در حال حاضر تکلیفی ثبت نشده است.",
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return
    await callback.message.edit_text(
        _format_tasks_for_user(grouped),
        reply_markup=keyboards.main_menu_keyboard(),
        parse_mode="HTML",
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
async def tasks_task_add_handler(callback: CallbackQuery):
    """Step 1: dynamically list existing categories to pick from."""
    await callback.answer()
    cats = await models.get_task_categories()
    if not cats:
        await callback.message.edit_text(
            "❌ هنوز هیچ دسته‌بندی‌ای ثبت نشده است.\n"
            "ابتدا یک دسته‌بندی بسازید:",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )
        return
    await callback.message.edit_text(
        "📁 <b>انتخاب دسته‌بندی</b>\n\n"
        "دسته‌بندی تکلیف را انتخاب کنید:",
        reply_markup=keyboards.task_categories_keyboard(cats, "pick"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_cat_pick:"))
async def tasks_cat_picked_handler(callback: CallbackQuery, state: FSMContext):
    """Step 2: category picked -> ask for title."""
    await callback.answer()
    cat_id = int(callback.data.split(":")[1])
    cat = await models.get_task_category_by_id(cat_id)
    if not cat:
        await callback.answer("❌ دسته‌بندی یافت نشد!", show_alert=True)
        return
    await state.set_state(TaskAddFlow.entering_title)
    await state.update_data(task_cat_id=cat_id, task_cat_name=cat["name"])
    await callback.message.edit_text(
        f"📁 دسته‌بندی: <b>{escape_html(cat['name'])}</b>\n\n"
        "📝 <b>عنوان/موضوع تکلیف</b> را ارسال کنید\n(مثلاً: حل صفحه ۲۲ ریاضی):",
        reply_markup=keyboards.task_cancel_keyboard(),
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
        "📋 <b>جزئیات کامل تکلیف</b> را ارسال کنید\n"
        "(مثلاً: سوالات ۱ تا ۱۰ صفحه ۲۲ را کامل حل کنید...):",
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
    data = await state.get_data()
    cat_id = data.get("task_cat_id")
    title = data.get("task_title", "")
    task_id = await models.create_task(cat_id, title, details, message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ <b>تکلیف ثبت شد!</b>\n\n"
        f"🆔 شناسه: <code>{task_id}</code>\n"
        f"📁 دسته‌بندی: {escape_html(data.get('task_cat_name', ''))}\n"
        f"📝 {escape_html(title)}\n\n"
        f"{escape_html(details)}",
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
        parse_mode="HTML",
    )
    await models.add_log(
        message.from_user.id, message.from_user.username or "",
        "add_task", f"#{task_id} [{data.get('task_cat_name')}] {title}",
    )
    logger.info(f"Task #{task_id} created by {message.from_user.id}: {title}")


@router.message(StateFilter(TaskAddFlow.entering_details))
async def tasks_task_details_not_text(message: Message):
    await message.answer("❌ لطفاً جزئیات را به‌صورت متن ارسال کنید:")


# ─── Admin: List / Delete Tasks ─────────────────────────────────────────────

@router.callback_query(F.data == "tasks_admin_list")
async def tasks_admin_list_handler(callback: CallbackQuery):
    await callback.answer()
    grouped = await models.get_all_tasks_grouped()
    if not grouped:
        await callback.message.edit_text(
            "📚 در حال حاضر تکلیفی ثبت نشده است.",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )
        return
    # Same grouped text as user view + tappable task IDs for deletion
    lines = ["📚 <b>تکالیف ثبت‌شده</b>", "━━━━━━━━━━━━━━━"]
    for cat, tasks in grouped.items():
        lines.append(f"📁 <b>{escape_html(cat)}</b>")
        for t in tasks:
            lines.append(
                f"📝 <b>{escape_html(t['title'])}</b> "
                f"<code>(#{t['id']})</code>"
            )
        lines.append("━━━━━━━━━━━━━━━")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=keyboards.admin_tasks_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tasks_task_delete:"))
async def tasks_task_delete_handler(callback: CallbackQuery):
    await callback.answer()
    task_id = int(callback.data.split(":")[1])
    task = await models.get_task_by_id(task_id)
    if not task:
        await callback.answer("❌ تکلیف یافت نشد!", show_alert=True)
        return
    await models.delete_task(task_id)
    await callback.answer("🗑 تکلیف حذف شد.", show_alert=True)
    await models.add_log(
        callback.from_user.id, callback.from_user.username or "",
        "delete_task", f"#{task_id}: {task['title']}",
    )
    grouped = await models.get_all_tasks_grouped()
    if grouped:
        lines = ["📚 <b>تکالیف ثبت‌شده</b>", "━━━━━━━━━━━━━━━"]
        for cat, tasks in grouped.items():
            lines.append(f"📁 <b>{escape_html(cat)}</b>")
            for t in tasks:
                lines.append(f"📝 <b>{escape_html(t['title'])}</b> <code>(#{t['id']})</code>")
            lines.append("━━━━━━━━━━━━━━━")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "📚 هیچ تکلیف فعالی باقی نمانده است.",
            reply_markup=keyboards.admin_tasks_menu_keyboard(),
        )


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
