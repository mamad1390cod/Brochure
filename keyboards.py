"""
Inline keyboard builders for Bot-File-School.
All user interactions use inline keyboards.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ─── Shared Small Keyboards ─────────────────────────────────────────────────

def cancel_keyboard(callback_data: str = "generic_cancel") -> InlineKeyboardMarkup:
    """A single cancel button - used during FSM text-input steps."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="❌ لغو عملیات", callback_data=callback_data),
    )
    return kb.as_markup()


# ─── Main Menus ──────────────────────────────────────────────────────────────

def main_menu_keyboard(has_admin_access: bool = False) -> InlineKeyboardMarkup:
    """Build the user menu and optionally expose the admin-panel entry."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📚 مشاهده جزوه‌ها", callback_data="menu_fields"),
    )
    kb.row(
        InlineKeyboardButton(text="➕ ثبت جزوه", callback_data="submit_note_start"),
    )
    kb.row(
        InlineKeyboardButton(text="🛠 ابزارهای فایل", callback_data="menu_tools"),
        InlineKeyboardButton(text="🗓 برنامه هفتگی کلاس", callback_data="menu_schedule"),
    )
    kb.row(
        InlineKeyboardButton(text="📄 ساخت PDF", callback_data="menu_make_pdf"),
        InlineKeyboardButton(text="📚 تکالیف", callback_data="menu_tasks"),
    )
    if has_admin_access:
        kb.row(
            InlineKeyboardButton(text="⚙️ پنل مدیریت", callback_data="admin_login"),
        )
    return kb.as_markup()


async def main_menu_keyboard_for(user_id: int) -> InlineKeyboardMarkup:
    """Show the admin entry only to an active, database-backed admin or Owner."""
    from permissions import is_admin

    return main_menu_keyboard(await is_admin(user_id))


def auto_columns_keyboard(items: list, back: tuple | None = None) -> InlineKeyboardMarkup:
    """Lay out (label, callback) pairs in 1/2/3 columns automatically:
    <=5 items -> 1 column, 6..14 -> 2 columns, >14 -> 3 columns."""
    kb = InlineKeyboardBuilder()
    n = len(items)
    cols = 1 if n <= 5 else (2 if n <= 14 else 3)
    row = []
    for label, cb in items:
        row.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(row) == cols:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    if back:
        kb.row(InlineKeyboardButton(text=back[0], callback_data=back[1]))
    return kb.as_markup()


async def admin_main_menu_keyboard_for(user_id: int) -> InlineKeyboardMarkup:
    """Permission-based admin panel: only buttons whose permission the
    admin currently has (live from DB) are shown. Layout is automatic
    1/2/3 columns and labels are short."""
    from permissions import check_permission, is_owner
    owner = await is_owner(user_id)

    # (short label, callback, permission key) — order = display order
    entries = [
        ("📚 رشته‌ها", "admin_fields", "manage_fields"),
        ("📖 درس‌ها", "admin_subjects", "manage_fields"),
        ("📕 فصل‌ها", "admin_chapters", "manage_fields"),
        ("📄 جزوه‌ها", "admin_notes", "view_notes"),
        ("⏳ در انتظار", "admin_pending", "view_notes"),
        ("📅 برنامه", "admin_schedule", "manage_schedule"),
        ("🟢 کلاس‌ها", "admin_classes", "manage_classes"),
        ("📚 تکالیف", "admin_tasks", "manage_tasks"),
        ("🛠 تبدیل فایل", "admin_convert_start", "convert_files"),
        ("👥 کاربران", "admin_users", "manage_users"),
        ("👤 ادمین‌ها", "admin_admins", "manage_admins"),
        ("📋 لاگ‌ها", "admin_logs", "view_logs"),
        ("📊 آمار", "admin_stats", "view_stats"),
        ("⚙️ تنظیمات", "admin_settings", "manage_settings"),
    ]
    items = []
    for label, cb, perm in entries:
        if perm is None or owner or await check_permission(user_id, perm):
            items.append((label, cb))

    kb = InlineKeyboardBuilder()
    cols = 1 if len(items) <= 5 else (2 if len(items) <= 14 else 3)
    row = []
    for label, cb in items:
        row.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(row) == cols:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    kb.row(InlineKeyboardButton(text="🔙 خروج از پنل", callback_data="admin_logout"))
    return kb.as_markup()


def admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Fallback full panel (used before we know which admin is calling).
    Prefer admin_main_menu_keyboard_for() for permission-based menus."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📚 رشته‌ها", callback_data="admin_fields"),
        InlineKeyboardButton(text="📖 درس‌ها", callback_data="admin_subjects"),
    )
    kb.row(
        InlineKeyboardButton(text="📕 فصل‌ها", callback_data="admin_chapters"),
        InlineKeyboardButton(text="📄 جزوه‌ها", callback_data="admin_notes"),
    )
    kb.row(
        InlineKeyboardButton(text="⏳ در انتظار", callback_data="admin_pending"),
    )
    kb.row(
        InlineKeyboardButton(text="📅 برنامه", callback_data="admin_schedule"),
        InlineKeyboardButton(text="🟢 کلاس‌ها", callback_data="admin_classes"),
    )
    kb.row(
        InlineKeyboardButton(text="📚 تکالیف", callback_data="admin_tasks"),
        InlineKeyboardButton(text="🛠 تبدیل فایل", callback_data="admin_convert_start"),
    )
    kb.row(
        InlineKeyboardButton(text="👥 کاربران", callback_data="admin_users"),
        InlineKeyboardButton(text="👤 ادمین‌ها", callback_data="admin_admins"),
    )
    kb.row(
        InlineKeyboardButton(text="📋 لاگ‌ها", callback_data="admin_logs"),
        InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="admin_settings"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 خروج از پنل", callback_data="admin_logout"),
    )
    return kb.as_markup()


def admin_login_keyboard() -> InlineKeyboardMarkup:
    """Admin login prompt keyboard."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🔐 ورود به پنل مدیریت", callback_data="admin_login"),
    )
    return kb.as_markup()


