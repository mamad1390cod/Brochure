"""
Permission system for Bot-File-School.
Role + Permission design:
  - Owner  : full access (main admin from config + is_owner admins in DB)
  - Admin  : only the permissions the owner enabled for them

Permissions are read LIVE from the database on every check (no cache) so
permission changes apply immediately without restart or re-login.
"""

from models import admin_has_permission, get_admin_by_user_id, get_all_admins

# ─── Permission Constants (extensible - add new ones here) ───────────────────

PERMISSIONS = {
    "view_panel": "👁 پنل",
    "view_notes": "📄 مشاهده جزوه‌ها",
    "add_note": "➕ افزودن جزوه",
    "delete_note": "🗑 حذف جزوه",
    "edit_note": "✏️ ویرایش جزوه",
    "add_field": "➕ رشته",
    "delete_field": "🗑 حذف رشته",
    "add_subject": "➕ درس",
    "delete_subject": "🗑 حذف درس",
    "add_chapter": "➕ فصل",
    "delete_chapter": "🗑 حذف فصل",
    "manage_users": "👥 کاربران",
    "manage_admins": "👤 ادمین‌ها",
    "manage_settings": "⚙️ تنظیمات",
    "manage_schedule": "📅 برنامه",
    "manage_tasks": "📚 تکالیف",
    "manage_classes": "🟢 کلاس‌ها",
    "manage_files": "📁 فایل‌ها",
    "manage_fields": "📚 ساختار درسی",
    "convert_files": "🛠 تبدیل فایل",
    "view_logs": "📋 لاگ‌ها",
    "export_logs": "📤 خروجی لاگ‌ها",
    "view_stats": "📊 آمار",
    "add_admin": "➕ افزودن ادمین",
    "delete_admin": "🗑 حذف ادمین",
    "manage_owners": "👑 Ownerها",
}

# Default permissions for new regular admins
DEFAULT_ADMIN_PERMISSIONS = [
    "view_panel",
    "view_notes",
    "add_note",
    "edit_note",
]

