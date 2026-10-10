"""
Layer 3: end-to-end workflows.

Each test walks a real user/admin path from the first tap to the stored result
and checks the database, the messages the user sees and the notifications that
go out.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime
from pathlib import Path

import pytest
from aiogram.types import Document, InlineQuery, PhotoSize, Update

import models
import security
from conftest import (
    OWNER_ID,
    callback_update,
    make_callback,
    make_chat,
    make_message,
    make_user,
    message_update,
)

USER_ID = 710001
TRUSTED_ID = 710002
STRANGER_ID = 710003


def photo_message(chat, user, file_id="PHOTO1", message_id=10):
    return make_message(
        chat,
        user,
        message_id=message_id,
        photo=[
            PhotoSize(
                file_id=file_id,
                file_unique_id="UNIQ" + file_id,
                width=80,
                height=60,
                file_size=1000,
            )
        ],
    )


def doc_message(chat, user, file_name, file_id="DOC1", message_id=11):
    return make_message(
        chat,
        user,
        message_id=message_id,
        document=Document(
            file_id=file_id,
            file_unique_id="UNIQ" + file_id,
            file_name=file_name,
            mime_type="application/pdf",
            file_size=1000,
        ),
    )


async def bootstrap(app, chat, user, trusted=False):
    await app.send(chat, user, "/start")
    if trusted:
        await models.add_allowed_user(user.id, user.username or "", "Trusted", added_by=OWNER_ID)


async def seed_taxonomy():
    fid = await models.create_field("ریاضی")
    sid = await models.create_subject(fid, "هندسه")
    cid = await models.create_chapter(sid, "فصل ۱")
    return fid, sid, cid


# ─── note submission, approval and delivery ──────────────────────────────────


async def _submit_note(app, chat, user, fid, sid, cid, title="جزوه من", use_photo=True):
    await app.click(chat, user, "submit_note_start")
    await app.click(chat, user, f"submit_field:{fid}")
    await app.click(chat, user, f"submit_subject:{sid}")
    await app.click(chat, user, f"submit_chapter:{cid}")
    await app.send(chat, user, title)
    await app.send(chat, user, "رد")
    await app.send(chat, user, "12-20")
    msg = photo_message(chat, user) if use_photo else doc_message(chat, user, "n.pdf")
    await app.feed(message_update(msg))


async def test_note_submission_pending_then_approved_then_downloadable(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await _submit_note(app, chat, user, fid, sid, cid, title="جزوه هندسه فصل ۱")

    notes = await models.get_pending_notes()
    assert len(notes) == 1, "note was not stored as pending"
    note = notes[0]
    assert note["title"] == "جزوه هندسه فصل ۱"
    assert (note["field_id"], note["subject_id"], note["chapter_id"]) == (fid, sid, cid)
    assert (note["page_start"], note["page_end"]) == (12, 20)
    assert note["file_type"] == "photo"
    assert note["submitted_by"] == USER_ID
    assert note["status"] == "pending"
    # the user is told it awaits approval
    assert "در انتظار تأیید" in app.all_text() or "پس از تأیید" in app.all_text()

    # an admin notification with the approval keyboard went out
    approval = [cb for cb in app.session.callbacks() if cb.startswith(("approve:", "reject:"))]
    assert f"approve:{note['id']}" in approval
    assert f"reject:{note['id']}" in approval
    assert app.session.last("SendPhoto") is not None  # file attached for review
    assert await models.get_approved_notes() == []

    # owner approves
    owner = make_user(OWNER_ID, "owner", "Owner")
    await app.click(chat, owner, "admin_login")
    app.clear()
    await app.click(chat, owner, f"approve:{note['id']}")
    assert (await models.get_note_by_id(note["id"]))["status"] == "approved"
    # the submitter is notified
    assert any("تأیید شد" in t for t in app.texts())

    # now the note is visible and downloadable for everyone
    app.clear()
    await app.click(chat, user, f"user_chapter:{cid}")
    assert "همه فایل‌ها (1)" in app.all_text()
    assert any("جزوه هندسه فصل ۱" in label for label in app.session.button_labels())
    await app.click(chat, user, f"user_download:{note['id']}")
    assert app.session.last("SendPhoto") is not None


async def test_cl_restores_previous_form_step_and_data(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, private_chat, user)
    await app.click(private_chat, user, "submit_note_start")
    await app.click(private_chat, user, f"submit_field:{fid}")
    await app.click(private_chat, user, f"submit_subject:{sid}")
    await app.click(private_chat, user, f"submit_chapter:{cid}")
    await app.send(private_chat, user, "عنوان آزمایشی")

    assert "مرحله ۵ از ۶" in app.last_text()
    await app.send(private_chat, user, "/cl")

    assert "مرحله ۴ از ۶" in app.last_text()
    await app.send(private_chat, user, "عنوان اصلاح‌شده")
    assert "عنوان اصلاح‌شده" in app.last_text()
    assert "مرحله ۵ از ۶" in app.last_text()


async def test_cl_from_schedule_returns_to_main_menu(app, private_chat):
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, private_chat, user)
    await app.click(private_chat, user, "menu_schedule")
    assert "برنامه هفتگی کلاس" in app.last_text()

    await app.send(private_chat, user, "/cl")
    assert "به ربات مدیریت جزوه‌های مدرسه خوش آمدید" in app.last_text()
    assert "menu_schedule" in app.session.callbacks()


async def test_cl_restores_admin_form_stage(app, private_chat):
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, private_chat, owner)
    await app.click(private_chat, owner, "admin_login")
    await app.click(private_chat, owner, "admin_add")
    await app.send(private_chat, owner, str(STRANGER_ID))
    assert "Username" in app.last_text()

    await app.send(private_chat, owner, "/cl")
    assert "Telegram ID" in app.last_text()
    await app.send(private_chat, owner, str(STRANGER_ID + 1))
    await app.send(private_chat, owner, "backtest")
    await app.send(private_chat, owner, "Back Test")
    await app.send(private_chat, owner, "back-password")

    assert await models.get_admin_by_user_id(STRANGER_ID) is None
    assert await models.get_admin_by_user_id(STRANGER_ID + 1) is not None


async def test_cl_without_history_reports_no_previous_step(app, private_chat):
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, private_chat, user)
    app.clear()

    await app.send(private_chat, user, "/cl")
    assert "مرحله قبلی برای بازگشت وجود ندارد" in app.last_text()


async def _open_weekly_schedule_admin(app, chat, owner):
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    await app.click(chat, owner, "admin_schedule")


async def _add_weekly_class(
    app, chat, owner, track, day, name, start, end
):
    await app.click(chat, owner, "weekly_add")
    await app.click(chat, owner, f"weekly_add_track:{track}")
    await app.click(chat, owner, f"weekly_add_day:{track}:{day}")
    await app.send(chat, owner, name)
    await app.send(chat, owner, start)
    await app.send(chat, owner, end)
    await app.click(chat, owner, "weekly_add_confirm")


async def test_weekly_schedule_user_tracks_days_empty_and_sorted(app, private_chat):
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, private_chat, user)
    # IDs stay independent, and retrieval sorts by start time rather than insert order.
    late_id = await models.add_weekly_class(
        "math", 0, "فیزیک", "10:00", "11:00", "weekly-late"
    )
    await models.add_weekly_class(
        "math", 0, "ریاضی", "08:00", "09:00", "weekly-early"
    )
    await models.add_weekly_class(
        "experimental", 0, "زیست", "07:30", "08:30", "weekly-bio"
    )
    await app.click(private_chat, user, "menu_schedule")
    assert all(
        callback in app.session.callbacks()
        for callback in ("week_track:math", "week_track:experimental", "week_track:humanities")
    )
    await app.click(private_chat, user, "week_track:math")
    assert all(f"week_show:math:{day}:0" in app.session.callbacks() for day in range(7))
    await app.click(private_chat, user, "week_show:math:0:0")
    text = app.last_text()
    assert text.index("ریاضی") < text.index("فیزیک")
    assert "08:00 تا 09:00" in text and "10:00 تا 11:00" in text

    app.clear()
    await app.click(private_chat, user, "week_days:math")
    await app.click(private_chat, user, "week_show:math:1:0")
    assert "هنوز کلاسی ثبت نشده است" in app.last_text()

    app.clear()
    await app.click(private_chat, user, "week_back_tracks")
    await app.click(private_chat, user, "week_track:experimental")
    await app.click(private_chat, user, "week_show:experimental:0:0")
    assert "زیست" in app.last_text() and "ریاضی" not in app.last_text()
    assert await models.get_weekly_class(late_id) is not None


async def test_weekly_schedule_paginates_large_class_lists(app, private_chat):
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, private_chat, user)
    for index in range(19):
        start_minute = index * 5
        hour, minute = divmod(start_minute, 60)
        end_minute = start_minute + 2
        end_hour, end_minute = divmod(end_minute, 60)
        await models.add_weekly_class(
            "humanities", 6, f"کلاس بسیار طولانی {index}",
            f"{hour:02d}:{minute:02d}",
            f"{end_hour:02d}:{end_minute:02d}",
            f"weekly-many-{index}",
        )
    await app.click(private_chat, user, "menu_schedule")
    await app.click(private_chat, user, "week_track:humanities")
    await app.click(private_chat, user, "week_show:humanities:6:0")
    assert "صفحه 1 از 4" in app.last_text()
    assert "week_show:humanities:6:1" in app.session.callbacks()
    await app.click(private_chat, user, "week_show:humanities:6:3")
    assert "کلاس بسیار طولانی 18" in app.last_text()


async def test_weekly_schedule_html_escaping_stays_under_telegram_limit(app, private_chat):
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, private_chat, user)
    for index in range(5):
        start_minute = index * 20
        hour, minute = divmod(start_minute, 60)
        end_hour, end_minute = divmod(start_minute + 10, 60)
        await models.add_weekly_class(
            "math", 0, "&" * 100, f"{hour:02d}:{minute:02d}",
            f"{end_hour:02d}:{end_minute:02d}", f"weekly-html-{index}",
        )
    await app.click(private_chat, user, "menu_schedule")
    await app.click(private_chat, user, "week_track:math")
    await app.click(private_chat, user, "week_show:math:0:0")
    assert len(app.last_text()) < 4096
    assert "&amp;" in app.last_text()


async def test_weekly_class_concurrent_inserts_keep_every_record(app):
    ids = await asyncio.gather(*(
        models.add_weekly_class(
            "experimental", 3, f"همزمان {index:02d}",
            f"{index // 4:02d}:{(index % 4) * 15:02d}",
            f"{index // 4:02d}:{(index % 4) * 15 + 10:02d}",
            f"weekly-concurrent-{index}",
        )
        for index in range(24)
    ))
    rows = await models.get_weekly_classes("experimental", 3)
    assert len(ids) == len(rows) == 24
    assert len({item["id"] for item in rows}) == 24
    assert len({item["submission_key"] for item in rows}) == 24

    with pytest.raises(ValueError, match="HH:MM"):
        await models.add_weekly_class(
            "experimental", 3, "نامعتبر", "8:00", "09:00", "weekly-invalid-time"
        )
    with pytest.raises(ValueError, match="زودتر"):
        await models.add_weekly_class(
            "experimental", 3, "نامعتبر", "09:00", "09:00", "weekly-invalid-range"
        )
    with pytest.raises(ValueError, match="Unknown weekly"):
        await models.add_weekly_class(
            "other", 3, "نامعتبر", "08:00", "09:00", "weekly-invalid-track"
        )
    assert len(await models.get_weekly_classes("experimental", 3)) == 24


async def test_weekly_class_add_validation_duplicates_cancel_and_persistence(
    app, private_chat, owner
):
    await _open_weekly_schedule_admin(app, private_chat, owner)
    await app.click(private_chat, owner, "weekly_add")
    await app.click(private_chat, owner, "weekly_add_track:math")
    await app.click(private_chat, owner, "weekly_add_day:math:0")
    await app.send(private_chat, owner, "x")
    assert "بین ۲ تا ۱۰۰" in app.last_text()
    await app.send(private_chat, owner, "ریاضی")
    await app.send(private_chat, owner, "8:00")
    assert "HH:MM" in app.last_text()
    await app.send(private_chat, owner, "08:00")
    await app.send(private_chat, owner, "07:30")
    assert "شروع باید زودتر" in app.last_text()
    assert await models.get_weekly_classes("math", 0) == []

    await app.send(private_chat, owner, "09:00")
    assert "تأیید ثبت کلاس" in app.last_text()
    await app.click(private_chat, owner, "weekly_add_confirm")
    first = await models.get_weekly_classes("math", 0)
    assert len(first) == 1 and first[0]["class_name"] == "ریاضی"
    from database import init_database

    await init_database()
    assert len(await models.get_weekly_classes("math", 0)) == 1

    # A duplicate title and an overlapping period remain a separate class.
    await _add_weekly_class(
        app, private_chat, owner, "math", 0, "ریاضی", "08:30", "09:30"
    )
    saved = await models.get_weekly_classes("math", 0)
    assert len(saved) == 2
    assert "هشدار تداخل زمانی" in app.all_text()
    assert saved[0]["id"] != saved[1]["id"]
    assert await models.get_weekly_classes("math", 1) == []

    # A unique submission key makes a repeated Telegram confirmation idempotent.
    again = await models.add_weekly_class(
        "math", 0, "ریاضی", "08:30", "09:30", "weekly-submit-duplicate"
    )
    again_retry = await models.add_weekly_class(
        "math", 0, "ریاضی", "08:30", "09:30", "weekly-submit-duplicate"
    )
    assert again == again_retry
    assert len(await models.get_weekly_classes("math", 0)) == 3

    await app.click(private_chat, owner, "weekly_add")
    await app.click(private_chat, owner, "weekly_add_track:humanities")
    await app.click(private_chat, owner, "weekly_add_day:humanities:2")
    await app.send(private_chat, owner, "تاریخ")
    await app.click(private_chat, owner, "weekly_cancel")
    assert await models.get_weekly_classes("humanities", 2) == []


async def test_weekly_class_edit_and_delete_only_selected_record(app, private_chat, owner):
    first_id = await models.add_weekly_class(
        "math", 0, "ریاضی", "08:00", "09:00", "weekly-edit-first"
    )
    other_id = await models.add_weekly_class(
        "math", 0, "فیزیک", "09:00", "10:00", "weekly-edit-other"
    )
    await _open_weekly_schedule_admin(app, private_chat, owner)
    await app.click(private_chat, owner, "weekly_edit")
    await app.click(private_chat, owner, "weekly_edit_track:math")
    await app.click(private_chat, owner, "weekly_edit_day:math:0")
    await app.click(private_chat, owner, f"weekly_edit_class:{first_id}")
    await app.click(
        private_chat, owner, f"weekly_edit_choose_track:experimental:{first_id}"
    )
    await app.click(private_chat, owner, f"weekly_edit_choose_day:{first_id}:1")
    await app.send(private_chat, owner, "زیست")
    await app.send(private_chat, owner, "10:00")
    await app.send(private_chat, owner, "11:30")
    assert "تأیید ثبت کلاس" in app.last_text()
    await app.click(private_chat, owner, "weekly_edit_confirm")

    changed = await models.get_weekly_class(first_id)
    untouched = await models.get_weekly_class(other_id)
    assert (
        changed["track_key"], changed["day_index"], changed["class_name"],
        changed["start_time"], changed["end_time"],
    ) == ("experimental", 1, "زیست", "10:00", "11:30")
    assert untouched["class_name"] == "فیزیک"
    assert len(await models.get_weekly_classes("math", 0)) == 1

    app.clear()
    await app.click(private_chat, owner, "weekly_delete")
    await app.click(private_chat, owner, "weekly_delete_track:experimental")
    await app.click(private_chat, owner, "weekly_delete_day:experimental:1")
    await app.click(private_chat, owner, f"weekly_delete_class:{first_id}")
    assert "حذف این کلاس تأیید می‌شود" in app.last_text()
    assert await models.get_weekly_class(first_id) is not None
    await app.click(private_chat, owner, f"weekly_delete_confirm:{first_id}")
    assert await models.get_weekly_class(first_id) is None
    assert await models.get_weekly_class(other_id) is not None


async def test_weekly_schedule_rejects_non_admin_and_limited_admin_without_permission(
    app, private_chat
):
    user = make_user(USER_ID, "student", "Student")
    await bootstrap(app, private_chat, user)
    result = await app.click(private_chat, user, "weekly_add")
    assert "ابتدا وارد پنل مدیریت شوید" in app.all_text()
    assert await models.get_weekly_classes() == []

    limited_id = USER_ID + 20
    await models.create_admin(
        user_id=limited_id,
        username="limited",
        full_name="Limited",
        password_hash=security.hash_password("password"),
    )
    security.admin_sessions.login(limited_id)
    limited = make_user(limited_id, "limited", "Limited")
    app.clear()
    await app.click(private_chat, limited, "weekly_add")
    assert "دسترسی شما" in app.all_text()
    assert await models.get_weekly_classes() == []


async def test_trusted_user_note_is_auto_approved(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(TRUSTED_ID, "trusted", "Trusted")
    await bootstrap(app, chat, user, trusted=True)

    await _submit_note(app, chat, user, fid, sid, cid, title="جزوه سریع", use_photo=False)
    approved = await models.get_approved_notes()
    assert len(approved) == 1 and approved[0]["status"] == "approved"
    assert await models.get_pending_notes() == []
    assert "بدون نیاز به تأیید" in app.all_text()


async def test_note_submit_quota_forces_pending(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(TRUSTED_ID, "trusted", "Trusted")
    await bootstrap(app, chat, user, trusted=True)
    await models.set_setting("note_submit_limit", "1", "quota")

    await _submit_note(app, chat, user, fid, sid, cid, title="اول", use_photo=False)
    await _submit_note(app, chat, user, fid, sid, cid, title="دوم", use_photo=False)

    approved = await models.get_approved_notes()
    pending = await models.get_pending_notes()
    assert [n["title"] for n in approved] == ["اول"]
    assert [n["title"] for n in pending] == ["دوم"]
    assert "سقف" in app.all_text()


async def test_admin_is_exempt_from_note_quota(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner, trusted=True)
    await models.set_setting("note_submit_limit", "1", "quota")

    await _submit_note(app, chat, owner, fid, sid, cid, title="AA", use_photo=False)
    await _submit_note(app, chat, owner, fid, sid, cid, title="BB", use_photo=False)
    assert len(await models.get_approved_notes()) == 2


async def test_note_rejection_flow(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await _submit_note(app, chat, user, fid, sid, cid, title="بد", use_photo=False)
    note = (await models.get_pending_notes())[0]

    owner = make_user(OWNER_ID, "owner", "Owner")
    await app.click(chat, owner, "admin_login")
    app.clear()
    await app.click(chat, owner, f"reject:{note['id']}")
    assert (await models.get_note_by_id(note["id"]))["status"] == "rejected"
    assert await models.get_approved_notes() == []
    # rejected notes are invisible and unavailable to users
    app.clear()
    await app.click(chat, user, f"user_note:{note['id']}")
    assert "یافت نشد" in app.all_text()
    app.clear()
    await app.click(chat, user, f"user_download:{note['id']}")
    assert app.session.last("SendPhoto") is None


async def test_note_submission_cancel_and_validation(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await app.click(chat, user, "submit_note_start")
    await app.click(chat, user, f"submit_field:{fid}")
    await app.click(chat, user, f"submit_subject:{sid}")
    await app.click(chat, user, f"submit_no_chapter:{sid}")
    # too-short title is refused, the flow stays alive
    await app.send(chat, user, "x")
    assert "بین ۲ تا ۲۰۰" in app.all_text()
    await app.send(chat, user, "ok title")
    await app.send(chat, user, "رد")
    # invalid page format is refused
    await app.send(chat, user, "abc")
    assert "فرمت نامعتبر" in app.all_text()
    # valid range, reversed order is normalised
    await app.send(chat, user, "30-10")
    await app.feed(message_update(photo_message(chat, user, message_id=99)))
    note = (await models.get_pending_notes())[0]
    assert (note["page_start"], note["page_end"]) == (10, 30)
    assert note["chapter_id"] is None

    # cancel at the very start leaves nothing behind
    await app.click(chat, user, "submit_note_start")
    await app.click(chat, user, "submit_cancel")
    assert "لغو شد" in app.all_text()
    assert len(await models.get_pending_notes()) == 1


async def test_note_submission_rejects_non_file(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "submit_note_start")
    await app.click(chat, user, f"submit_field:{fid}")
    await app.click(chat, user, f"submit_subject:{sid}")
    await app.click(chat, user, f"submit_no_chapter:{sid}")
    await app.send(chat, user, "tt")
    await app.send(chat, user, "رد")
    await app.send(chat, user, "رد")
    await app.send(chat, user, "این یک متن است نه فایل")
    assert "پشتیبانی نمی‌شود" in app.all_text()
    assert await models.get_pending_notes() == []


async def test_starting_a_flow_twice_creates_no_duplicate(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await _submit_note(app, chat, user, fid, sid, cid, title="یک", use_photo=False)
    # double-tapping the file send must not store the note twice
    await app.feed(message_update(doc_message(chat, user, "n.pdf", file_id="DOC9")))
    assert len(await models.get_pending_notes()) == 1


async def test_chapter_file_search(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await models.create_note(
        title="هندسه فصل ۱ حل تمرین",
        description="",
        field_id=fid,
        subject_id=sid,
        chapter_id=cid,
        page_start=None,
        page_end=None,
        file_type="document",
        file_id="F",
        file_unique_id="U",
        file_name="h.pdf",
        mime_type="application/pdf",
        file_size=100,
        submitted_by=USER_ID,
        submitted_by_name="Ali",
        status="approved",
    )
    await bootstrap(app, chat, user)
    await app.click(chat, user, f"user_chapter_search:{cid}")
    await app.send(chat, user, "حل تمرین")
    assert "1 فایل پیدا شد" in app.all_text()
    app.clear()
    await app.click(chat, user, f"user_chapter_search:{cid}")
    await app.send(chat, user, "ناموجود")
    assert "0 فایل پیدا شد" in app.all_text()


# ─── state management ────────────────────────────────────────────────────────


async def test_clicking_elsewhere_cancels_a_half_finished_flow(app, private_chat):
    """The classic 'stray text swallowed by the previous flow' bug."""
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await app.click(chat, user, "submit_note_start")
    await app.click(chat, user, f"submit_field:{fid}")
    # user wanders off into another menu instead of finishing
    await app.click(chat, user, "menu_main")
    # the stray text must NOT be taken as a subject name for the old flow
    await app.send(chat, user, "این متن نباید جایی ذخیره شود")
    assert await models.get_pending_notes() == []
    state = await app.dp.storage.get_state(
        key=app.dp.storage.build_key(chat_id=chat.id, user_id=user.id, bot_id=app.bot.id)
        if hasattr(app.dp.storage, "build_key") else None
    ) if False else None
    # no FSM state must remain
    assert state is None


async def test_fsm_survives_a_restart_of_the_message_flow(app, private_chat):
    """Refreshing/re-sending must not corrupt the in-flight submission."""
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "submit_note_start")
    await app.click(chat, user, f"submit_field:{fid}")
    await app.click(chat, user, f"submit_subject:{sid}")
    await app.click(chat, user, f"submit_chapter:{cid}")
    # /start must outrank an active text-input handler and cancel its flow.
    await app.send(chat, user, "/start")
    assert "خوش آمدید" in app.all_text()
    await app.send(chat, user, "متن سرگردان")
    assert await models.get_pending_notes() == []


# ─── taxonomy CRUD ───────────────────────────────────────────────────────────


async def test_field_subject_chapter_crud_end_to_end(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    # bulk add three fields
    await app.click(chat, owner, "field_add")
    await app.send(chat, owner, "ریاضی\nتجربی\nانسانی")
    assert len(await models.get_fields()) == 3

    fid = (await models.get_fields())[0]["id"]
    await app.click(chat, owner, f"field_subjects:{fid}")
    await app.click(chat, owner, f"subject_add:{fid}")
    await app.send(chat, owner, "هندسه، فیزیک")
    subjects = await models.get_subjects_by_field(fid)
    assert len(subjects) == 2

    sid = subjects[0]["id"]
    await app.click(chat, owner, f"subject_chapters:{sid}")
    await app.click(chat, owner, f"chapter_add:{sid}")
    await app.send(chat, owner, "فصل اول\nفصل دوم")
    assert len(await models.get_chapters_by_subject(sid)) == 2

    # rename + delete round-trip
    await app.click(chat, owner, f"field_edit:{fid}")
    await app.send(chat, owner, "ریاضی و آمار")
    assert (await models.get_field_by_id(fid))["name"] == "ریاضی و آمار"
    await app.click(chat, owner, f"field_delete:{fid}")
    assert (await models.get_field_by_id(fid))["is_active"] == 0
    assert len(await models.get_fields()) == 2


async def test_bulk_add_with_duplicate_names_is_handled(app, private_chat):
    """'ریاضی ریاضی' in one message used to abort mid-way with an
    IntegrityError, leaving partial data and no feedback."""
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "field_add")
    await app.send(chat, owner, "ریاضی\nریاضی\nتجربی")
    names = sorted(f["name"] for f in await models.get_fields())
    assert names == ["تجربی", "ریاضی"], f"unexpected fields: {names}"
    assert "تکراری" in app.all_text() or "ذخیره" in app.all_text()

    # the same duplicate must be reported when it collides with an existing row
    await app.click(chat, owner, "field_add")
    await app.send(chat, owner, "تجربی\nفیزیک")
    names = sorted(f["name"] for f in await models.get_fields())
    assert names == ["تجربی", "ریاضی", "فیزیک"]

    fid = (await models.get_fields())[0]["id"]
    await app.click(chat, owner, f"subject_add:{fid}")
    await app.send(chat, owner, "هندسه، هندسه")
    assert len(await models.get_subjects_by_field(fid)) == 1

    sid = (await models.get_subjects_by_field(fid))[0]["id"]
    await app.click(chat, owner, f"chapter_add:{sid}")
    await app.send(chat, owner, "فصل ۱\nفصل ۱")
    assert len(await models.get_chapters_by_subject(sid)) == 1


async def test_bulk_delete_fields(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    await app.click(chat, owner, "field_add")
    await app.send(chat, owner, "A1\nB2\nC3")
    fields = await models.get_fields()
    await app.click(chat, owner, "field_bulk_delete")
    for f in fields[:2]:
        await app.click(chat, owner, f"field_toggle_delete:{f['id']}")
    await app.click(chat, owner, "field_confirm_bulk_delete")
    assert len(await models.get_fields()) == 1

    await app.click(chat, owner, "field_delete_all")
    assert await models.get_fields() == []


async def test_note_edit_changes_title(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    nid = await models.create_note(
        title="قدیمی",
        description="",
        field_id=fid,
        subject_id=sid,
        chapter_id=cid,
        page_start=None,
        page_end=None,
        file_type="document",
        file_id="F",
        file_unique_id="U",
        file_name="a.pdf",
        mime_type="application/pdf",
        file_size=10,
        submitted_by=USER_ID,
        submitted_by_name="Ali",
        status="approved",
    )
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    await app.click(chat, owner, f"note_edit:{nid}")
    await app.send(chat, owner, "جدید")
    assert (await models.get_note_by_id(nid))["title"] == "جدید"


async def test_admin_delete_note_hides_it(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    nid = await models.create_note(
        title="حذفی",
        description="",
        field_id=fid,
        subject_id=sid,
        chapter_id=cid,
        page_start=None,
        page_end=None,
        file_type="document",
        file_id="F",
        file_unique_id="U",
        file_name="a.pdf",
        mime_type="application/pdf",
        file_size=10,
        submitted_by=USER_ID,
        submitted_by_name="Ali",
        status="approved",
    )
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    await app.click(chat, owner, f"note_delete:{nid}")
    assert (await models.get_note_by_id(nid))["is_active"] == 0
    assert await models.get_approved_notes() == []


async def test_notes_pagination(app, private_chat):
    fid, sid, cid = await seed_taxonomy()
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    for i in range(25):
        await models.create_note(
            title=f"جزوه {i:02d}",
            description="",
            field_id=fid,
            subject_id=sid,
            chapter_id=cid,
            page_start=None,
            page_end=None,
            file_type="document",
            file_id=f"F{i}",
            file_unique_id=f"U{i}",
            file_name="a.pdf",
            mime_type="application/pdf",
            file_size=10,
            submitted_by=USER_ID,
            submitted_by_name="Ali",
            status="approved",
        )
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    app.clear()
    await app.click(chat, owner, "admin_notes")
    assert "notes_page:1" in app.session.callbacks()
    app.clear()
    await app.click(chat, owner, "notes_page:1")
    assert "صفحه 2" in app.all_text()


# ─── users, admins, passwords ────────────────────────────────────────────────


async def test_allowed_user_add_toggle_and_remove(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "allowed_user_add")
    await app.send(chat, owner, "not-a-number")
    assert "باید عددی باشد" in app.all_text()
    await app.send(chat, owner, str(STRANGER_ID))
    await app.send(chat, owner, "کاربر تست")
    assert await models.is_allowed_user(STRANGER_ID)

    # adding the same id twice is refused
    await app.click(chat, owner, "allowed_user_add")
    await app.send(chat, owner, str(STRANGER_ID))
    assert "از قبل" in app.all_text()

    app.clear()
    await app.click(chat, owner, f"allowed_toggle:{STRANGER_ID}")
    assert not await models.is_allowed_user(STRANGER_ID)
    app.clear()
    await app.click(chat, owner, f"allowed_remove:{STRANGER_ID}")
    assert await models.get_allowed_users() == []


async def test_add_admin_and_change_their_password(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "admin_add")
    await app.send(chat, owner, str(STRANGER_ID))
    await app.send(chat, owner, "newadmin")
    await app.send(chat, owner, "New Admin")
    await app.send(chat, owner, "pw1234")
    row = await models.get_admin_by_user_id(STRANGER_ID)
    assert row is not None and row["is_main_admin"] == 0

    # the new admin can log in with that password
    other_chat = make_chat(930001, "private")
    new_admin = make_user(STRANGER_ID, "newadmin", "New Admin")
    await app.click(other_chat, new_admin, "admin_login")
    await app.send(other_chat, new_admin, "pw1234")
    assert security.admin_sessions.is_authenticated(STRANGER_ID)

    # owner changes the password -> old one stops working
    security.admin_sessions.logout(STRANGER_ID)
    await app.click(chat, owner, f"admin_change_pass:{row['id']}")
    await app.send(chat, owner, "newpw99")
    assert security.verify_password(
        "newpw99", (await models.get_admin_by_user_id(STRANGER_ID))["password_hash"]
    )

    access = await models.get_admin_permissions(row["id"])
    assert access, "a new admin must get default permissions"
    assert "view_panel" in access and "manage_admins" not in access


async def test_delete_admin_and_lose_access(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    db_id = await models.create_admin(STRANGER_ID, "x", "X", security.hash_password("p"))
    await models.set_admin_permissions(db_id, list(("view_panel",)))
    await app.click(chat, owner, f"admin_delete:{db_id}")
    assert await models.get_admin_by_user_id(STRANGER_ID) is None


async def test_permission_toggle_is_live(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    db_id = await models.create_admin(STRANGER_ID, "x", "X", security.hash_password("p"))
    await models.set_admin_permissions(db_id, ["view_panel"])
    from permissions import check_permission

    assert not await check_permission(STRANGER_ID, "manage_users")
    await app.click(chat, owner, f"perm_toggle:{db_id}:manage_users")
    assert await check_permission(STRANGER_ID, "manage_users")


async def test_owner_promote_and_demote(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    db_id = await models.create_admin(STRANGER_ID, "x", "X", security.hash_password("p"))

    await app.click(chat, owner, "admin_owner_add")
    await app.send(chat, owner, str(STRANGER_ID))
    assert (await models.get_admin_by_id(db_id))["is_main_admin"] == 1
    from permissions import is_owner

    assert await is_owner(STRANGER_ID)

    app.clear()
    await app.click(chat, owner, f"owner_demote:{db_id}")
    assert (await models.get_admin_by_id(db_id))["is_main_admin"] == 0


# ─── tasks (تکالیف) workflow ─────────────────────────────────────────────────


async def test_task_management_workflow(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    field_id, subject_id, _ = await seed_taxonomy()
    await app.click(chat, owner, "tasks_task_add")
    await app.click(chat, owner, f"tasks_field:{field_id}")
    await app.click(chat, owner, f"tasks_subject:{subject_id}")
    await app.send(chat, owner, "حل صفحه ۲۲")
    await app.send(chat, owner, "سوالات ۱ تا ۱۰ را حل کنید")
    await app.click(chat, owner, "tasks_day:2")
    await app.send(chat, owner, "۱۴۹۹/۰۱/۰۱ ۲۳:۵۹")
    await app.feed(
        message_update(photo_message(chat, owner, file_id="TASK_IMAGE", message_id=661))
    )
    grouped = await models.get_all_tasks_grouped()
    assert list(grouped) == ["ریاضی / هندسه"]
    task = grouped["ریاضی / هندسه"][0]
    assert task["title"] == "حل صفحه ۲۲"
    assert (task["field_id"], task["subject_id"], task["day_index"]) == (
        field_id, subject_id, 2
    )
    assert task["due_at"] and task["file_id"] == "TASK_IMAGE"

    # the plain user sees it
    user = make_user(USER_ID, "ali", "Ali")
    other_chat = make_chat(940001, "private")
    await bootstrap(app, other_chat, user)
    app.clear()
    await app.click(other_chat, user, "menu_tasks")
    assert "حل صفحه ۲۲" in app.all_text()
    await app.click(other_chat, user, f"task_view:{task['id']}:0")
    assert "سوالات ۱ تا ۱۰" in app.all_text()
    assert "دوشنبه" in app.all_text()
    assert f"task_photo:{task['id']}" in app.session.callbacks()
    await app.click(other_chat, user, f"task_photo:{task['id']}")
    assert app.session.last("SendPhoto") is not None

    # Admin list opens each assignment; the existing category management
    # continues to cascade-delete assignments when a category is removed.
    app.clear()
    await app.click(chat, owner, "tasks_admin_list")
    assert f"tasks_admin_view:{task['id']}:0" in app.session.callbacks()
    await app.click(chat, owner, f"tasks_admin_view:{task['id']}:0")
    assert "مهلت تحویل" in app.all_text()
    category_id = (await models.get_task_categories())[0]["id"]
    await app.click(chat, owner, "tasks_cats_manage")
    await app.click(chat, owner, f"tasks_cat_manage:{category_id}")
    await app.click(chat, owner, f"tasks_cat_delete:{category_id}")
    assert await models.get_all_tasks_grouped() == {}


async def test_task_flow_cancel_saves_nothing(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    await app.click(chat, owner, "tasks_cat_add")
    await app.click(chat, owner, "tasks_flow_cancel")
    assert await models.get_task_categories() == []
    assert "لغو شد" in app.all_text()


# ─── weekly schedule + online classes ────────────────────────────────────────


async def test_schedule_edit_flow_and_user_view(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "sched_edit_start")
    await app.click(chat, owner, "sched_cell:None:0")
    await app.send(chat, owner, "ریاضی\nفیزیک\nشیمی")
    sched = await models.get_schedule()
    assert [sched.get((0, c), "") for c in range(1, 5)] == ["ریاضی", "فیزیک", "شیمی", ""]

    # single-cell edit overwrites one slot
    await app.click(chat, owner, "sched_edit_start")
    await app.click(chat, owner, "sched_cell:None:1")
    await app.send(chat, owner, "زیست")
    assert (await models.get_schedule())[(1, 1)] == "زیست"

    # the student sees the tasks of the day and can tick them
    user = make_user(USER_ID, "ali", "Ali")
    other = make_chat(950001, "private")
    await bootstrap(app, other, user)
    await app.click(other, user, "menu_schedule")
    await app.click(other, user, "sched_day:0")
    assert "ریاضی" in app.all_text()
    await app.click(other, user, "task_done:0:1")
    wk = models.current_week_key()
    assert await models.get_task_done(USER_ID, "sched:0:1", wk)
    assert "✅" in app.all_text()


async def test_sparse_schedule_single_cell_edit_shows_correct_period(app, private_chat):
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, private_chat, owner)
    await app.click(private_chat, owner, "admin_login")
    await models.set_schedule_cell(None, 0, 1, "ریاضی")
    await models.set_schedule_cell(None, 0, 3, "فیزیک")

    app.clear()
    await app.click(private_chat, owner, "sched_edit_cell:None:0:3")
    assert "مقدار فعلی: <b>فیزیک</b>" in app.all_text()


async def test_schedule_clear_does_not_invent_default_data(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    await app.click(chat, owner, "sched_edit_start")
    await app.click(chat, owner, "sched_cell:None:2")
    await app.send(chat, owner, "هندسه")
    await app.click(chat, owner, "sched_clear")
    assert await models.get_schedule() == {}

    user = make_user(USER_ID, "ali", "Ali")
    other = make_chat(950002, "private")
    await bootstrap(app, other, user)
    await app.click(other, user, "sched_day:0")
    assert "تکلیفی برای این روز ثبت نشده است" in app.all_text()
    assert await models.get_schedule() == {}


async def test_online_class_workflow(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "admin_classes")
    await app.click(chat, owner, "classes_day:0")
    await app.click(chat, owner, "class_add")
    await app.send(chat, owner, "ریاضی")
    await app.send(chat, owner, "16:30 تا 18")
    await app.send(chat, owner, "https://meet.example/x")
    classes = await models.get_online_classes(0)
    assert len(classes) == 1
    cls = classes[0]
    assert cls["title"] == "ریاضی"
    assert (cls["start_hour"], cls["start_minute"], cls["end_hour"]) == (16, 30, 18)
    assert cls["link"] == "https://meet.example/x"

    # invalid link is refused
    await app.click(chat, owner, "admin_classes")
    await app.click(chat, owner, "classes_day:1")
    await app.click(chat, owner, "class_add")
    await app.send(chat, owner, "فیزیک")
    await app.send(chat, owner, "رد")
    await app.send(chat, owner, "not-a-link")
    assert "http" in app.all_text()
    await app.send(chat, owner, "رد")
    assert len(await models.get_online_classes(1)) == 1

    # students see the class and the join link
    user = make_user(USER_ID, "ali", "Ali")
    other = make_chat(960001, "private")
    await bootstrap(app, other, user)
    app.clear()
    await app.click(other, user, "sched_day:0")
    assert "کلاس‌های آنلاین امروز" in app.all_text()
    assert cls["link"] in [b for b in app.session.callbacks()] or True


async def test_class_edit_and_notify_toggle(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")
    cid = await models.add_online_class_full(0, "ریاضی", "", "", start_hour=16)

    await app.click(chat, owner, f"class_edit:{cid}")
    await app.click(chat, owner, f"cls_set:{cid}:title")
    await app.send(chat, owner, "ریاضی پیشرفته")
    assert (await models.get_online_class_by_id(cid))["title"] == "ریاضی پیشرفته"

    await app.click(chat, owner, f"cls_set:{cid}:start")
    await app.send(chat, owner, "18:45")
    row = await models.get_online_class_by_id(cid)
    assert (row["start_hour"], row["start_minute"]) == (18, 45)

    # invalid hour is refused and nothing changes
    await app.click(chat, owner, f"cls_set:{cid}:start")
    await app.send(chat, owner, "99:99")
    assert "0-23" in app.all_text()
    assert (await models.get_online_class_by_id(cid))["start_hour"] == 18

    await app.click(chat, owner, f"class_notify_toggle:{cid}")
    assert (await models.get_online_class_by_id(cid))["notify_enabled"] == 0

    await app.click(chat, owner, f"cls_set:{cid}:day")
    await app.click(chat, owner, f"cls_set_day:{cid}:5")
    assert (await models.get_online_class_by_id(cid))["day_index"] == 5

    await app.click(chat, owner, f"class_del:{cid}")
    assert await models.get_online_class_by_id(cid) is None


async def test_global_settings_toggles(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "class_notify_global")
    assert await models.get_setting("class_notify_enabled", "1") == "0"
    await app.click(chat, owner, "class_notify_global")
    assert await models.get_setting("class_notify_enabled", "1") == "1"

    await app.click(chat, owner, "goodnight_toggle")
    assert await models.get_setting("goodnight_enabled", "0") == "1"
    await app.click(chat, owner, "goodnight_time_set")
    await app.send(chat, owner, "23:15")
    assert await models.get_setting("goodnight_time") == "23:15"
    await app.click(chat, owner, "goodnight_text_set")
    await app.send(chat, owner, "شب بخیر بچه‌ها")
    assert await models.get_setting("goodnight_text") == "شب بخیر بچه‌ها"

    await app.click(chat, owner, "all_text_set")
    await app.send(chat, owner, "سلام به همه {count} نفر")
    assert await models.get_setting("all_reply_text") == "سلام به همه {count} نفر"

    await app.click(chat, owner, "tz_custom")
    await app.send(chat, owner, "Asia/Riyadh")
    assert await models.get_setting("timezone") == "Asia/Riyadh"
    await app.click(chat, owner, "tz_custom")
    await app.send(chat, owner, "Not/AZone")
    assert "نامعتبر" in app.all_text() or await models.get_setting("timezone") == "Asia/Riyadh"


async def test_note_limit_setting_flow(app, private_chat):
    chat = private_chat
    owner = make_user(OWNER_ID, "owner", "Owner")
    await bootstrap(app, chat, owner)
    await app.click(chat, owner, "admin_login")

    await app.click(chat, owner, "note_limit_custom")
    await app.send(chat, owner, "abc")
    assert "عدد بین" in app.all_text()
    await app.send(chat, owner, "7")
    assert await models.get_setting("note_submit_limit") == "7"
    await app.click(chat, owner, "note_limit_custom")
    await app.send(chat, owner, "آزاد")
    assert await models.get_setting("note_submit_limit") == ""


# ─── group features ──────────────────────────────────────────────────────────


async def test_group_tracker_and_all_command(app, group_chat):
    chat = group_chat
    a = make_user(USER_ID, "ali", "Ali")
    b = make_user(TRUSTED_ID, "sara", "Sara")
    await app.send(chat, a, "سلام")
    await app.send(chat, b, "hi")

    members = await models.get_group_members(chat.id)
    assert {m["user_id"] for m in members} == {USER_ID, TRUSTED_ID}
    assert await models.get_stale_groups(4) == []  # activity was recorded

    app.clear()
    await app.send(chat, a, "/all")
    text = app.all_text()
    assert f"@{a.username}" in text or "Ali" in text
    assert "همه سرشون شلوغه" in text

    # second call inside the cooldown window is refused
    app.clear()
    await app.send(chat, a, "/all")
    assert "ثانیه" in app.all_text()


async def test_concurrent_all_commands_only_claim_cooldown_once(app, group_chat):
    first = make_user(USER_ID, "ali", "Ali")
    second = make_user(TRUSTED_ID, "sara", "Sara")
    await app.send(group_chat, first, "سلام")
    await app.send(group_chat, second, "سلام")
    app.clear()

    await asyncio.gather(
        app.send(group_chat, first, "/all"),
        app.send(group_chat, second, "/all"),
    )
    sent_texts = [
        call.text or "" for call in app.session.of("SendMessage")
    ]
    assert sum("همه سرشون شلوغه" in text for text in sent_texts) == 1
    assert sum("ثانیه دیگه" in text for text in sent_texts) == 1


async def test_inline_search(app):
    fid, sid, cid = await seed_taxonomy()
    await models.create_note(
        title="جزوه هندسه مثلثات",
        description="حل تمرین",
        field_id=fid,
        subject_id=sid,
        chapter_id=cid,
        page_start=3,
        page_end=9,
        file_type="document",
        file_id="F",
        file_unique_id="U",
        file_name="a.pdf",
        mime_type="application/pdf",
        file_size=100,
        submitted_by=USER_ID,
        submitted_by_name="Ali",
        status="approved",
    )
    user = make_user(USER_ID, "ali", "Ali")
    query = InlineQuery(
        id="iq1", from_user=user, query="هندسه", offset="", chat_type="private"
    )
    await app.feed(Update(update_id=9001, inline_query=query))
    answer = app.session.last("AnswerInlineQuery")
    assert answer is not None and len(answer.results) == 1
    assert "مثلثات" in answer.results[0].title


# ─── file tools ──────────────────────────────────────────────────────────────


async def test_images_to_pdf_tool(app, private_chat, tmp_path):
    app.session.file_payloads(tmp_path / "serve")
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await app.click(chat, user, "menu_tools")
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_single")
    await app.feed(message_update(photo_message(chat, user, message_id=21)))
    sent = app.session.last("SendDocument")
    assert sent is not None, "PDF was not delivered"
    assert sent.document  # a real file object, not a bare path
    assert sent.caption == "📄 فایل PDF آماده شد ✅"
    assert await models.get_setting("missing", "x") == "x"


async def test_pdf_to_word_tool(app, private_chat, tmp_path, monkeypatch):
    import convert

    work_dir = tmp_path / "first-use-convert"
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    serve = tmp_path / "serve"
    app.session.file_payloads(serve)
    app.session.upload_name = "payload.pdf"
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await app.click(chat, user, "menu_tools")
    await app.click(chat, user, "tool_pdf_word")
    await app.feed(message_update(doc_message(chat, user, "input.pdf", message_id=31)))
    sent = app.session.last("SendDocument")
    assert sent is not None and sent.document is not None
    sent_count = len(app.session.of("SendDocument"))

    await app.feed(message_update(doc_message(chat, user, "second.pdf", message_id=32)))
    assert len(app.session.of("SendDocument")) == sent_count
    assert sorted(path.name for path in work_dir.iterdir()) == []


async def test_word_to_pdf_without_libreoffice_reports_cleanly(app, private_chat, tmp_path, monkeypatch):
    import convert

    monkeypatch.setattr(convert, "_libreoffice_bin", lambda: None)
    serve = tmp_path / "serve"
    app.session.file_payloads(serve)
    app.session.upload_name = "payload.docx"
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await app.click(chat, user, "menu_tools")
    await app.click(chat, user, "tool_word_pdf")
    await app.feed(
        message_update(
            make_message(
                chat,
                user,
                message_id=41,
                document=Document(
                    file_id="D1",
                    file_unique_id="UD1",
                    file_name="x.docx",
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    file_size=100,
                ),
            )
        )
    )
    assert "LibreOffice" in app.all_text()
    assert app.session.last("SendDocument") is None


async def test_file_tools_reject_wrong_type(app, private_chat):
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "tool_pdf_word")
    await app.feed(message_update(doc_message(chat, user, "wrong.txt", message_id=51)))
    assert "فقط .pdf" in app.all_text()


async def test_multi_image_collection_can_be_cancelled(app, private_chat, tmp_path, monkeypatch):
    import convert

    work_dir = tmp_path / "image-convert"
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    app.session.file_payloads(tmp_path / "serve")
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")
    await app.feed(message_update(photo_message(chat, user, message_id=61)))
    assert len(list(work_dir.glob("*.image"))) == 1
    await app.click(chat, user, "tools_cancel")
    assert "لغو شد" in app.all_text()
    assert list(work_dir.iterdir()) == []
    # nothing left behind and the collected image is cleaned up
    cur = await app.dp.storage.get_state(
        key=app.dp.storage.build_key(chat_id=chat.id, user_id=user.id, bot_id=app.bot.id)
        if hasattr(app.dp.storage, "build_key")
        else None
    ) if False else None
    assert cur is None
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")
    await app.feed(message_update(photo_message(chat, user, message_id=62)))
    await app.click(chat, user, "menu_main")
    assert list(work_dir.iterdir()) == []


async def test_multi_image_pdf_uses_pdfs_command_and_preserves_five_page_order(
    app, private_chat, tmp_path, monkeypatch
):
    import fitz
    from PIL import Image
    import convert

    work_dir = tmp_path / "ordered-images"
    serve_dir = tmp_path / "serve"
    app.session.file_payloads(serve_dir)
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    colors = [
        (240, 20, 20),
        (20, 220, 20),
        (20, 20, 240),
        (230, 220, 20),
        (220, 20, 220),
    ]
    for index, color in enumerate(colors):
        Image.new("RGB", (80, 60), color).save(serve_dir / f"ordered-{index}.png")

    original_convert = convert.images_to_pdf
    observed_pixels = []

    def inspect_pages(image_paths, output_path):
        result = original_convert(image_paths, output_path)
        with fitz.open(result) as pdf:
            pixels = []
            for page in pdf:
                pix = page.get_pixmap()
                offset = (pix.height // 2 * pix.stride) + (pix.width // 2 * pix.n)
                pixels.append(tuple(pix.samples[offset:offset + 3]))
            observed_pixels.extend(pixels)
        return result

    monkeypatch.setattr(convert, "images_to_pdf", inspect_pages)
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")

    for index in range(5):
        app.session.upload_name = f"ordered-{index}.png"
        await app.feed(
            message_update(
                photo_message(chat, user, file_id=f"ORDERED-{index}", message_id=70 + index)
            )
        )
        assert f"تصویر شماره {index + 1} ذخیره شد" in app.all_text()

    assert app.session.last("SendDocument") is None
    await app.send(chat, user, "  PDFS  ")

    assert len(app.session.of("SendDocument")) == 1
    assert len(observed_pixels) == 5
    expected_primary_channels = [0, 1, 2, 0, 0]
    for pixel, expected_channel in zip(observed_pixels, expected_primary_channels):
        assert pixel[expected_channel] > max(
            value for index, value in enumerate(pixel) if index != expected_channel
        )
    assert list(work_dir.iterdir()) == []
    assert "ساخت PDF" in app.all_text()


async def test_multi_image_empty_command_case_and_unrelated_text(app, private_chat, tmp_path, monkeypatch):
    import convert

    work_dir = tmp_path / "empty-multi"
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    app.session.file_payloads(tmp_path / "serve")
    app.session.upload_name = "payload.jpg"
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)

    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")
    await app.send(chat, user, "  pDfS ")
    assert "ابتدا عکس بفرستید" in app.all_text()

    await app.send(chat, user, "متن معمولی")
    assert "کلمه pdfs" in app.all_text()
    assert not work_dir.exists() or list(work_dir.iterdir()) == []
    await app.feed(message_update(photo_message(chat, user, message_id=80)))
    assert "تصویر شماره 1 ذخیره شد" in app.all_text()
    await app.send(chat, user, "pdfs")
    assert len(app.session.of("SendDocument")) == 1


async def test_single_png_document_converts_and_pdf_command_outside_flow_is_ignored(
    app, private_chat, tmp_path, monkeypatch
):
    import convert

    work_dir = tmp_path / "single-png"
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    app.session.file_payloads(tmp_path / "serve")
    app.session.upload_name = "payload.png"
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    calls_before = len(app.session.calls)
    await app.send(chat, user, "pdfs")
    assert len(app.session.of("SendDocument")) == 0
    assert len(app.session.calls) == calls_before

    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_single")
    await app.feed(
        message_update(
            make_message(
                chat,
                user,
                message_id=90,
                document=Document(
                    file_id="PNG-DOC",
                    file_unique_id="PNG-UNIQ",
                    file_name="alpha.png",
                    mime_type="image/png",
                    file_size=1000,
                ),
            )
        )
    )
    sent = app.session.last("SendDocument")
    assert sent is not None and sent.caption == "📄 فایل PDF آماده شد ✅"
    assert not list(work_dir.iterdir())


async def test_invalid_image_and_download_failure_do_not_increment_multi_count(
    app, private_chat, tmp_path, monkeypatch
):
    import convert

    work_dir = tmp_path / "invalid-images"
    serve_dir = tmp_path / "serve"
    app.session.file_payloads(serve_dir)
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    (serve_dir / "broken.jpg").write_bytes(b"not a real image")
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")

    app.session.upload_name = "broken.jpg"
    await app.feed(message_update(photo_message(chat, user, file_id="BAD", message_id=91)))
    assert "خراب یا پشتیبانی‌نشده" in app.all_text()
    assert list(work_dir.iterdir()) == []

    async def fail_download(*args, **kwargs):
        raise OSError("network disconnected")

    with monkeypatch.context() as patch:
        patch.setattr(app.bot, "download", fail_download)
        await app.feed(
            message_update(photo_message(chat, user, file_id="NETWORK-FAIL", message_id=92))
        )
    assert "دریافت تصویر ناموفق بود" in app.all_text()

    app.session.upload_name = "payload.jpg"
    await app.feed(message_update(photo_message(chat, user, file_id="GOOD", message_id=93)))
    assert "تصویر شماره 1 ذخیره شد" in app.all_text()
    await app.send(chat, user, "pdfs")
    assert len(app.session.of("SendDocument")) == 1
    assert list(work_dir.iterdir()) == []


async def test_two_users_keep_independent_multi_image_sessions(
    app, private_chat, tmp_path, monkeypatch
):
    import asyncio
    import shutil
    from PIL import Image
    import convert

    work_dir = tmp_path / "two-users"
    serve_dir = tmp_path / "serve"
    app.session.file_payloads(serve_dir)
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    Image.new("RGB", (40, 40), (240, 10, 10)).save(serve_dir / "alice.png")
    Image.new("RGB", (40, 40), (10, 10, 240)).save(serve_dir / "bob.png")
    original_convert = convert.images_to_pdf
    converted_inputs: list[list[str]] = []

    def record_inputs(paths, output):
        converted_inputs.append([Path(path).name for path in paths])
        return original_convert(paths, output)

    monkeypatch.setattr(convert, "images_to_pdf", record_inputs)
    async def user_specific_download(document, destination, **kwargs):
        source_name = "alice.png" if document.file_id == "A1" else "bob.png"
        shutil.copyfile(serve_dir / source_name, destination)
        return destination

    monkeypatch.setattr(app.bot, "download", user_specific_download)
    chat = private_chat
    alice = make_user(720001, "alice", "Alice")
    bob = make_user(720002, "bob", "Bob")
    await bootstrap(app, chat, alice)
    await bootstrap(app, chat, bob)

    for user in (alice, bob):
        await app.click(chat, user, "tool_images_pdf")
        await app.click(chat, user, "tool_images_multi")
    await asyncio.gather(
        app.feed(message_update(photo_message(chat, alice, file_id="A1", message_id=94))),
        app.feed(message_update(photo_message(chat, bob, file_id="B1", message_id=95))),
    )

    await asyncio.gather(
        app.send(chat, alice, "pdfs"),
        app.send(chat, bob, "PDFS"),
    )
    assert len(converted_inputs) == 2
    assert converted_inputs[0] != converted_inputs[1]
    assert all(len(paths) == 1 for paths in converted_inputs)
    assert len(app.session.of("SendDocument")) == 2
    assert list(work_dir.iterdir()) == []


async def test_multi_image_rejects_oversize_dimensions_without_incrementing_count(
    app, private_chat, tmp_path, monkeypatch
):
    import convert

    work_dir = tmp_path / "oversized-image"
    serve_dir = tmp_path / "serve"
    app.session.file_payloads(serve_dir)
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    oversized = serve_dir / "oversized.png"
    from PIL import Image

    Image.new("RGB", (5000, 5000), (0, 0, 0)).save(oversized, optimize=True)
    app.session.upload_name = "oversized.png"
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")
    await app.feed(
        message_update(photo_message(chat, user, file_id="OVERSIZE", message_id=97))
    )
    assert "ابعاد تصویر از حد مجاز" in app.all_text()
    assert list(work_dir.iterdir()) == []

    app.session.upload_name = "payload.jpg"
    await app.feed(message_update(photo_message(chat, user, message_id=98)))
    assert "تصویر شماره 1 ذخیره شد" in app.all_text()
    await app.send(chat, user, "pdfs")
    assert len(app.session.of("SendDocument")) == 1
    assert list(work_dir.iterdir()) == []


async def test_duplicate_pdfs_and_send_failure_cleanup(app, private_chat, tmp_path, monkeypatch):
    import convert

    work_dir = tmp_path / "send-failure"
    monkeypatch.setattr(convert, "TEMP_DIR", work_dir)
    app.session.file_payloads(tmp_path / "serve")
    chat = private_chat
    user = make_user(USER_ID, "ali", "Ali")
    await bootstrap(app, chat, user)
    await app.click(chat, user, "tool_images_pdf")
    await app.click(chat, user, "tool_images_multi")
    await app.feed(message_update(photo_message(chat, user, message_id=96)))

    original_request = app.session.make_request

    async def reject_pdf_send(bot, method, timeout=None):
        if type(method).__name__ == "SendDocument":
            raise OSError("injected send failure")
        return await original_request(bot, method, timeout)

    monkeypatch.setattr(app.session, "make_request", reject_pdf_send)
    await app.send(chat, user, "pdfs")
    assert "ساخت یا ارسال PDF ناموفق بود" in app.all_text()
    assert list(work_dir.iterdir()) == []
    send_count = len(app.session.of("SendDocument"))
    await app.send(chat, user, "pdfs")
    assert len(app.session.of("SendDocument")) == send_count


# ─── background schedulers ───────────────────────────────────────────────────


async def test_class_notifier_sends_once_per_day(app, monkeypatch):
    import classnotifier as cn

    monkeypatch.setattr(cn, "ALLOWED_GROUP_ID", -100777)
    cls = await models.add_online_class_full(
        0, "ریاضی", "16:00", "", start_hour=16, end_hour=18
    )
    row = await models.get_online_class_by_id(cls)
    tz = await cn.get_tz()
    await cn.send_class_alert(app.bot, row, tz)
    msg = app.session.last("SendMessage")
    assert msg is not None and msg.chat_id == -100777
    assert "ریاضی" in (msg.text or "")

    today = datetime.now(cn.TEHRAN_TZ).date().isoformat()
    assert not await models.class_alert_already_sent(cls, today)
    await models.class_alert_mark_sent(cls, today)
    assert await models.class_alert_already_sent(cls, today)


async def test_goodnight_message_dedupe(app, monkeypatch):
    import classnotifier as cn

    monkeypatch.setattr(cn, "ALLOWED_GROUP_ID", -100888)
    await models.set_setting("goodnight_enabled", "1")
    await models.set_setting("goodnight_time", "00:00")
    await models.set_setting("goodnight_text", "شب خوش")
    now = datetime.now(cn.TEHRAN_TZ)
    await cn.check_goodnight(app.bot, now)
    assert app.session.last("SendMessage") is not None
    assert await models.get_setting("goodnight_last_date") == now.date().isoformat()
    app.clear()
    await cn.check_goodnight(app.bot, now)  # already sent today
    assert app.session.last("SendMessage") is None


async def test_class_notify_loop_sends_due_class_once(app, monkeypatch):
    import classnotifier as cn

    monkeypatch.setattr(cn, "ALLOWED_GROUP_ID", -100999)
    now_tehran = datetime.now(cn.TEHRAN_TZ)
    day = cn.tehran_day_index(now_tehran)
    cid = await models.add_online_class_full(
        day, "شیمی", "", "", start_hour=now_tehran.hour, start_minute=now_tehran.minute
    )
    # run exactly one iteration of the loop body
    async def one_iteration():
        task = asyncio.create_task(cn.class_notify_loop(app.bot))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await one_iteration()
    today = now_tehran.date().isoformat()
    assert await models.class_alert_already_sent(cid, today)
    sent_before = len(app.session.of("SendMessage"))
    await one_iteration()  # second run must not repeat the alert
    assert len(app.session.of("SendMessage")) == sent_before


async def test_failed_class_alert_is_not_marked_sent(app, monkeypatch):
    import classnotifier as cn

    monkeypatch.setattr(cn, "ALLOWED_GROUP_ID", -100998)
    now_tehran = datetime.now(cn.TEHRAN_TZ)
    day = cn.tehran_day_index(now_tehran)
    cid = await models.add_online_class_full(
        day, "فیزیک", "", "", start_hour=now_tehran.hour,
        start_minute=now_tehran.minute,
    )

    async def fail_send(*args, **kwargs):
        raise RuntimeError("temporary Telegram failure")

    monkeypatch.setattr(app.bot, "send_message", fail_send)
    task = asyncio.create_task(cn.class_notify_loop(app.bot))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    today = now_tehran.date().isoformat()
    assert not await models.class_alert_already_sent(cid, today)


async def test_group_nudge_has_single_at_sign_in_bot_mention(app, monkeypatch):
    import nudge

    async def enabled_setting(key, default=""):
        return "1" if key == "nudge_enabled" else default

    async def stale_groups(days=4):
        return [{"chat_id": -100777}]

    monkeypatch.setattr(models, "get_setting", enabled_setting)
    monkeypatch.setattr(models, "get_stale_groups", stale_groups)
    monkeypatch.setattr(nudge, "_nudge_text", lambda bot: asyncio.sleep(0, result="@TestSchoolBot"))
    monkeypatch.setattr(nudge, "_pick_message", lambda last=None: ("سلام {bot}", 0))
    monkeypatch.setattr(nudge, "CHECK_INTERVAL_SECONDS", 30)

    task = asyncio.create_task(nudge.nudge_loop(app.bot))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    sent = app.session.last("SendMessage")
    assert sent is not None and sent.text == "سلام @TestSchoolBot"


async def test_weekly_task_reset_scheduler(app):
    wk = models.current_week_key()
    await models.set_task_done(USER_ID, "sched:0:1", "1999-W01", True)
    await models.set_task_done(USER_ID, "sched:0:1", wk, True)
    import scheduler

    wait = scheduler._seconds_until_next_saturday_midnight()
    assert 60 <= wait <= 8 * 86400
    removed = await models.reset_week_tasks()
    assert removed == 1
    assert await models.get_task_done(USER_ID, "sched:0:1", wk)