def image_conversion_mode_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🖼️ یک تصویر", callback_data="tool_images_single"),
        InlineKeyboardButton(text="🖼️🖼️ چند تصویر", callback_data="tool_images_multi"),
    )
    kb.row(
        InlineKeyboardButton(text="❌ لغو عملیات", callback_data="tools_cancel"),
    )
    return kb.as_markup()


# ─── User Browsing ───────────────────────────────────────────────────────────

def user_fields_keyboard(fields: list) -> InlineKeyboardMarkup:
    """Keyboard listing study fields for regular users (browse only)."""
    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}",
                callback_data=f"user_field:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu_main"),
    )
    return kb.as_markup()


# ─── Field Management ────────────────────────────────────────────────────────

def fields_list_keyboard(fields: list) -> InlineKeyboardMarkup:
    """Keyboard listing study fields with management options."""
    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}",
                callback_data=f"field_view:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="➕ افزودن", callback_data="field_add"),
        InlineKeyboardButton(text="🗑 حذف گروهی", callback_data="field_bulk_delete"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_fields_back"),
    )
    return kb.as_markup()


def field_detail_keyboard(field_id: int) -> InlineKeyboardMarkup:
    """Keyboard for a specific field's management."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📖 درس‌ها", callback_data=f"field_subjects:{field_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="✏️ ویرایش نام", callback_data=f"field_edit:{field_id}"),
        InlineKeyboardButton(text="🗑 حذف", callback_data=f"field_delete:{field_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_fields"),
    )
    return kb.as_markup()


def field_bulk_delete_keyboard(fields: list) -> InlineKeyboardMarkup:
    """Keyboard for bulk field deletion with checkboxes."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🗑 حذف همه", callback_data="field_delete_all"),
    )
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"⬜ {field['name']}",
                callback_data=f"field_toggle_delete:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🗑 حذف انتخاب‌شده‌ها", callback_data="field_confirm_bulk_delete"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_fields"),
    )
    return kb.as_markup()


# ─── Subject Management ──────────────────────────────────────────────────────

