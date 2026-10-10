"""
Layer 2: every button / callback, authentication, permissions, dead buttons.

Seeds a realistic database, logs in as Owner and as a limited admin, then
clicks every button the keyboards can produce. A button that matches no
handler leaves the update UNHANDLED - that is how "looks clickable but does
nothing" buttons are detected.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import re

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

import models
import security
from conftest import OWNER_ID, make_chat, make_user
from permissions import CALLBACK_PERMISSIONS, DEFAULT_ADMIN_PERMISSIONS, PERMISSIONS

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ─── static inventory helpers (source-level, independent of the test DB) ────

_CB = re.compile(r'callback_data\s*=\s*(f?)"([^"]*)"')
_EQ = re.compile(r'F\.data\s*==\s*"([^"]+)"')
_SW = re.compile(r'F\.data\.startswith\("([^"]+)"\)')
_STATE_FILTER = re.compile(r'StateFilter\((\w+)\.')

# Keyboard builders that are never referenced by any handler. They are dead
# code, not dead buttons - keep the list explicit so a NEW unrouted button
# (a button the user can actually see but nothing handles) fails this suite.
UNREACHABLE_KEYBOARD_BUILDERS = {
    "sched_edit_field",   # sched_edit_field_keyboard(), never used
    "sched_period",       # sched_periods_keyboard(), never used
}

# Template whose {action} is substituted before the button is built:
# tasks_cat_{action}:<id> becomes tasks_cat_pick:<id> / tasks_cat_manage:<id>.
DYNAMIC_TEMPLATES = {"tasks_cat_", "weekly_"}


def _source_files():
    return sorted(ROOT.glob("*.py"))


def produced_callbacks() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in _source_files():
        for _is_f, raw in _CB.findall(path.read_text(encoding="utf-8")):
            base = raw.split("{")[0].rstrip(":").split(":")[0]
            if not base:
                continue
            out.setdefault(base, set()).add(path.name)
    return out


def handler_prefixes() -> set[str]:
    prefixes: set[str] = set()
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        prefixes.update(a.rstrip(":").split(":")[0] for a in _EQ.findall(text))
        prefixes.update(a.rstrip(":").split(":")[0] for a in _SW.findall(text))
    return prefixes

USER_ID = 700001
LIMITED_ADMIN_ID = 700002
OTHER_ADMIN_ID = 700003


class World:
    """Seeded database plus the ids the buttons need."""

    def __init__(self, ids: dict):
        self.__dict__.update(ids)


async def seed(app) -> World:
    field = await models.create_field("ریاضی")
    subject = await models.create_subject(field, "هندسه")
    chapter = await models.create_chapter(subject, "فصل ۱")
    note = await models.create_note(
        title="جزوه هندسه",
        description="توضیح",
        field_id=field,
        subject_id=subject,
        chapter_id=chapter,
        page_start=1,
        page_end=3,
        file_type="document",
        file_id="FILE",
        file_unique_id="UNIQ",
        file_name="g.pdf",
        mime_type="application/pdf",
        file_size=2048,
        submitted_by=USER_ID,
        submitted_by_name="Test User",
        status="approved",
    )
    pending = await models.create_note(
        title="جزوه در انتظار",
        description="",
        field_id=field,
        subject_id=subject,
        chapter_id=chapter,
        page_start=None,
        page_end=None,
        file_type="photo",
        file_id="PHOTO",
        file_unique_id="UNIQ2",
        file_name="p.jpg",
        mime_type="image/jpeg",
        file_size=100,
        submitted_by=USER_ID,
        submitted_by_name="Test User",
        status="pending",
    )
    limited_db_id = await models.create_admin(
        LIMITED_ADMIN_ID, "limited", "Limited Admin", security.hash_password("limited-pw")
    )
    await models.set_admin_permissions(limited_db_id, DEFAULT_ADMIN_PERMISSIONS)
    other_db_id = await models.create_admin(
        OTHER_ADMIN_ID, "other", "Other Admin", security.hash_password("other-pw")
    )
    await models.set_admin_permissions(other_db_id, list(PERMISSIONS.keys()))

    await models.add_allowed_user(USER_ID, "u", "Allowed User", added_by=OWNER_ID)
    await models.add_online_class_full(
        0, "ریاضی", "16:00 تا 18:00", "https://meet.test", start_hour=16, end_hour=18
    )
    cat = await models.create_task_category("ریاضی")
    await models.create_task(cat, "صفحه ۲۲", "حل تمرین", created_by=OWNER_ID)
    await models.touch_group_activity(-100500, "Test Group")
    await models.upsert_group_member(-100500, USER_ID, "u", "Allowed User")

    return World(
        {
            "field": field,
            "subject": subject,
            "chapter": chapter,
            "note": note,
            "pending": pending,
            "cat": cat,
            "limited_db_id": limited_db_id,
            "other_db_id": other_db_id,
            "class_id": (await models.get_online_classes(0))[0]["id"],
        }
    )


async def login_owner(app, chat, owner):
    await app.click(chat, owner, "admin_login")


async def login_admin(app, chat, user, password):
    await app.click(chat, user, "admin_login")
    await app.send(chat, user, password)


# ─── user-facing buttons ─────────────────────────────────────────────────────


async def test_every_user_button_is_handled(app, private_chat, group_chat):
    w = await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    chat = private_chat
    buttons = [
        "menu_main",
        "menu_fields",
        f"user_field:{w.field}",
        f"user_subject:{w.subject}",
        f"user_chapter:{w.chapter}",
        f"user_chapter_search:{w.chapter}",
        f"user_note:{w.note}",
        f"user_download:{w.note}",
        f"user_field_back:{w.field}",
        "menu_search",
        "menu_tools",
        "menu_make_pdf",
        "menu_tasks",
        "menu_schedule",
        "noop",
    ]
    for data in buttons:
        app.clear()
        result = await app.click(chat, user, data)
        assert result is not UNHANDLED, f"DEAD BUTTON (no handler): {data}"

    # user routers must also accept a plain /start
    from conftest import make_message, message_update

    await app.feed(message_update(make_message(chat, user, "/start")))
    assert "منوی اصلی" in app.all_text() or "خوش آمدید" in app.all_text()


async def test_start_database_failure_is_logged_and_user_gets_recovery_message(
    app, private_chat, monkeypatch, caplog
):
    import handlers

    async def fail_upsert(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(handlers.models, "upsert_user", fail_upsert)
    user = make_user(USER_ID, "u", "Ali")

    await app.send(private_chat, user, "/start")

    assert "موقتاً با خطا" in app.all_text()
    assert "Could not process /start" in caplog.text
    assert "simulated database failure" in caplog.text


async def test_download_sends_the_file(app, private_chat):
    w = await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    await app.click(private_chat, user, f"user_download:{w.note}")
    assert app.session.last("SendDocument") is not None
    # pending note must NOT be downloadable by a regular user
    app.clear()
    await app.click(private_chat, user, f"user_download:{w.pending}")
    assert app.session.last("SendDocument") is None
    assert "فایل یافت نشد" in app.all_text() + str(app.session.calls[-1])


async def test_pending_note_not_visible_to_users(app, private_chat):
    w = await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    app.clear()
    await app.click(private_chat, user, f"user_note:{w.pending}")
    assert "جزوه یافت نشد" in app.all_text()


async def test_user_note_view_shows_details(app, private_chat):
    w = await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    await app.click(private_chat, user, f"user_note:{w.note}")
    text = app.all_text()
    assert "جزوه هندسه" in text and "هندسه" in text and "تأیید شده" in text


async def test_unknown_ids_are_rejected_gracefully(app, private_chat):
    await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    for data in [
        "user_field:999999",
        "user_subject:999999",
        "user_chapter:999999",
        "user_note:999999",
        "user_download:999999",
    ]:
        app.clear()
        await app.click(private_chat, user, data)  # must not raise
        assert "یافت نشد" in app.all_text(), data

    # a stale "back" button falls back to the fields list instead of an alert
    app.clear()
    await app.click(private_chat, user, "user_field_back:999999")
    assert "رشته" in app.all_text()


async def test_malformed_callback_data_does_not_corrupt_state(app, private_chat):
    """Non-numeric callback ids are done in dozens of handlers with int().

    Telegram only ever replays callback_data of buttons the bot itself sent,
    so an empty/非-numeric id is not reachable from a client; what matters is
    that such a payload never writes anything. This documents the behaviour
    instead of pretending it is a clean 404.
    """
    w = await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    for data in ["user_field:abc", "user_field:", "user_note:", "user_chapter:x"]:
        app.clear()
        try:
            await app.click(private_chat, user, data)
        except (ValueError, IndexError) as e:
            assert await models.get_approved_notes() != []  # data untouched
        else:
            assert "یافت نشد" in app.all_text() or "رشته" in app.all_text()
    assert (await models.get_note_by_id(w.note))["is_active"] == 1


# ─── schedule / task buttons ─────────────────────────────────────────────────


async def test_schedule_flow_buttons(app, private_chat):
    await seed(app)
    await models.set_schedule_cell(None, 0, 1, "ریاضی")
    await models.set_schedule_cell(None, 0, 2, "فیزیک")
    user = make_user(USER_ID, "u", "Ali")
    for data in ["menu_schedule", "sched_day:0", "task_done:0:1", "task_done:0:2"]:
        app.clear()
        result = await app.click(private_chat, user, data)
        assert result is not UNHANDLED, f"DEAD BUTTON: {data}"
    wk = models.current_week_key()
    assert await models.get_task_done(USER_ID, "sched:0:1", wk)
    # the day view must be re-rendered after the toggle (not just saved)
    assert "📋 <b>تکالیف امروز:</b>" in app.all_text()
    assert "✅" in app.all_text()
    # toggling twice returns to "not done"
    app.clear()
    await app.click(private_chat, user, "task_done:0:1")
    assert not await models.get_task_done(USER_ID, "sched:0:1", wk)
    assert "↩️" not in app.all_text()


async def test_schedule_in_group_is_handed_off_to_private(app, group_chat):
    await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    await app.click(group_chat, user, "menu_schedule")
    text = app.all_text()
    assert "حریم خصوصی" in text


async def test_sparse_schedule_keeps_period_identity(app, private_chat):
    await seed(app)
    await models.set_schedule_cell(None, 0, 1, "ریاضی")
    await models.set_schedule_cell(None, 0, 3, "فیزیک")
    user = make_user(USER_ID, "u", "Ali")
    await app.click(private_chat, user, "menu_schedule")
    await app.click(private_chat, user, "sched_day:0")
    assert "task_done:0:1" in app.session.callbacks()
    assert "task_done:0:3" in app.session.callbacks()
    assert "task_done:0:2" not in app.session.callbacks()

    app.clear()
    await app.click(private_chat, user, "task_done:0:3")
    week = models.current_week_key()
    assert await models.get_task_done(USER_ID, "sched:0:3", week)
    assert await models.get_day_done_status(USER_ID, 0, week) == (1, 2)
    assert "1/2 انجام شده" in app.all_text()


# ─── admin login / logout / rate limiting ────────────────────────────────────


async def test_owner_auto_login_and_logout(app, private_chat, owner):
    await login_owner(app, private_chat, owner)
    assert "Owner" in app.all_text()
    # a second /start while authenticated skips the login form
    app.clear()
    await app.click(private_chat, owner, "admin_login")
    assert "پنل مدیریت" in app.all_text()
    await app.click(private_chat, owner, "admin_logout")
    assert "خارج شدید" in app.all_text()


async def test_repeated_admin_login_ignores_only_unchanged_message_error(
    app, private_chat, owner, monkeypatch
):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageText

    original_make_request = app.session.make_request
    edited_messages = set()

    async def telegram_rejects_unchanged_edit(bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            signature = (
                method.chat_id,
                method.message_id,
                method.text,
                repr(method.reply_markup),
            )
            if signature in edited_messages:
                raise TelegramBadRequest(
                    method=method,
                    message=(
                        "Bad Request: message is not modified: specified new "
                        "message content and reply markup are exactly the same"
                    ),
                )
            edited_messages.add(signature)
        return await original_make_request(bot, method, timeout)

    monkeypatch.setattr(app.session, "make_request", telegram_rejects_unchanged_edit)

    await app.send(private_chat, owner, "/start")
    source = app.session.message_for_button(private_chat.id, "admin_login")
    assert source is not None
    security.admin_sessions.login(owner.id)
    await app.click(private_chat, owner, "admin_login", message=source)
    await app.click(private_chat, owner, "admin_login", message=source)

    assert len(edited_messages) == 1
    assert "پنل مدیریت" in app.all_text()


async def test_admin_login_reraises_unrelated_telegram_bad_request(
    app, private_chat, owner, monkeypatch
):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageText

    original_make_request = app.session.make_request

    async def telegram_rejects_edit(bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            raise TelegramBadRequest(method=method, message="Bad Request: message is too old")
        return await original_make_request(bot, method, timeout)

    monkeypatch.setattr(app.session, "make_request", telegram_rejects_edit)

    security.admin_sessions.login(owner.id)
    with pytest.raises(TelegramBadRequest, match="message is too old"):
        await app.click(private_chat, owner, "admin_login")


async def test_concurrent_owner_logins_create_one_admin_row(app):
    owner = make_user(OWNER_ID, "owner", "Owner")
    chats = [make_chat(920000 + i, "private") for i in range(5)]
    await asyncio.gather(
        *(app.click(chat, owner, "admin_login") for chat in chats)
    )
    assert len(await models.get_all_admins()) == 1


async def test_admin_password_login(app, private_chat):
    await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, private_chat, admin, "limited-pw")
    assert "خوش آمدید" in app.all_text()
    assert security.admin_sessions.is_authenticated(LIMITED_ADMIN_ID)


async def test_legacy_admin_password_hash_upgrades_on_login(app, private_chat):
    salt = "old-salt"
    digest = hashlib.sha256(
        f"{salt}{'legacy-pw'}".encode("utf-8")
    ).hexdigest()
    db_id = await models.create_admin(
        LIMITED_ADMIN_ID, "limited", "Limited Admin", f"{salt}${digest}")
    await models.set_admin_permissions(db_id, DEFAULT_ADMIN_PERMISSIONS)

    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, private_chat, admin, "legacy-pw")

    stored = (await models.get_admin_by_user_id(LIMITED_ADMIN_ID))["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")
    assert security.verify_password("legacy-pw", stored)


async def test_admin_login_wrong_password_never_authenticates(app, private_chat):
    await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await app.click(private_chat, admin, "admin_login")
    await app.send(private_chat, admin, "wrong-pw")
    assert not security.admin_sessions.is_authenticated(LIMITED_ADMIN_ID)
    assert "رمز اشتباه" in app.all_text()
    assert "تلاش باقی" in app.all_text()


async def test_successful_login_deletes_the_password_message(app, private_chat):
    await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, private_chat, admin, "limited-pw")
    # the password must not stay in the chat history
    assert app.session.last("DeleteMessage") is not None


async def test_admin_login_rate_limit_locks_out(app, private_chat):
    await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await app.click(private_chat, admin, "admin_login")
    for _ in range(5):
        await app.send(private_chat, admin, "nope")
    assert security.rate_limiter.is_locked(LIMITED_ADMIN_ID)
    app.clear()
    await app.click(private_chat, admin, "admin_login")
    assert "قفل" in app.all_text()


async def test_non_admin_cannot_get_into_the_panel(app, private_chat):
    await seed(app)
    user = make_user(USER_ID, "u", "Ali")
    app.clear()
    await app.click(private_chat, user, "admin_login")
    # the login button only asks for a password; no session is created
    assert not security.admin_sessions.is_authenticated(USER_ID)
    await app.send(private_chat, user, "anything")
    assert not security.admin_sessions.is_authenticated(USER_ID)


# ─── admin panel: every button, as Owner ─────────────────────────────────────


async def test_every_admin_button_is_handled_as_owner(app, private_chat, owner):
    w = await seed(app)
    await login_owner(app, private_chat, owner)

    buttons = [
        "admin_main_back",
        "admin_fields",
        f"field_view:{w.field}",
        "field_add",
        f"field_edit:{w.field}",
        "field_bulk_delete",
        f"field_toggle_delete:{w.field}",
        "field_confirm_bulk_delete",
        f"field_subjects:{w.field}",
        f"subject_add:{w.field}",
        f"subject_view:{w.subject}",
        f"subject_edit:{w.subject}",
        f"subject_chapters:{w.subject}",
        f"subject_notes:{w.subject}",
        f"chapter_add:{w.subject}",
        f"chapter_view:{w.chapter}",
        f"chapter_edit:{w.chapter}",
        f"chapter_notes:{w.chapter}",
        f"chapter_search:{w.chapter}",
        f"note_view:{w.note}",
        f"note_download:{w.note}",
        f"note_edit:{w.note}",
        f"submitter_info:{w.note}",
        f"note_back:admin",
        "notes_page:0",
        "notes_page:1",
        "admin_pending",
        "admin_notes",
        "admin_admins",
        "admin_add",
        f"admin_detail:{w.other_db_id}",
        f"admin_change_pass:{w.other_db_id}",
        f"admin_perms:{w.other_db_id}",
        f"perm_toggle:{w.other_db_id}:view_panel",
        "manage_owners",
        "admin_owner_add",
        "admin_users",
        "allowed_users_list",
        f"allowed_detail:{USER_ID}",
        f"allowed_toggle:{USER_ID}",
        "allowed_user_add",
        "note_limit_menu",
        "note_limit_set:5",
        "note_limit_set:free",
        "note_limit_custom",
        "admin_logs",
        "admin_settings",
        "setting_inline",
        "setting_stats",
        "admin_schedule",
        "sched_edit_start",
        f"sched_cell:None:0",
        "admin_classes",
        "classes_day:0",
        f"class_edit:{w.class_id}",
        f"class_notify_toggle:{w.class_id}",
        f"cls_set:{w.class_id}:day",
        f"cls_set_day:{w.class_id}:1",
        "class_notify_global",
        "goodnight_menu",
        "goodnight_toggle",
        "goodnight_time_set",
        "goodnight_text_set",
        "all_text_set",
        "tz_menu",
        "tz_set:Asia/Tehran",
        "tz_custom",
        "admin_tasks",
        "tasks_cat_add",
        "tasks_cats_manage",
        f"tasks_cat_manage:{w.cat}",
        "tasks_task_add",
        f"tasks_cat_pick:{w.cat}",
        "tasks_admin_list",
        "admin_convert_start",
        "admin_stats",
        f"cancel:x:1",
        f"confirm:x:1",
        "noop",
    ]
    dead = []
    for data in buttons:
        app.clear()
        try:
            result = await app.click(private_chat, owner, data)
        except Exception as e:  # noqa: BLE001
            dead.append(f"{data} -> RAISED {type(e).__name__}: {e}")
            continue
        if result is UNHANDLED:
            dead.append(f"{data} -> UNHANDLED (no handler)")
    assert not dead, "broken admin buttons:\n" + "\n".join(dead)


async def test_admin_pending_list_renders(app, private_chat, owner):
    w = await seed(app)
    await login_owner(app, private_chat, owner)
    app.clear()
    await app.click(private_chat, owner, "admin_pending")
    text = app.all_text()
    assert "در انتظار تأیید" in text
    assert "جزوه در انتظار" in text
    assert f"pending_note:{w.pending}:0" in app.session.callbacks()

    await app.click(private_chat, owner, f"pending_note:{w.pending}:0")
    detail = app.all_text()
    assert "اطلاعات" in detail or "Test User" in detail
    assert f"approve:{w.pending}" in app.session.callbacks()
    assert f"reject:{w.pending}" in app.session.callbacks()
    assert f"note_download:{w.pending}" in app.session.callbacks()


async def test_admin_schedule_view_renders(app, private_chat, owner):
    await seed(app)
    await login_owner(app, private_chat, owner)
    app.clear()
    await app.click(private_chat, owner, "admin_schedule")
    assert "مدیریت برنامه هفتگی کلاس" in app.all_text()
    assert all(
        callback in app.session.callbacks()
        for callback in ("weekly_add", "weekly_view", "weekly_edit", "weekly_delete")
    )
    assert "admin_classes" not in app.session.callbacks()


async def test_repeated_schedule_edit_ignores_only_unchanged_message_error(
    app, private_chat, owner, monkeypatch
):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageText

    original_make_request = app.session.make_request
    edited_messages = set()

    async def telegram_rejects_unchanged_edit(bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            signature = (
                method.chat_id,
                method.message_id,
                method.text,
                repr(method.reply_markup),
            )
            if signature in edited_messages:
                raise TelegramBadRequest(
                    method=method,
                    message="Bad Request: message is not modified",
                )
            edited_messages.add(signature)
        return await original_make_request(bot, method, timeout)

    monkeypatch.setattr(app.session, "make_request", telegram_rejects_unchanged_edit)

    await login_owner(app, private_chat, owner)
    await app.click(private_chat, owner, "menu_schedule")
    await app.click(private_chat, owner, "admin_schedule_view")
    assert "برنامه هفتگی کلاس" in app.last_text()


async def test_repeated_schedule_clear_ignores_unchanged_message_error(
    app, private_chat, owner, monkeypatch
):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageText

    original_make_request = app.session.make_request
    edited_messages = set()

    async def telegram_rejects_unchanged_edit(bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            signature = (
                method.chat_id,
                method.message_id,
                method.text,
                repr(method.reply_markup),
            )
            if signature in edited_messages:
                raise TelegramBadRequest(
                    method=method,
                    message="Bad Request: message is not modified",
                )
            edited_messages.add(signature)
        return await original_make_request(bot, method, timeout)

    monkeypatch.setattr(app.session, "make_request", telegram_rejects_unchanged_edit)

    await login_owner(app, private_chat, owner)
    await app.click(private_chat, owner, "admin_schedule")
    await app.click(private_chat, owner, "sched_clear")
    await app.click(private_chat, owner, "sched_clear")
    assert "کل برنامه هفتگی پاک شد" in app.last_text()


async def test_stats_pdf_report(app, private_chat, owner):
    await seed(app)
    await login_owner(app, private_chat, owner)
    app.clear()
    await app.click(private_chat, owner, "stats_pdf")
    assert app.session.last("SendDocument") is not None


async def test_logs_pdf_export(app, private_chat, owner):
    await seed(app)
    await models.add_log(OWNER_ID, "owner", "test", "row")
    await login_owner(app, private_chat, owner)
    app.clear()
    await app.click(private_chat, owner, "logs_pdf")
    assert app.session.last("SendDocument") is not None


async def test_stats_overview_button(app, private_chat, owner):
    await seed(app)
    await login_owner(app, private_chat, owner)
    app.clear()
    await app.click(private_chat, owner, "admin_stats")
    assert "کاربر برتر" in app.all_text() or "آمار" in app.all_text()


# ─── authorisation ───────────────────────────────────────────────────────────


async def test_unauthenticated_admin_callback_is_blocked(app, private_chat):
    await seed(app)
    intruder = make_user(OTHER_ADMIN_ID, "other", "Other Admin")  # has perms, no session
    app.clear()
    await app.click(private_chat, intruder, "admin_users")
    assert "ابتدا وارد پنل" in app.all_text()
    assert await models.get_allowed_users() != []  # nothing leaked / changed


async def test_limited_admin_denied_sensitive_callbacks(app, private_chat):
    """A limited admin (view_notes/add_note/edit_note) must not manage users."""
    await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, private_chat, admin, "limited-pw")
    for data in [
        "admin_users",
        "allowed_users_list",
        "admin_admins",
        "admin_delete:1",
        "manage_owners",
        "admin_logs",
        "admin_stats",
        "admin_settings",
        "note_limit_menu",
        "admin_schedule",
        "admin_classes",
        "admin_tasks",
        "admin_convert_start",
        "admin_fields",
    ]:
        app.clear()
        await app.click(private_chat, admin, data)
        assert "دسترسی" in app.all_text(), f"{data} was NOT denied for a limited admin"


async def test_limited_admin_allowed_callbacks_work(app, private_chat):
    w = await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, private_chat, admin, "limited-pw")
    for data in ["admin_notes", f"note_view:{w.note}", f"note_download:{w.note}",
                 f"note_back:admin", "notes_page:0", "admin_pending"]:
        app.clear()
        result = await app.click(private_chat, admin, data)
        assert result is not UNHANDLED, f"{data} unhandled"
        assert "دسترسی شما" not in app.all_text(), f"{data} wrongly denied"


async def test_permission_revoked_live_takes_effect(app, private_chat):
    w = await seed(app)
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, private_chat, admin, "limited-pw")
    assert await models.get_admin_permissions(w.limited_db_id)
    await models.set_admin_permissions(w.limited_db_id, [])  # owner revokes everything
    app.clear()
    await app.click(private_chat, admin, "admin_notes")
    assert "دسترسی" in app.all_text()


async def test_owner_cannot_be_deleted(app, private_chat, owner):
    await login_owner(app, private_chat, owner)
    row = await models.get_admin_by_user_id(OWNER_ID)
    app.clear()
    await app.click(private_chat, owner, f"admin_delete:{row['id']}")
    assert await models.get_admin_by_user_id(OWNER_ID) is not None


async def test_owner_cannot_demote_configured_main(app, private_chat, owner):
    await login_owner(app, private_chat, owner)
    row = await models.get_admin_by_user_id(OWNER_ID)
    app.clear()
    await app.click(private_chat, owner, f"owner_demote:{row['id']}")
    assert (await models.get_admin_by_user_id(OWNER_ID))["is_main_admin"] == 1


async def test_admin_state_flow_requires_permission(app):
    """A limited admin cannot start a FieldAdd flow it has no permission for."""
    await seed(app)
    chat = make_chat(910002, "private")
    admin = make_user(LIMITED_ADMIN_ID, "limited", "Limited")
    await login_admin(app, chat, admin, "limited-pw")
    app.clear()
    await app.click(chat, admin, "admin_fields")
    assert "دسترسی" in app.all_text()


# ─── keyboard inventory: nothing unreachable ─────────────────────────────────


# ─── static inventory: no button without a handler ──────────────────────────


def test_no_keyboard_button_is_unrouted():
    """Every callback prefix produced anywhere must be matched by a handler
    filter, unless it comes from a builder that is known to be unreachable."""
    handled = handler_prefixes()
    unrouted = sorted(
        base for base in produced_callbacks()
        if base not in handled
        and base not in UNREACHABLE_KEYBOARD_BUILDERS
        and base not in DYNAMIC_TEMPLATES
    )
    assert not unrouted, f"buttons with no handler at all: {unrouted}"


def test_permission_rules_are_not_stale():
    """A permission rule whose callback no handler implements is dead weight -
    and a typo'd rule silently means 'no permission required', so it must fail
    loudly instead."""
    handled = handler_prefixes()
    stale = sorted(k for k in CALLBACK_PERMISSIONS if k not in handled)
    assert not stale, f"permission rules with no matching handler: {stale}"


def test_panel_menu_buttons_have_permission_rules():
    """The 14 buttons of the admin main panel must each be guarded."""
    panel = [
        "admin_fields", "admin_subjects", "admin_chapters", "admin_notes",
        "admin_pending", "admin_schedule", "admin_classes", "admin_tasks",
        "admin_convert_start", "admin_users", "admin_admins", "admin_logs",
        "admin_stats", "admin_settings",
    ]
    missing = [b for b in panel if b not in CALLBACK_PERMISSIONS]
    assert not missing, f"panel buttons without a permission rule: {missing}"


def _guarded_aliases(text: str) -> set[str]:
    """Router aliases that get AdminAuthMiddleware in this source text.
    Handles both the direct form and the `guard = AdminAuthMiddleware(...)`
    variable form used for mixed routers."""
    aliases = set(re.findall(
        r"(\w+)\.(?:callback_query|message)\.middleware\(\s*AdminAuthMiddleware", text
    ))
    for var in re.findall(r"(\w+)\s*=\s*AdminAuthMiddleware\(", text):
        aliases |= set(re.findall(
            rf"(\w+)\.(?:callback_query|message)\.middleware\(\s*{var}\s*\)", text
        ))
    return aliases


def guarded_modules() -> set[str]:
    """Modules whose router really has AdminAuthMiddleware attached, read from
    the source so this check cannot drift away from the running bot."""
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    alias_to_module = {
        alias: f"{module}.py"
        for module, alias in re.findall(
            r"^from (\w+) import router as (\w+)", main_src, re.M
        )
    }
    guarded = {alias_to_module[a] for a in _guarded_aliases(main_src)
               if a in alias_to_module}
    # routers that guard themselves inside their own module
    for path in _source_files():
        if path.name in ("main.py", "middleware.py", "conftest.py"):
            continue
        if "router" in _guarded_aliases(path.read_text(encoding="utf-8")):
            guarded.add(path.name)
    return guarded


def test_admin_handlers_live_on_a_guarded_router():
    """Handlers requiring an admin permission must sit on a router that has the
    auth middleware, or they are reachable without any admin session."""
    guarded = guarded_modules()
    assert "admin.py" in guarded, f"admin router is not guarded (found {guarded})"
    offenders = []
    for path in _source_files():
        if path.name in guarded:
            continue
        text = path.read_text(encoding="utf-8")
        for cb in _EQ.findall(text) + _SW.findall(text):
            base = cb.rstrip(":").split(":")[0]
            if base in CALLBACK_PERMISSIONS:
                offenders.append(f"{path.name}:{cb}")
    assert not offenders, (
        "admin-permission callbacks handled outside a guarded router: "
        f"{offenders}"
    )


def test_callback_data_length_within_telegram_limit():
    """callback_data must stay <= 64 bytes or Telegram rejects the button."""
    too_long = []
    for path in _source_files():
        for _is_f, raw in _CB.findall(path.read_text(encoding="utf-8")):
            sample = re.sub(r"\{[^}]*\}", "1234567890", raw).encode()
            if len(sample) > 64:
                too_long.append(f"{path.name}:{raw} ({len(sample)} bytes)")
    assert not too_long, f"callback_data over 64 bytes: {too_long}"


# ─── authorisation: unauthenticated users must not reach admin features ─────


async def test_unauthenticated_user_cannot_use_admin_task_buttons(app, private_chat):
    """A user with no admin session tapping task-management buttons must be
    refused, not served."""
    w = await seed(app)
    stranger = make_user(880001, "stranger", "Stranger")
    assert not security.admin_sessions.is_authenticated(880001)

    for data in ["admin_tasks", "tasks_cat_add", "tasks_task_add",
                 "tasks_admin_list", "tasks_cats_manage",
                 f"tasks_cat_manage:{w.cat}", f"tasks_cat_pick:{w.cat}",
                 "tasks_field:1", "tasks_subject:1", "tasks_day:0",
                 f"tasks_cat_delete:{w.cat}", "tasks_flow_cancel"]:
        app.clear()
        await app.click(private_chat, stranger, data)
        assert "ابتدا وارد پنل" in app.all_text(), (
            f"UNAUTHENTICATED user reached admin handler via {data}"
        )


async def test_unauthenticated_user_cannot_create_task_flow(app, private_chat):
    """The task FSM must not be reachable without an admin session."""
    await seed(app)
    stranger = make_user(880002, "stranger2", "Stranger2")
    await app.click(private_chat, stranger, f"tasks_cat_pick:1")
    await app.send(private_chat, stranger, "دسته ساختگی")
    await app.send(private_chat, stranger, "تکلیف ساختگی")
    grouped = await models.get_all_tasks_grouped()
    assert "دسته ساختگی" not in grouped, "unauthenticated user created a task"
    cats = await models.get_task_categories()
    assert all(c["name"] != "دسته ساختگی" for c in cats)