# Mapping of panel buttons (callback base) to the permission they require.
# Used by middleware to enforce backend checks on every callback.
CALLBACK_PERMISSIONS = {
    "admin_users": "manage_users",
    "allowed_users_list": "manage_users",
    "allowed_user_add": "manage_users",
    "allowed_detail": "manage_users",
    "allowed_toggle": "manage_users",
    "allowed_remove": "manage_users",
    "admin_admins": "manage_admins",
    "admin_add": "add_admin",
    "admin_detail": "manage_admins",
    "admin_change_pass": "manage_admins",
    "admin_perms": "manage_admins",
    "perm_toggle": "manage_admins",
    "admin_delete": "delete_admin",
    "admin_owner_add": "manage_owners",
    "owner_demote": "manage_owners",
    "manage_owners": "manage_owners",
    "admin_logs": "view_logs",
    "logs_pdf": "export_logs",
    "admin_stats": "view_stats",
    "stats_pdf": "view_stats",
    "note_limit_menu": "manage_users",
    "note_limit_set": "manage_users",
    "note_limit_custom": "manage_users",
    "class_edit": "manage_classes",
    "cls_set": "manage_classes",
    "cls_set_day": "manage_classes",
    "class_notify_toggle": "manage_classes",
    "class_notify_global": "manage_classes",
    "goodnight_menu": "manage_classes",
    "goodnight_toggle": "manage_classes",
    "goodnight_time_set": "manage_classes",
    "goodnight_text_set": "manage_classes",
    "all_text_set": "manage_classes",
    "tz_menu": "manage_settings",
    "tz_set": "manage_settings",
    "tz_custom": "manage_settings",
    "admin_settings": "manage_settings",
    "setting_stats": "manage_settings",
    "setting_inline": "manage_settings",
    "field_add": "add_field",
    "field_edit": "add_field",
    "field_delete": "delete_field",
    "field_toggle_delete": "delete_field",
    "field_delete_all": "delete_field",
    "field_confirm_bulk_delete": "delete_field",
    "subject_add": "add_subject",
    "subject_edit": "add_subject",
    "subject_delete": "delete_subject",
    "chapter_add": "add_chapter",
    "chapter_edit": "add_chapter",
    "chapter_delete": "delete_chapter",
    "note_edit": "edit_note",
    "note_delete": "delete_note",
    "admin_fields": "manage_fields",
    "admin_fields_back": "manage_fields",
    "field_view": "manage_fields",
    "field_subjects": "manage_fields",
    "field_bulk_delete": "delete_field",
    "admin_subjects": "manage_fields",
    "subject_view": "manage_fields",
    "subject_chapters": "manage_fields",
    "subject_chapters_back": "manage_fields",
    "admin_chapters": "manage_fields",
    "admin_chapters_field": "manage_fields",
    "chapter_view": "manage_fields",
    "chapter_notes": "manage_fields",
    "chapter_search": "manage_fields",
    "admin_notes": "view_notes",
    "admin_pending": "view_notes",
    "admin_pending_page": "view_notes",
    "pending_note": "view_notes",
    "note_view": "view_notes",
    "note_back": "view_notes",
    "note_download": "view_notes",
    "notes_page": "view_notes",
    "subject_notes": "view_notes",
    "submitter_info": "view_notes",
    "approve": "add_note",
    "reject": "delete_note",
    "admin_convert_start": "convert_files",
    "admin_convert_done": "convert_files",
    "admin_schedule": "manage_schedule",
    "admin_schedule_view": "manage_schedule",
    "sched_edit_start": "manage_schedule",
    "sched_cell": "manage_schedule",
    "sched_edit_cell": "manage_schedule",
    "sched_clear": "manage_schedule",
    "sched_reset_tasks": "manage_schedule",
    "weekly_add": "manage_schedule",
    "weekly_add_track": "manage_schedule",
    "weekly_add_day": "manage_schedule",
    "weekly_add_confirm": "manage_schedule",
    "weekly_view": "manage_schedule",
    "weekly_view_track": "manage_schedule",
    "weekly_view_day": "manage_schedule",
    "weekly_view_page": "manage_schedule",
    "weekly_view_item": "manage_schedule",
    "weekly_edit": "manage_schedule",
    "weekly_edit_track": "manage_schedule",
    "weekly_edit_day": "manage_schedule",
    "weekly_edit_list": "manage_schedule",
    "weekly_edit_class": "manage_schedule",
    "weekly_edit_choose_track": "manage_schedule",
    "weekly_edit_choose_day": "manage_schedule",
    "weekly_edit_confirm": "manage_schedule",
    "weekly_correct": "manage_schedule",
    "weekly_delete": "manage_schedule",
    "weekly_delete_track": "manage_schedule",
    "weekly_delete_day": "manage_schedule",
    "weekly_delete_list": "manage_schedule",
    "weekly_delete_class": "manage_schedule",
    "weekly_delete_confirm": "manage_schedule",
    "weekly_delete_cancel": "manage_schedule",
    "weekly_cancel": "manage_schedule",
    "admin_classes": "manage_classes",
    "classes_day": "manage_classes",
    "class_add": "manage_classes",
    "class_del": "manage_classes",
    "admin_tasks": "manage_tasks",
    "tasks_cat_add": "manage_tasks",
    "tasks_cat_manage": "manage_tasks",
    "tasks_cats_manage": "manage_tasks",
    "tasks_cat_pick": "manage_tasks",
    "tasks_cat_rename": "manage_tasks",
    "tasks_cat_delete": "manage_tasks",
    "tasks_task_add": "manage_tasks",
    "tasks_field": "manage_tasks",
    "tasks_subject": "manage_tasks",
    "tasks_day": "manage_tasks",
    "tasks_task_delete": "manage_tasks",
    "tasks_admin_list": "manage_tasks",
    "tasks_admin_view": "manage_tasks",
    "tasks_admin_page": "manage_tasks",
    "tasks_flow_cancel": "manage_tasks",
}


async def is_owner(user_id: int) -> bool:
    """Owner = MAIN_ADMIN_ID (config) or an admin flagged is_owner in DB."""
    from config import MAIN_ADMIN_ID
    if user_id == MAIN_ADMIN_ID:
        return True
    admin = await get_admin_by_user_id(user_id)
    return admin is not None and bool(admin["is_main_admin"])


async def check_permission(user_id: int, permission: str) -> bool:
    """Check LIVE from the database (no cache) - permission changes are
    effective immediately for logged-in admins."""
    if await is_owner(user_id):
        return True

    admin = await get_admin_by_user_id(user_id)
    if not admin:
        return False

    return await admin_has_permission(admin["id"], permission)


async def is_admin(user_id: int) -> bool:
    from config import MAIN_ADMIN_ID
    if user_id == MAIN_ADMIN_ID:
        return True
    admin = await get_admin_by_user_id(user_id)
    return admin is not None


async def is_main_admin(user_id: int) -> bool:
    return await is_owner(user_id)


async def get_owner_ids() -> list[int]:
    """All owner user IDs (config main + DB owners)."""
    ids = []
    from config import MAIN_ADMIN_ID
    ids.append(MAIN_ADMIN_ID)
    for a in await get_all_admins():
        if a["is_main_admin"] and a["user_id"] != MAIN_ADMIN_ID:
            ids.append(a["user_id"])
    return ids