def subjects_list_keyboard(subjects: list, field_id: int) -> InlineKeyboardBuilder:
    """Keyboard listing subjects for a field."""
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {subject['name']}",
                callback_data=f"subject_view:{subject['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="➕ افزودن درس", callback_data=f"subject_add:{field_id}"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"field_view:{field_id}"),
    )
    return kb


def subject_detail_keyboard(subject_id: int, field_id: int) -> InlineKeyboardMarkup:
    """Keyboard for a specific subject's management."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📕 فصل‌ها", callback_data=f"subject_chapters:{subject_id}"),
        InlineKeyboardButton(text="📄 جزوه‌ها", callback_data=f"subject_notes:{subject_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"subject_edit:{subject_id}"),
        InlineKeyboardButton(text="🗑 حذف", callback_data=f"subject_delete:{subject_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"field_subjects:{field_id}"),
    )
    return kb.as_markup()


# ─── Chapter Management ──────────────────────────────────────────────────────

def chapters_list_keyboard(chapters: list, subject_id: int) -> InlineKeyboardMarkup:
    """Keyboard listing chapters for a subject."""
    kb = InlineKeyboardBuilder()
    for chapter in chapters:
        kb.row(
            InlineKeyboardButton(
                text=f"📕 {chapter['name']}",
                callback_data=f"chapter_view:{chapter['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="➕ افزودن فصل", callback_data=f"chapter_add:{subject_id}"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"subject_chapters_back:{subject_id}"),
    )
    return kb.as_markup()


def chapter_detail_keyboard(chapter_id: int, subject_id: int) -> InlineKeyboardMarkup:
    """Keyboard for a specific chapter's management."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📄 جزوه‌ها", callback_data=f"chapter_notes:{chapter_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"chapter_edit:{chapter_id}"),
        InlineKeyboardButton(text="🗑 حذف", callback_data=f"chapter_delete:{chapter_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"subject_chapters:{subject_id}"),
    )
    return kb.as_markup()


# ─── Notes Browsing ─────────────────────────────────────────────────────────

def notes_list_keyboard(notes: list, page: int = 0, has_more: bool = False) -> InlineKeyboardMarkup:
    """Keyboard listing notes with pagination."""
    kb = InlineKeyboardBuilder()
    for note in notes:
        title = note["title"][:30] + "..." if len(note["title"]) > 30 else note["title"]
        kb.row(
            InlineKeyboardButton(
                text=f"📄 {title}",
                callback_data=f"note_view:{note['id']}",
            )
        )
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"notes_page:{page - 1}"))
    if has_more:
        nav_row.append(InlineKeyboardButton(text="➡️ بعدی", callback_data=f"notes_page:{page + 1}"))
    if nav_row:
        kb.row(*nav_row)
    return kb.as_markup()


def note_detail_keyboard(note_id: int, context: str = "user") -> InlineKeyboardMarkup:
    """Keyboard for viewing a note's details."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📥 دریافت جزوه", callback_data=f"note_download:{note_id}"),
    )
    if context == "admin":
        kb.row(
            InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"note_edit:{note_id}"),
            InlineKeyboardButton(text="🗑 حذف", callback_data=f"note_delete:{note_id}"),
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"note_back:{context}"),
    )
    return kb.as_markup()


# ─── Note Submission Flow ────────────────────────────────────────────────────

def submit_field_keyboard(fields: list) -> InlineKeyboardMarkup:
    """Keyboard for selecting a field during note submission."""
    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}",
                callback_data=f"submit_field:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="❌ لغو", callback_data="submit_cancel"),
    )
    return kb.as_markup()


def submit_subject_keyboard(subjects: list, field_id: int) -> InlineKeyboardMarkup:
    """Keyboard for selecting a subject during note submission."""
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {subject['name']}",
                callback_data=f"submit_subject:{subject['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="submit_note_start"),
        InlineKeyboardButton(text="❌ لغو", callback_data="submit_cancel"),
    )
    return kb.as_markup()


def submit_chapter_keyboard(chapters: list, subject_id: int) -> InlineKeyboardMarkup:
    """Keyboard for selecting a chapter during note submission."""
    kb = InlineKeyboardBuilder()
    for chapter in chapters:
        kb.row(
            InlineKeyboardButton(
                text=f"📕 {chapter['name']}",
                callback_data=f"submit_chapter:{chapter['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="⏭ بدون فصل", callback_data=f"submit_no_chapter:{subject_id}"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"submit_back_subject:{subject_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="❌ لغو", callback_data="submit_cancel"),
    )
    return kb.as_markup()


# ─── Approval Keyboard ──────────────────────────────────────────────────────

def note_approval_keyboard(note_id: int) -> InlineKeyboardMarkup:
    """Keyboard for admin to approve/reject a pending note."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ قبول", callback_data=f"approve:{note_id}"),
        InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{note_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="📄 مشاهده جزوه", callback_data=f"note_view:{note_id}"),
        InlineKeyboardButton(text="👤 اطلاعات ثبت‌کننده", callback_data=f"submitter_info:{note_id}"),
    )
    return kb.as_markup()


