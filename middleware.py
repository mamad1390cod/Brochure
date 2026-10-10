"""
Authentication & permission middleware for Bot-File-School.

Guards every handler registered on the admin router:
- Callback queries require an authenticated admin session (except the
  login button itself) and, for sensitive operations, a specific permission.
- FSM messages on the admin router require authentication, except the
  admin-login password step.
"""

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from typing import Any, Awaitable, Callable, Dict

import security
from permissions import check_permission, is_admin, CALLBACK_PERMISSIONS
from logger import logger

# Callback-data prefixes that are always allowed without authentication
EXEMPT_CALLBACKS = {"admin_login"}

# callback prefix -> required permission (from permissions.py - single source)
CALLBACK_PERMISSIONS = CALLBACK_PERMISSIONS

# FSM state group prefix -> required permission (AdminLogin is exempt)
STATE_PERMISSIONS = {
    "FieldAddFlow": "add_field",
    "FieldEditFlow": "add_field",
    "SubjectAddFlow": "add_subject",
    "SubjectEditFlow": "add_subject",
    "ChapterAddFlow": "add_chapter",
    "ChapterEditFlow": "add_chapter",
    "NoteEditFlow": "edit_note",
    "AdminAddFlow": "add_admin",
    "PasswordChangeFlow": "manage_admins",
    "AllowedUserAddFlow": "manage_users",
    "OnlineClassFlow": "manage_classes",
    "SchedEditFlow": "manage_schedule",
    "AdminConvertFlow": "convert_files",
    "TaskCatAddFlow": "manage_tasks",
    "TaskCatRenameFlow": "manage_tasks",
    "TaskAddFlow": "manage_tasks",
    "NoteLimitFlow": "manage_users",
    "ClassEditFlow": "manage_classes",
    "ChapterSearchFlow": "manage_fields",
    "WeeklyClassFlow": "manage_schedule",
}


class AdminAuthMiddleware(BaseMiddleware):
    """Require an authenticated admin session and granular permissions.

    guard_all=True  - every callback on the router belongs to the admin panel
                      (the admin router).
    guard_all=False - MIXED router: only callbacks/state flows that are listed
                      in CALLBACK_PERMISSIONS / STATE_PERMISSIONS are guarded,
                      everything else keeps working for regular users. Use this
                      on routers that serve both users and admins (e.g. the
                      tasks router), otherwise admin handlers on that router
                      would be reachable without any admin session.
    """

    def __init__(self, guard_all: bool = True) -> None:
        self.guard_all = guard_all

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return None

        user_id = user.id
        authenticated = security.admin_sessions.is_authenticated(user_id)
        if authenticated and not await is_admin(user_id):
            security.admin_sessions.logout(user_id)
            authenticated = False

        if isinstance(event, CallbackQuery):
            callback_base = (event.data or "").split(":")[0]

            if callback_base in EXEMPT_CALLBACKS:
                return await handler(event, data)

            if not self.guard_all and callback_base not in CALLBACK_PERMISSIONS:
                return await handler(event, data)  # not an admin feature

            if authenticated:
                # Sliding refresh - active admins keep their session alive
                security.admin_sessions.refresh(user_id)

            if not authenticated:
                await event.answer(
                    "🔒 ابتدا وارد پنل مدیریت شوید؛ این بخش فقط برای ادمین معتبر است.",
                    show_alert=True,
                )
                return None

            permission = CALLBACK_PERMISSIONS.get(callback_base)
            if permission and not await check_permission(user_id, permission):
                await event.answer(
                    "❌ دسترسی شما به این بخش توسط Owner حذف/تغییر کرده است.",
                    show_alert=True,
                )
                logger.warning(
                    f"Permission denied: user {user_id} tried '{event.data}' "
                    f"(needs '{permission}')"
                )
                return None

            return await handler(event, data)

        if isinstance(event, Message):
            state = data.get("state")
            state_str = await state.get_state() if state else None

            # Password entry step must remain reachable before authentication
            if state_str and state_str.startswith("AdminLogin:"):
                return await handler(event, data)

            flow = state_str.split(":")[0] if state_str else None

            if not self.guard_all and (flow is None or flow not in STATE_PERMISSIONS):
                return await handler(event, data)  # not an admin flow

            if not authenticated:
                return None  # Silently ignore stray messages

            if state_str:
                permission = STATE_PERMISSIONS.get(flow)
                if permission and not await check_permission(user_id, permission):
                    await event.answer("❌ شما دسترسی لازم برای این عملیات را ندارید.")
                    logger.warning(
                        f"Permission denied: user {user_id} in state '{state_str}' "
                        f"(needs '{permission}')"
                    )
                    return None

            return await handler(event, data)

        return await handler(event, data)


# Callback bases that CONTINUE an FSM flow and must NOT clear the state.
# Everything else (opening another menu, viewing a note, ...) cancels any
# half-finished input flow so a stray text is never consumed by the old flow.
KEEP_STATE_CALLBACKS = {
    # submit-note flow (user picks field/subject/chapter via callbacks)
    "submit_note_start", "submit_field", "submit_subject", "submit_chapter",
    "submit_no_chapter", "submit_back_subject", "submit_cancel",
    # file tools are collected via messages and cancelled via callbacks
    "tools_cancel",
    # Homework creation requires multiple inline selections between inputs.
    "tasks_field", "tasks_subject", "tasks_day",
    # Weekly timetable creation/edit selection and confirmation.
    "weekly_add_track", "weekly_add_day", "weekly_edit_choose_track",
    "weekly_edit_choose_day", "weekly_add_confirm", "weekly_edit_confirm",
    "weekly_correct",
}


class StateCleanupMiddleware(BaseMiddleware):
    """Cancel any half-finished FSM flow when the user taps a button that
    belongs to a different section. Prevents the classic bug where text sent
    for a new action is swallowed by the previous input flow."""

    async def __call__(self, handler, event, data):
        state = data.get("state")
        state_str = await state.get_state() if state is not None else None
        if state_str:
            callback_base = (getattr(event, "data", "") or "").split(":")[0]
            if callback_base not in KEEP_STATE_CALLBACKS:
                if state_str.startswith("FileToolsFlow:"):
                    from filetools import cleanup_filetools_state
                    await cleanup_filetools_state(state)
                await state.clear()
        return await handler(event, data)


class UsageMiddleware(BaseMiddleware):
    """Count feature usage per user (for the Top-5 active users stat).
    Register on user-facing routers only (never the admin router)."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not user.is_bot:
            try:
                import models as _models
                await _models.bump_usage(
                    user.id, user.username or "", user.full_name or "")
            except Exception as e:  # stats must never break the bot
                logger.warning(f"Usage tracking failed: {e}")
        return await handler(event, data)
