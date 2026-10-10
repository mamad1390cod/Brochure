"""Integration tests for role-aware menus and persistent callback ownership."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
import security
import models
from conftest import (
    OWNER_ID,
    callback_update,
    make_callback,
    make_user,
)


def _callback_data(message_method) -> list[str]:
    markup = message_method.reply_markup
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


async def _start_and_get_menu(app, chat, user):
    await app.send(chat, user, "/start")
    menu = app.session.message_for_button(chat.id, "menu_fields")
    assert menu is not None
    sent = next(
        response_method
        for response_method, response in reversed(app.session.responses)
        if response is menu
    )
    return menu, _callback_data(sent)


async def test_start_always_shows_user_menu_and_only_active_roles_see_admin_entry(
    app, private_chat
):
    user = make_user(1001, "ali", "Ali")
    admin = make_user(1002, "mohammad", "Mohammad")
    owner = make_user(OWNER_ID, "owner", "Owner")
    admin_db_id = await models.create_admin(
        admin.id, "mohammad", "Mohammad", security.hash_password("admin-pass")
    )
    await models.set_admin_permissions(admin_db_id, ["view_panel", "view_notes"])

    _, user_callbacks = await _start_and_get_menu(app, private_chat, user)
    _, admin_callbacks = await _start_and_get_menu(app, private_chat, admin)
    _, owner_callbacks = await _start_and_get_menu(app, private_chat, owner)

    assert {"menu_fields", "submit_note_start", "menu_tools"} <= set(user_callbacks)
    assert "admin_login" not in user_callbacks
    assert "admin_login" in admin_callbacks
    assert "admin_login" in owner_callbacks

    await models.toggle_admin_active(admin_db_id, False)
    _, disabled_callbacks = await _start_and_get_menu(app, private_chat, admin)
    assert "admin_login" not in disabled_callbacks


async def test_admin_can_login_from_the_role_aware_private_main_menu(app, private_chat):
    admin = make_user(1002, "admin", "Admin")
    admin_db_id = await models.create_admin(
        admin.id, "admin", "Admin", security.hash_password("admin-pass")
    )
    await models.set_admin_permissions(admin_db_id, ["view_panel", "view_notes"])

    menu, callbacks = await _start_and_get_menu(app, private_chat, admin)
    assert "admin_login" in callbacks
    await app.click(private_chat, admin, "admin_login", message=menu)
    assert "رمز عبور" in app.all_text()
    await app.send(private_chat, admin, "admin-pass")

    assert security.admin_sessions.is_authenticated(admin.id)
    panel = app.session.message_for_button(private_chat.id, "admin_notes")
    assert panel is not None
    panel_buttons = _callback_data(
        next(method for method, response in reversed(app.session.responses) if response is panel)
    )
    assert "admin_notes" in panel_buttons
    assert "admin_admins" not in panel_buttons


async def test_group_callbacks_are_bound_to_owner_across_nested_edits_and_back(
    app, group_chat
):
    field_id = await models.create_field("ریاضی")
    subject_id = await models.create_subject(field_id, "هندسه")
    await models.create_chapter(subject_id, "فصل یک")

    ali = make_user(1001, "ali", "Ali")
    mohammad = make_user(1002, "mohammad", "Mohammad")
    reza = make_user(1003, "reza", "Reza")
    menu, _ = await _start_and_get_menu(app, group_chat, ali)
    initial_owner = await models.get_inline_keyboard_ownership(
        group_chat.id, menu.message_id
    )
    assert initial_owner is not None and initial_owner["owner_user_id"] == ali.id

    app.session.clear()
    await app.click(group_chat, mohammad, "menu_fields", message=menu)
    assert "این دکمه متعلق به شما نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []

    app.session.clear()
    await app.click(group_chat, reza, "menu_fields", message=menu)
    assert "این دکمه متعلق به شما نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []

    app.session.clear()
    await app.click(group_chat, ali, "menu_fields", message=menu)
    fields_message = app.session.message_for_button(
        group_chat.id, f"user_field:{field_id}"
    )
    assert fields_message is not None
    assert "user_field" in (
        await models.get_inline_keyboard_ownership(
            group_chat.id, fields_message.message_id
        )
    )["operation_types"]

    app.session.clear()
    await app.click(
        group_chat, mohammad, f"user_field:{field_id}", message=fields_message
    )
    assert "این دکمه متعلق به شما نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []

    app.session.clear()
    await app.click(
        group_chat, ali, f"user_field:{field_id}", message=fields_message
    )
    subjects_message = app.session.message_for_button(
        group_chat.id, f"user_subject:{subject_id}"
    )
    assert subjects_message is not None

    app.session.clear()
    await app.click(
        group_chat, ali, f"user_subject:{subject_id}", message=subjects_message
    )
    back_data = f"user_field_back:{field_id}"
    back_message = app.session.message_for_button(group_chat.id, back_data)
    assert back_message is not None
    await app.click(group_chat, ali, back_data, message=back_message)
    field_menu = app.session.message_for_button(
        group_chat.id, f"user_subject:{subject_id}"
    )
    assert field_menu is not None
    await app.click(
        group_chat, ali, f"user_subject:{subject_id}", message=field_menu
    )

    await app.send(group_chat, mohammad, "/start")
    mohammad_menu = app.session.message_for_button(group_chat.id, "menu_fields")
    assert mohammad_menu is not None
    app.session.clear()
    await app.click(group_chat, mohammad, "menu_fields", message=mohammad_menu)
    assert app.session.of("EditMessageText")


async def test_forged_or_stale_callback_is_rejected_before_handler_runs(app, group_chat):
    user = make_user(1001, "ali", "Ali")
    menu, _ = await _start_and_get_menu(app, group_chat, user)
    app.session.clear()

    await app.feed(
        callback_update(
            make_callback(user, group_chat, "admin_fields", message=menu)
        )
    )
    assert "دیگر فعال نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []

    app.session.clear()
    unknown_message = menu.model_copy(
        update={"message_id": menu.message_id + 50_000}
    )
    await app.feed(
        callback_update(
            make_callback(user, group_chat, "menu_fields", message=unknown_message)
        )
    )
    assert "قدیمی یا نامعتبر" in app.all_text()
    assert app.session.of("EditMessageText") == []


async def test_concurrent_cross_user_clicks_cannot_execute_shared_group_keyboard(
    app, group_chat
):
    owner = make_user(1001, "ali", "Ali")
    other_users = [
        make_user(1002, "mohammad", "Mohammad"),
        make_user(1003, "reza", "Reza"),
    ]
    menu, _ = await _start_and_get_menu(app, group_chat, owner)
    app.session.clear()

    await asyncio.gather(
        *(
            app.click(group_chat, user, "menu_fields", message=menu)
            for user in other_users
        )
    )

    assert app.session.of("EditMessageText") == []
    assert sum("این دکمه متعلق به شما نیست" in text for text in app.texts()) == 2


async def test_group_admin_menu_is_role_based_and_password_is_never_requested_in_group(
    app, group_chat
):
    admin = make_user(1002, "admin", "Admin")
    admin_db_id = await models.create_admin(
        admin.id, "admin", "Admin", security.hash_password("admin-pass")
    )
    await models.set_admin_permissions(admin_db_id, ["view_panel", "view_notes"])
    menu, callbacks = await _start_and_get_menu(app, group_chat, admin)
    assert "admin_login" in callbacks

    app.session.clear()
    await app.click(group_chat, admin, "admin_login", message=menu)
    assert "گفتگوی خصوصی" in app.all_text()
    assert app.session.of("EditMessageText") == []

    ordinary = make_user(1001, "user", "User")
    user_menu, user_callbacks = await _start_and_get_menu(app, group_chat, ordinary)
    assert "admin_login" not in user_callbacks
    app.session.clear()
    await app.feed(
        callback_update(
            make_callback(ordinary, group_chat, "admin_login", message=user_menu)
        )
    )
    assert "این دکمه دیگر فعال نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []


async def test_ownership_survives_clearing_in_memory_dispatcher_state(app, group_chat):
    from database import init_database

    ali = make_user(1001, "ali", "Ali")
    mohammad = make_user(1002, "mohammad", "Mohammad")
    message, _ = await _start_and_get_menu(app, group_chat, ali)
    expected = await models.get_inline_keyboard_ownership(
        group_chat.id, message.message_id
    )
    assert expected is not None

    await init_database()
    assert await models.get_inline_keyboard_ownership(
        group_chat.id, message.message_id
    ) == expected

    app.session.clear()
    await app.click(group_chat, mohammad, "menu_fields", message=message)
    assert "این دکمه متعلق به شما نیست" in app.all_text()


async def test_owner_menu_in_group_keeps_full_permissions_but_not_for_other_members(
    app, group_chat
):
    owner = make_user(OWNER_ID, "owner", "Owner")
    menu, callbacks = await _start_and_get_menu(app, group_chat, owner)
    assert "admin_login" in callbacks

    app.session.clear()
    await app.click(group_chat, owner, "admin_login", message=menu)
    admin_message = app.session.message_for_button(group_chat.id, "admin_admins")
    assert admin_message is not None

    ordinary = make_user(1001, "user", "User")
    app.session.clear()
    await app.click(
        group_chat, ordinary, "admin_admins", message=admin_message
    )
    assert "این دکمه متعلق به شما نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []

    app.session.clear()
    await app.click(group_chat, owner, "admin_admins", message=admin_message)
    assert app.session.of("EditMessageText")


async def test_deleted_keyboard_and_database_failure_fail_closed(app, group_chat, monkeypatch):
    user = make_user(1001, "ali", "Ali")
    message, _ = await _start_and_get_menu(app, group_chat, user)

    await app.bot.delete_message(group_chat.id, message.message_id)
    assert await models.get_inline_keyboard_ownership(
        group_chat.id, message.message_id
    ) is None

    app.session.clear()
    await app.feed(
        callback_update(make_callback(user, group_chat, "menu_fields", message=message))
    )
    assert "قدیمی یا نامعتبر" in app.all_text()
    assert app.session.of("EditMessageText") == []

    message, _ = await _start_and_get_menu(app, group_chat, user)
    app.session.clear()

    async def database_unavailable(_chat_id, _message_id):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(models, "get_inline_keyboard_ownership", database_unavailable)
    with pytest.raises(sqlite3.OperationalError, match="database unavailable"):
        await app.feed(
            callback_update(
                make_callback(user, group_chat, "menu_fields", message=message)
            )
        )
    assert "بررسی دسترسی موقتاً ممکن نیست" in app.all_text()
    assert app.session.of("EditMessageText") == []


async def test_private_and_group_admin_callbacks_still_require_current_role(app, private_chat):
    admin = make_user(1002, "admin", "Admin")
    admin_db_id = await models.create_admin(
        admin.id, "admin", "Admin", security.hash_password("admin-pass")
    )
    await models.set_admin_permissions(admin_db_id, ["view_panel", "view_notes"])
    security.admin_sessions.login(admin.id)

    await models.toggle_admin_active(admin_db_id, False)
    await app.click(private_chat, admin, "admin_notes")
    assert not security.admin_sessions.is_authenticated(admin.id)
    assert "ابتدا وارد پنل مدیریت" in app.all_text()
    assert app.session.of("EditMessageText") == []