def pending_notes_keyboard(notes: list, page: int, has_more: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for note in notes:
        label = note["title"][:35]
        submitter = note["submitted_by_name"] or "بدون نام"
        kb.row(
            InlineKeyboardButton(
                text=f"📄 {label} · {submitter[:16]}",
                callback_data=f"pending_note:{note['id']}:{page}",
            )
        )
    if page > 0 or has_more:
        controls = []
        if page > 0:
            controls.append(
                InlineKeyboardButton(
                    text="⬅️ قبلی", callback_data=f"admin_pending_page:{page - 1}"
                )
            )
        if has_more:
            controls.append(
                InlineKeyboardButton(
                    text="بعدی ➡️", callback_data=f"admin_pending_page:{page + 1}"
                )
            )
        kb.row(*controls)
    kb.row(InlineKeyboardButton(text="🔙 پنل مدیریت", callback_data="admin_main_back"))
    return kb.as_markup()


def pending_note_detail_keyboard(note_id: int, page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ تأیید", callback_data=f"approve:{note_id}"),
        InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{note_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="📎 مشاهده فایل", callback_data=f"note_download:{note_id}"),
        InlineKeyboardButton(
            text="👤 اطلاعات ثبت‌کننده", callback_data=f"submitter_info:{note_id}"
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text="🔙 فهرست درخواست‌ها", callback_data=f"admin_pending_page:{page}"
        )
    )
    return kb.as_markup()


# ─── Admin Management ────────────────────────────────────────────────────────

def admins_list_keyboard(admins: list) -> InlineKeyboardMarkup:
    """Keyboard listing admins (auto columns, short labels)."""
    items = []
    for admin in admins:
        status = "🟢" if admin["is_active"] else "🔴"
        main = "👑" if admin["is_main_admin"] else "👤"
        name = admin["full_name"] or admin["username"] or f"ID:{admin['user_id']}"
        items.append((f"{status}{main} {name[:14]}", f"admin_detail:{admin['id']}"))
    kb = auto_columns_keyboard(
        items,
        back=("➕ افزودن", "admin_add"),
    )
    # add owners shortcut + back row
    from aiogram.types import InlineKeyboardMarkup as _M
    rows = kb.inline_keyboard
    extra = [
        [InlineKeyboardButton(text="👑 Ownerها", callback_data="manage_owners"),
         InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows + extra)


def admin_detail_keyboard(admin_id: int, is_main: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for managing a specific admin (short, auto layout)."""
    items = []
    if not is_main:
        items.append(("🔑 رمز", f"admin_change_pass:{admin_id}"))
        items.append(("🔐 دسترسی‌ها", f"admin_perms:{admin_id}"))
        items.append(("🗑 حذف", f"admin_delete:{admin_id}"))
    kb = auto_columns_keyboard(items, back=("🔙 بازگشت", "admin_admins"))
    return kb


def permissions_keyboard(admin_id: int, current_perms: list) -> InlineKeyboardMarkup:
    """Keyboard for toggling admin permissions (auto 2-col layout)."""
    from permissions import PERMISSIONS as ALL_PERMS
    kb = InlineKeyboardBuilder()
    row = []
    for perm_key, perm_label in ALL_PERMS.items():
        check = "✅" if perm_key in current_perms else "⬜"
        row.append(InlineKeyboardButton(
            text=f"{check} {perm_label}",
            callback_data=f"perm_toggle:{admin_id}:{perm_key}",
        ))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"admin_detail:{admin_id}"),
    )
    return kb.as_markup()


# ─── User Management ─────────────────────────────────────────────────────────

def users_management_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for user management options."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="👥 کاربران مجاز", callback_data="allowed_users_list"),
    )
    kb.row(
        InlineKeyboardButton(text="➕ افزودن کاربر مجاز", callback_data="allowed_user_add"),
    )
    kb.row(
        InlineKeyboardButton(text="📊 سقف ثبت جزوه", callback_data="note_limit_menu"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"),
    )
    return kb.as_markup()


def allowed_user_keyboard(user_id: int, is_allowed: bool) -> InlineKeyboardMarkup:
    """Keyboard for managing an allowed user."""
    kb = InlineKeyboardBuilder()
    status = "🟢 فعال" if is_allowed else "🔴 غیرفعال"
    kb.row(
        InlineKeyboardButton(
            text=f"{status} تأیید خودکار",
            callback_data=f"allowed_toggle:{user_id}",
        ),
    )
    kb.row(
        InlineKeyboardButton(text="🗑 حذف", callback_data=f"allowed_remove:{user_id}"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="allowed_users_list"),
    )
    return kb.as_markup()


# ─── Confirmation ────────────────────────────────────────────────────────────

def confirm_keyboard(action: str, item_id: int) -> InlineKeyboardMarkup:
    """Generic confirmation keyboard."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ تأیید", callback_data=f"confirm:{action}:{item_id}"),
        InlineKeyboardButton(text="❌ انصراف", callback_data=f"cancel:{action}:{item_id}"),
    )
    return kb.as_markup()


# ─── Settings ─────────────────────────────────────────────────────────────────

def settings_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for admin settings."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🔎 جستجوی Inline", callback_data="setting_inline"),
        InlineKeyboardButton(text="📊 آمار ربات", callback_data="setting_stats"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"),
    )
    return kb.as_markup()


# ─── File Tools ───────────────────────────────────────────────────────────────

def file_tools_keyboard(back_to: str = "menu_tools") -> InlineKeyboardMarkup:
    """Menu for general file tools (images -> PDF etc).
    back_to controls where the back button goes so the user returns to
    the exact panel they came from (main menu, admin panel, PDF menu)."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🖼PDF تصویر به ", callback_data="tool_images_pdf"),
        InlineKeyboardButton(text="📄 Word → PDF", callback_data="tool_word_pdf"),
    )
    kb.row(
        InlineKeyboardButton(text="📝 PDF → Word", callback_data="tool_pdf_word"),
        InlineKeyboardButton(text="📑 فایل‌های ذخیره‌شده → PDF", callback_data="tool_saved_pdf"),
    )
    back_label = {
        "menu_main": "🔙 منوی اصلی",
        "admin_main_back": "🔙 بازگشت به پنل ادمین",
        "menu_make_pdf": "🔙 بازگشت به ساخت PDF",
    }.get(back_to, "🔙 بازگشت")
    kb.row(
        InlineKeyboardButton(text=back_label, callback_data=back_to),
    )
    return kb.as_markup()


def file_cancel_keyboard() -> InlineKeyboardMarkup:
    return cancel_keyboard("tools_cancel")


# ─── Weekly Schedule ────────────────────────────────────────────────────────

# 7 columns x 7 rows schedule grid. Row index 0 is the day itself (tap to
# see tasks for that day), remaining 6 rows show the subject names.

def schedule_view_keyboard(sched: dict, is_admin: bool = False) -> InlineKeyboardMarkup:
    """sched is a 7x8 list-of-lists: sched[day_index][col_index] (col 0 = day)."""
    kb = InlineKeyboardBuilder()
    for day_idx, row in enumerate(sched):
        buttons = [
            InlineKeyboardButton(
                text=row[0],
                callback_data=f"sched_day:{day_idx}",
            )
        ]
        for col in range(1, 8):
            buttons.append(
                InlineKeyboardButton(text=row[col], callback_data="noop")
            )
        kb.row(*buttons)
    if is_admin:
        kb.row(
            InlineKeyboardButton(text="✏️ ویرایش برنامه", callback_data="sched_edit_start"),
        )
    kb.row(
        InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu_main"),
    )
    return kb.as_markup()


def sched_day_keyboard(day_name: str, tasks: list, done_set: set, is_admin: bool) -> InlineKeyboardMarkup:
    """Show tasks of a single day; tasks are tap-toggleable per-user."""
    kb = InlineKeyboardBuilder()
    for idx, task in enumerate(tasks):
        check = "✅" if idx in done_set else "⬜"
        kb.row(
            InlineKeyboardButton(
                text=f"{check} {task}",
                callback_data=f"task_toggle:{idx}",
            )
        )
    if not tasks:
        kb.row(
            InlineKeyboardButton(text="— تکلیفی برای این روز نیست —", callback_data="noop"),
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت به برنامه", callback_data="menu_schedule"),
    )
    return kb.as_markup()


def sched_edit_field_keyboard(fields: list) -> InlineKeyboardMarkup:
    """Admin picking a study field to edit its weekly schedule."""
    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}",
                callback_data=f"sched_edit_field:{field['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_schedule"),
    )
    return kb.as_markup()


def sched_edit_menu_keyboard(field_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, day in enumerate(["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]):
        kb.row(
            InlineKeyboardButton(
                text=day,
                callback_data=f"sched_cell:{field_id}:{i}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_schedule"),
    )
    return kb.as_markup()


PERIOD_TIMES = ["۱۰-۱", "۱-۱", "۱-۳", "۳-۱", "۰-۳", "۵-۳", "۲۴-۵"]


def sched_periods_keyboard(field_id: int, cleared: bool = False) -> InlineKeyboardMarkup:
    """Show the 7 class periods as preset buttons for quick setup."""
    kb = InlineKeyboardBuilder()
    for idx, t in enumerate(PERIOD_TIMES, start=1):
        kb.row(
            InlineKeyboardButton(
                text=f"زنگ {idx} ({t})",
                callback_data=f"sched_period:{field_id}:{idx}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="✏️ ویرایش دستی", callback_data="sched_edit_start"),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_schedule"),
    )
    return kb.as_markup()


def admin_schedule_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➕ افزودن کلاس به برنامه هفتگی", callback_data="weekly_add"),
    )
    kb.row(
        InlineKeyboardButton(text="📋 مشاهده برنامه‌های ثبت‌شده", callback_data="weekly_view"),
    )
    kb.row(
        InlineKeyboardButton(text="✏️ ویرایش کلاس", callback_data="weekly_edit"),
    )
    kb.row(
        InlineKeyboardButton(text="🗑 حذف کلاس", callback_data="weekly_delete"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت به پنل مدیریت", callback_data="admin_main_back"),
    )
    return kb.as_markup()


# ─── Tasks (تکالیف) ──────────────────────────────────────────────────────

def admin_tasks_menu_keyboard() -> InlineKeyboardMarkup:
    """Admin homework management entry menu."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➕ ثبت موضوع / دسته‌بندی", callback_data="tasks_cat_add"),
    )
    kb.row(
        InlineKeyboardButton(text="📝 ثبت تکلیف", callback_data="tasks_task_add"),
    )
    kb.row(
        InlineKeyboardButton(text="📋 مشاهده تکالیف ثبت‌شده", callback_data="tasks_admin_list"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_main_back"),
    )
    return kb.as_markup()


def task_categories_keyboard(cats: list, action: str) -> InlineKeyboardMarkup:
    """List categories dynamically. action: 'pick' (for new task)
    or 'manage' (rename/delete)."""
    kb = InlineKeyboardBuilder()
    for cat in cats:
        kb.row(
            InlineKeyboardButton(
                text=f"📁 {cat['name']} ({cat['task_count']})",
                callback_data=f"tasks_cat_{action}:{cat['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_tasks"),
    )
    return kb.as_markup()


def task_category_detail_keyboard(cat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✏️ تغییر نام", callback_data=f"tasks_cat_rename:{cat_id}"),
        InlineKeyboardButton(text="🗑 حذف دسته‌بندی", callback_data=f"tasks_cat_delete:{cat_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="tasks_cats_manage"),
    )
    return kb.as_markup()


def task_detail_keyboard(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🗑 حذف تکلیف", callback_data=f"tasks_task_delete:{task_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="tasks_admin_list"),
    )
    return kb.as_markup()


def task_fields_keyboard(fields: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for field in fields:
        kb.row(
            InlineKeyboardButton(
                text=f"📚 {field['name']}", callback_data=f"tasks_field:{field['id']}"
            )
        )
    kb.row(InlineKeyboardButton(text="❌ لغو عملیات", callback_data="tasks_flow_cancel"))
    return kb.as_markup()


def task_subjects_keyboard(subjects: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.row(
            InlineKeyboardButton(
                text=f"📖 {subject['name']}",
                callback_data=f"tasks_subject:{subject['id']}",
            )
        )
    kb.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="tasks_task_add"),
        InlineKeyboardButton(text="❌ لغو", callback_data="tasks_flow_cancel"),
    )
    return kb.as_markup()


def task_days_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    days = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
    for index, day in enumerate(days):
        kb.row(
            InlineKeyboardButton(text=f"📅 {day}", callback_data=f"tasks_day:{index}")
        )
    kb.row(InlineKeyboardButton(text="❌ لغو عملیات", callback_data="tasks_flow_cancel"))
    return kb.as_markup()


def task_user_list_keyboard(tasks: list, page: int, has_more: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for task in tasks:
        title = task["title"][:45]
        kb.row(
            InlineKeyboardButton(
                text=f"📝 {title}",
                callback_data=f"task_view:{task['id']}:{page}",
            )
        )
    if page > 0 or has_more:
        controls = []
        if page > 0:
            controls.append(
                InlineKeyboardButton(
                    text="⬅️ قبلی", callback_data=f"menu_tasks_page:{page - 1}"
                )
            )
        if has_more:
            controls.append(
                InlineKeyboardButton(
                    text="بعدی ➡️", callback_data=f"menu_tasks_page:{page + 1}"
                )
            )
        kb.row(*controls)
    kb.row(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu_main"))
    return kb.as_markup()


def task_user_detail_keyboard(task_id: int, page: int, has_file: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_file:
        kb.row(
            InlineKeyboardButton(
                text="🖼 مشاهده تصویر تکلیف", callback_data=f"task_photo:{task_id}"
            )
        )
    kb.row(
        InlineKeyboardButton(
            text="🔙 فهرست تکالیف", callback_data=f"menu_tasks_page:{page}"
        )
    )
    return kb.as_markup()


def task_admin_list_keyboard(tasks: list, page: int, has_more: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for task in tasks:
        kb.row(
            InlineKeyboardButton(
                text=f"📝 {task['title'][:45]}",
                callback_data=f"tasks_admin_view:{task['id']}:{page}",
            )
        )
    if page > 0 or has_more:
        controls = []
        if page > 0:
            controls.append(
                InlineKeyboardButton(
                    text="⬅️ قبلی", callback_data=f"tasks_admin_page:{page - 1}"
                )
            )
        if has_more:
            controls.append(
                InlineKeyboardButton(
                    text="بعدی ➡️", callback_data=f"tasks_admin_page:{page + 1}"
                )
            )
        kb.row(*controls)
    kb.row(InlineKeyboardButton(text="🔙 مدیریت تکالیف", callback_data="admin_tasks"))
    return kb.as_markup()


def task_admin_detail_keyboard(task_id: int, page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🗑 حذف تکلیف", callback_data=f"tasks_task_delete:{task_id}")
    )
    kb.row(
        InlineKeyboardButton(
            text="🔙 فهرست تکالیف", callback_data=f"tasks_admin_page:{page}"
        )
    )
    return kb.as_markup()


def task_cancel_keyboard() -> InlineKeyboardMarkup:
    return cancel_keyboard("tasks_flow_cancel")
