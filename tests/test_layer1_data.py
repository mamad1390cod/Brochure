"""Layer 1: database, models, security primitives, permissions."""

from __future__ import annotations

import asyncio
import hashlib

import pytest

import models
import security
from permissions import (
    DEFAULT_ADMIN_PERMISSIONS,
    PERMISSIONS,
    check_permission,
    get_owner_ids,
    is_admin,
    is_owner,
)
from config import MAIN_ADMIN_ID


# ─── schema / migrations ─────────────────────────────────────────────────────


async def test_schema_creates_all_tables(app):
    from database import get_db

    db = await get_db()
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in await cur.fetchall()}
    await db.close()
    for expected in [
        "study_fields", "subjects", "chapters", "notes", "admins",
        "admin_permissions", "users", "allowed_users", "settings", "logs",
        "schedule_entries", "task_status", "task_done", "online_classes",
        "weekly_classes",
        "group_activity", "group_members", "usage_stats", "all_cooldowns",
        "class_alerts_sent", "convert_jobs", "task_categories", "tasks",
    ]:
        assert expected in tables, f"missing table {expected}"


def test_logging_redacts_bot_token_from_message_and_exception(monkeypatch):
    import logging
    import logger as logger_module

    secret = "987654:PRIVATE-TEST-TOKEN"
    monkeypatch.setenv("BOT_TOKEN", secret)
    redactor = logger_module._SecretRedactionFilter()
    try:
        raise RuntimeError(f"request failed for {secret}")
    except RuntimeError:
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "failure %s", (secret,), __import__("sys").exc_info()
        )

    assert redactor.filter(record)
    rendered = record.getMessage() + (record.exc_text or "")
    assert secret not in rendered
    assert "[REDACTED]" in rendered


async def test_wal_mode_enabled(app):
    from database import get_db

    db = await get_db()
    cur = await db.execute("PRAGMA journal_mode")
    mode = (await cur.fetchone())[0]
    await db.close()
    assert mode.lower() == "wal"


async def test_migrations_idempotent(app):
    from database import init_database

    await init_database()  # second run must not explode
    await init_database()


# ─── fields / subjects / chapters ────────────────────────────────────────────


async def test_field_crud_roundtrip(app):
    fid = await models.create_field("ریاضی")
    row = await models.get_field_by_id(fid)
    assert row["name"] == "ریاضی"
    await models.update_field(fid, "ریاضی ۱")
    assert (await models.get_field_by_id(fid))["name"] == "ریاضی ۱"
    await models.delete_field(fid)
    assert await models.get_fields() == []
    assert await models.get_field_by_id(fid) is not None  # soft delete keeps row


async def test_duplicate_field_name_raises_integrity_error(app):
    """Documents current behaviour: the UNIQUE(name) constraint is not handled."""
    await models.create_field("تجربی")
    with pytest.raises(Exception):
        await models.create_field("تجربی")


async def test_subject_and_chapter_cascade_names(app):
    fid = await models.create_field("ریاضی")
    sid = await models.create_subject(fid, "هندسه")
    cid = await models.create_chapter(sid, "فصل ۱")
    assert (await models.get_subject_by_id(sid))["name"] == "هندسه"
    assert (await models.get_chapter_by_id(cid))["name"] == "فصل ۱"
    assert len(await models.get_chapters_by_subject(sid)) == 1


async def test_duplicate_subject_in_same_field_rejected(app):
    fid = await models.create_field("ریاضی")
    await models.create_subject(fid, "هندسه")
    with pytest.raises(Exception):
        await models.create_subject(fid, "هندسه")


# ─── notes ───────────────────────────────────────────────────────────────────


_note_seq = {"n": 0}


async def _make_note(**over):
    _note_seq["n"] += 1
    n = _note_seq["n"]
    fid = await models.create_field(over.pop("field", f"ریاضی{n}"))
    sid = await models.create_subject(fid, over.pop("subject", f"هندسه{n}"))
    cid = await models.create_chapter(sid, over.pop("chapter", f"فصل {n}"))
    kwargs = dict(
        title="جزوه تست",
        description="توضیح",
        field_id=fid,
        subject_id=sid,
        chapter_id=cid,
        page_start=1,
        page_end=5,
        file_type="document",
        file_id="FILEID",
        file_unique_id="UNIQ",
        file_name="a.pdf",
        mime_type="application/pdf",
        file_size=1234,
        submitted_by=42,
        submitted_by_name="Ali",
        status="approved",
    )
    kwargs.update(over)
    nid = await models.create_note(**kwargs)
    return nid, fid, sid, cid


async def test_note_visibility_only_approved(app):
    nid_ok, fid, sid, cid = await _make_note(title="approved", status="approved")
    nid_pending, *_ = await _make_note(title="pending", status="pending")
    approved = await models.get_approved_notes()
    assert [n["id"] for n in approved] == [nid_ok]
    assert [n["id"] for n in await models.get_pending_notes()] == [nid_pending]


async def test_soft_deleted_note_disappears(app):
    nid, *_ = await _make_note()
    await models.delete_note(nid)
    assert await models.get_approved_notes() == []
    assert await models.get_note_by_id(nid) is not None


async def test_approve_and_reject(app):
    nid, *_ = await _make_note(status="pending")
    await models.approve_note(nid, reviewed_by=1)
    assert (await models.get_note_by_id(nid))["status"] == "approved"
    await models.reject_note(nid, reviewed_by=1, review_note="no")
    row = await models.get_note_by_id(nid)
    assert row["status"] == "rejected" and row["review_note"] == "no"


async def test_pending_note_can_only_be_reviewed_once(app):
    import asyncio

    nid, *_ = await _make_note(status="pending")
    results = await asyncio.gather(
        models.review_pending_note(nid, 1, "approved"),
        models.review_pending_note(nid, 2, "rejected"),
    )
    assert sum(results) == 1
    assert (await models.get_note_by_id(nid))["status"] in {"approved", "rejected"}


async def test_search_notes_matches_joined_names(app):
    await _make_note(title="هندسه فصل یک", field="ریاضی", subject="هندسه")
    assert await models.search_notes("هندسه")
    assert await models.search_notes("ریاضی")
    assert not await models.search_notes("زیست")


async def test_search_notes_wildcards_are_literal(app):
    """A '%' in the query must not act as a wildcard."""
    await _make_note(title="abc")
    assert await models.search_notes("%") == []
    assert await models.search_notes("_") == []


async def test_count_notes_filters(app):
    await _make_note(status="approved")
    await _make_note(status="pending")
    assert await models.count_notes() == 2
    assert await models.count_notes("approved") == 1
    assert await models.count_notes("pending") == 1


async def test_update_note_ignores_empty_kwargs(app):
    nid, *_ = await _make_note()
    await models.update_note(nid)  # must not raise
    assert (await models.get_note_by_id(nid))["title"] == "جزوه تست"


async def test_delete_notes_bulk(app):
    a, *_ = await _make_note()
    b, *_ = await _make_note()
    await models.delete_notes_bulk([])
    await models.delete_notes_bulk([a, b])
    assert await models.get_approved_notes() == []


# ─── users / allowed users / settings / logs ─────────────────────────────────


async def test_upsert_user_updates_profile(app):
    await models.upsert_user(5, "old", "Old Name")
    await models.upsert_user(5, "new", "New Name")
    assert (await models.get_user(5))["username"] == "new"


async def test_allowed_user_toggle_and_remove(app):
    await models.add_allowed_user(7, "u7", "Seven", added_by=1)
    assert await models.is_allowed_user(7)
    await models.toggle_allowed_user(7, False)
    assert not await models.is_allowed_user(7)
    await models.remove_allowed_user(7)
    assert await models.get_allowed_users() == []


async def test_settings_default_and_roundtrip(app):
    assert await models.get_setting("missing", "fallback") == "fallback"
    await models.set_setting("timezone", "Asia/Tehran")
    assert await models.get_setting("timezone") == "Asia/Tehran"
    await models.set_setting("timezone", "Asia/Dubai")
    assert await models.get_setting("timezone") == "Asia/Dubai"


async def test_logs_pagination(app):
    for i in range(30):
        await models.add_log(1, "u", "act", f"row {i}")
    assert len(await models.get_logs(limit=10)) == 10
    assert len(await models.get_logs(limit=10, offset=25)) == 5


# ─── weekly task state ───────────────────────────────────────────────────────


async def test_week_key_is_saturday_based(app):
    key = models.current_week_key()
    assert "-W" in key
    # Monday must belong to the *previous* Saturday's week
    # (verified structurally: key changes only when the Saturday rolls over)


async def test_task_done_roundtrip_and_week_isolation(app):
    wk = models.current_week_key()
    assert not await models.get_task_done(1, "sched:0:1", wk)
    await models.set_task_done(1, "sched:0:1", wk, True)
    assert await models.get_task_done(1, "sched:0:1", wk)
    assert not await models.get_task_done(1, "sched:0:1", "1999-W01")
    await models.set_task_done(1, "sched:0:1", wk, False)
    assert not await models.get_task_done(1, "sched:0:1", wk)


async def test_reset_week_tasks_keeps_current_week(app):
    wk = models.current_week_key()
    await models.set_task_done(1, "sched:0:1", wk, True)
    await models.set_task_done(1, "sched:0:1", "1999-W01", True)
    await models.set_task_status(1, 0, "1999-W01", True)
    removed = await models.reset_week_tasks()
    assert removed == 2
    assert await models.get_task_done(1, "sched:0:1", wk)


async def test_day_done_status_counts(app):
    await models.set_schedule_cell(None, 0, 1, "math")
    await models.set_schedule_cell(None, 0, 2, "physics")
    wk = models.current_week_key()
    assert await models.get_day_done_status(1, 0, wk) == (0, 2)
    await models.set_task_done(1, "sched:0:1", wk, True)
    assert await models.get_day_done_status(1, 0, wk) == (1, 2)


async def test_day_status_emoji():
    assert models.day_status_emoji(0, 0) == "⚪"
    assert models.day_status_emoji(0, 3) == "🔴"
    assert models.day_status_emoji(1, 3) == "🟡"
    assert models.day_status_emoji(3, 3) == "🟢"


async def test_schedule_cell_upsert(app):
    await models.set_schedule_cell(None, 1, 1, "ریاضی")
    await models.set_schedule_cell(None, 1, 1, "فیزیک")
    sched = await models.get_schedule()
    assert sched[(1, 1)] == "فیزیک"
    await models.clear_schedule()
    assert await models.get_schedule() == {}


async def test_get_day_tasks_skips_empty(app):
    await models.set_schedule_cell(None, 2, 1, "a")
    await models.set_schedule_cell(None, 2, 2, "")
    await models.set_schedule_cell(None, 2, 3, "c")
    assert await models.get_day_tasks(None, 2) == ["a", "c"]


# ─── online classes ──────────────────────────────────────────────────────────


async def test_online_class_full_crud(app):
    cid = await models.add_online_class_full(
        0, "ریاضی", "16:00 تا 18:00", "https://x.test", start_hour=16, end_hour=18
    )
    cls = await models.get_online_class_by_id(cid)
    assert cls["title"] == "ریاضی" and cls["notify_enabled"] == 1
    await models.update_online_class(cid, title="فیزیک")
    assert (await models.get_online_class_by_id(cid))["title"] == "فیزیک"
    await models.set_class_notify(cid, False)
    assert (await models.get_online_class_by_id(cid))["notify_enabled"] == 0
    await models.update_online_class(cid, start_hour=None, end_hour=None)
    cleared = await models.get_online_class_by_id(cid)
    assert cleared["start_hour"] is None and cleared["end_hour"] is None
    await models.delete_online_class(cid)
    assert await models.get_online_class_by_id(cid) is None


async def test_class_alert_dedupe(app):
    assert not await models.class_alert_already_sent(1, "2026-10-09")
    await models.class_alert_mark_sent(1, "2026-10-09")
    assert await models.class_alert_already_sent(1, "2026-10-09")
    await models.class_alert_mark_sent(1, "2026-10-09")  # idempotent


# ─── /all cooldown ───────────────────────────────────────────────────────────


async def test_all_cooldown(app):
    assert await models.all_cooldown_remaining(-100) == 0
    await models.all_cooldown_set(-100)
    remaining = await models.all_cooldown_remaining(-100, 60)
    assert 0 < remaining <= 60
    assert await models.all_cooldown_remaining(-100, 0) == 0


async def test_all_cooldown_claim_is_atomic(app):
    claims = await asyncio.gather(
        *(models.claim_all_cooldown(-101) for _ in range(10))
    )
    assert sum(claimed for claimed, _ in claims) == 1
    assert all(remaining > 0 for claimed, remaining in claims if not claimed)


# ─── tasks (تکالیف) ──────────────────────────────────────────────────────────


async def test_task_category_and_tasks(app):
    cat = await models.create_task_category("ریاضی")
    await models.create_task(cat, "صفحه ۲۲", "حل تمرینها", created_by=1)
    grouped = await models.get_all_tasks_grouped()
    assert "ریاضی" in grouped and len(grouped["ریاضی"]) == 1
    cats = await models.get_task_categories()
    assert cats[0]["task_count"] == 1
    removed = await models.delete_task_category(cat)
    assert removed == 1
    assert await models.get_all_tasks_grouped() == {}


async def test_duplicate_task_category_rejected(app):
    await models.create_task_category("ریاضی")
    with pytest.raises(Exception):
        await models.create_task_category("ریاضی")


async def test_soft_delete_task(app):
    cat = await models.create_task_category("فیزیک")
    tid = await models.create_task(cat, "t", "d", created_by=1)
    await models.delete_task(tid)
    assert await models.get_all_tasks_grouped() == {}
    assert (await models.get_task_by_id(tid))["is_active"] == 0


async def test_task_metadata_and_expired_deadline_are_removed_from_active_lists(app):
    from datetime import datetime, timedelta, timezone

    field_id = await models.create_field("علوم")
    subject_id = await models.create_subject(field_id, "زیست")
    category_id = await models.create_task_category("علوم / زیست")
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(
        tzinfo=None
    ).isoformat(sep=" ", timespec="seconds")
    task_id = await models.create_task(
        category_id,
        "تکلیف منقضی",
        "شرح",
        created_by=1,
        field_id=field_id,
        subject_id=subject_id,
        day_index=4,
        due_at=due_at,
        file_id="TASK_PHOTO",
    )

    assert await models.get_active_tasks() == []
    task = await models.get_task_by_id(task_id)
    assert task["is_active"] == 0
    assert (task["field_id"], task["subject_id"], task["day_index"]) == (
        field_id, subject_id, 4
    )
    assert task["file_id"] == "TASK_PHOTO"


async def test_legacy_task_schema_migrates_deadline_columns(tmp_path, monkeypatch):
    import sqlite3
    import database

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE task_categories "
            "(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT)"
        )
        db.execute(
            """CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                category_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                details TEXT DEFAULT '',
                created_by INTEGER,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )"""
        )
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)

    await database.init_database()
    db = await database.get_db()
    try:
        cursor = await db.execute("PRAGMA table_info(tasks)")
        columns = {row["name"] for row in await cursor.fetchall()}
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_tasks_active_deadline'"
        )
        index_exists = await cursor.fetchone()
    finally:
        await db.close()
    assert {"field_id", "subject_id", "day_index", "due_at", "file_id"} <= columns
    assert index_exists is not None


def test_jalali_task_deadline_parses_and_formats():
    import pytest
    import tasks

    stored = tasks._parse_jalali_deadline("۱۴۹۹/۰۱/۰۱ ۲۳:۵۹")
    assert tasks._format_deadline(stored) == "1499/01/01 ساعت 23:59"
    with pytest.raises(ValueError, match="آینده"):
        tasks._parse_jalali_deadline("۱۴۰۰/۰۱/۰۱ ۰۰:۰۰")
    with pytest.raises(ValueError, match="۱۴۰۵/۰۷/۲۵"):
        tasks._parse_jalali_deadline("تاریخ اشتباه")


# ─── group stats ─────────────────────────────────────────────────────────────


async def test_group_members_and_top_users(app):
    await models.upsert_group_member(-100, 1, "a", "A")
    await models.upsert_group_member(-100, 2, "", "B")
    assert len(await models.get_group_members(-100)) == 2
    await models.bump_usage(1, "a", "A")
    await models.bump_usage(1, "a", "A")
    await models.bump_usage(2, "", "B")
    top = await models.get_top_users(2)
    assert top[0]["user_id"] == 1 and top[0]["uses"] == 2


async def test_stats_overview_keys(app):
    stats = await models.get_stats_overview()
    for key in [
        "users_total", "group_members", "admins_total", "notes_total",
        "notes_approved", "notes_pending", "fields_total", "subjects_total",
        "chapters_total", "tasks_total", "online_classes", "conversions",
        "logs_total", "usage_total",
    ]:
        assert key in stats


async def test_stale_group_detection(app):
    await models.touch_group_activity(-100, "G")
    assert await models.get_stale_groups(4) == []
    await models.mark_group_nudged(-100)


# ─── security ────────────────────────────────────────────────────────────────


def test_password_hash_is_salted_and_verifies():
    h1 = security.hash_password("Parham11")
    h2 = security.hash_password("Parham11")
    assert h1 != h2
    assert h1.startswith("pbkdf2_sha256$")
    assert security.verify_password("Parham11", h1)
    assert security.verify_password("PARHAM11", h1)  # case-insensitive by design
    assert security.verify_password("  parham11 ", h1)
    assert not security.verify_password("wrong", h1)
    assert not security.verify_password("Parham11", "no-dollar")


def test_legacy_password_hash_verifies_and_requires_upgrade():
    salt = "legacy-salt"
    digest = hashlib.sha256(
        f"{salt}{'parham11'}".encode("utf-8")
    ).hexdigest()
    legacy_hash = f"{salt}${digest}"

    assert security.verify_password("PARHAM11", legacy_hash)
    assert security.password_hash_needs_upgrade(legacy_hash)
    assert not security.password_hash_needs_upgrade(security.hash_password("x"))


def test_password_hash_of_empty_string_verifies():
    h = security.hash_password("")
    assert security.verify_password("", h)


def test_rate_limiter_lockout_and_reset():
    rl = security.LoginRateLimiter(max_attempts=3, lockout_minutes=15)
    assert not rl.is_locked(1)
    rl.record_attempt(1)
    rl.record_attempt(1)
    assert not rl.is_locked(1)
    rl.record_attempt(1)
    assert rl.is_locked(1)
    assert rl.get_remaining_time(1) > 0
    rl.reset(1)
    assert not rl.is_locked(1)
    assert rl.get_remaining_time(1) == 0


def test_rate_limiter_expiry(monkeypatch):
    rl = security.LoginRateLimiter(max_attempts=1, lockout_minutes=1)
    rl.record_attempt(9)
    assert rl.is_locked(9)
    monkeypatch.setattr(security.time, "time", lambda: 1e12)
    assert not rl.is_locked(9)


def test_admin_session_sliding_expiry(monkeypatch):
    sm = security.AdminSessionManager(timeout_seconds=300)
    now = {"t": 1000.0}
    monkeypatch.setattr(security.time, "time", lambda: now["t"])
    assert not sm.is_authenticated(1)
    sm.login(1)
    assert sm.is_authenticated(1)
    now["t"] += 299
    sm.refresh(1)
    now["t"] += 299
    assert sm.is_authenticated(1)  # sliding refresh kept it alive
    now["t"] += 301
    assert not sm.is_authenticated(1)
    sm.logout(1)


def test_admin_session_logout():
    sm = security.AdminSessionManager()
    sm.login(3)
    sm.logout(3)
    assert not sm.is_authenticated(3)


# ─── permissions ─────────────────────────────────────────────────────────────


async def test_owner_is_the_configured_main_admin(app):
    assert await is_owner(MAIN_ADMIN_ID)
    assert await is_admin(MAIN_ADMIN_ID)
    assert await check_permission(MAIN_ADMIN_ID, "anything_at_all")
    assert not await is_owner(999)


async def test_permission_grants_are_live(app):
    admin_id = await models.create_admin(500, "a", "Admin A", security.hash_password("x"))
    await models.set_admin_permissions(admin_id, DEFAULT_ADMIN_PERMISSIONS)
    assert await check_permission(500, "view_notes")
    assert not await check_permission(500, "manage_admins")
    await models.set_admin_permissions(admin_id, list(PERMISSIONS.keys()))
    assert await check_permission(500, "manage_admins")
    # deactivating the admin revokes everything immediately
    await models.toggle_admin_active(admin_id, False)
    assert not await is_admin(500)
    assert not await check_permission(500, "view_notes")


async def test_owner_flag_in_db_grants_owner(app):
    admin_id = await models.create_admin(501, "o", "Owner 2", security.hash_password("x"))
    await models.set_admin_owner(admin_id, True)
    assert await is_owner(501)
    owners = await get_owner_ids()
    assert MAIN_ADMIN_ID in owners and 501 in owners


async def test_unknown_user_has_no_permissions(app):
    assert not await is_admin(4242)
    assert not await check_permission(4242, "view_panel")


# ─── conversion helpers ──────────────────────────────────────────────────────


def test_safe_name_sanitises():
    import convert

    # path separators are stripped, leading dots trimmed, no traversal possible
    assert convert.safe_name("../../etc/passwd") == "etcpasswd"
    assert "/" not in convert.safe_name("a/b")
    assert convert.safe_name("") == "converted"
    assert len(convert.safe_name("x" * 500)) == 120


def test_images_to_pdf(tmp_path):
    from PIL import Image
    import convert

    paths = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0)]):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (60, 40), color).save(p)
        paths.append(p)
    out = tmp_path / "out.pdf"
    convert.images_to_pdf(paths, out)
    assert out.exists() and out.stat().st_size > 0


def test_images_to_pdf_handles_formats_transparency_and_one_page_per_image(tmp_path):
    from PIL import Image
    import fitz
    import convert

    paths = []
    Image.new("RGB", (90, 45), (240, 10, 10)).save(tmp_path / "one.jpg")
    Image.new("RGBA", (60, 60), (10, 220, 10, 255)).save(tmp_path / "two.png")
    Image.new("RGB", (45, 90), (10, 10, 240)).save(tmp_path / "three.webp")
    Image.new("RGBA", (30, 30), (255, 0, 0, 0)).save(tmp_path / "transparent.png")
    paths.extend(
        [
            tmp_path / "one.jpg",
            tmp_path / "two.png",
            tmp_path / "three.webp",
            tmp_path / "transparent.png",
        ]
    )

    output = tmp_path / "formats.pdf"
    convert.images_to_pdf(paths, output)

    with fitz.open(output) as pdf:
        assert len(pdf) == 4
        ratios = [round(page.rect.width / page.rect.height, 1) for page in pdf]
        assert ratios == [2.0, 1.0, 0.5, 1.0]

        transparent_page = pdf[3]
        pix = transparent_page.get_pixmap()
        offset = (pix.height // 2 * pix.stride) + (pix.width // 2 * pix.n)
        assert tuple(pix.samples[offset:offset + 3]) == (255, 255, 255)

    two_page_output = tmp_path / "two-pages.pdf"
    convert.images_to_pdf(paths[:2], two_page_output)
    with fitz.open(two_page_output) as pdf:
        assert len(pdf) == 2


def test_images_to_pdf_rejects_corrupt_image_and_removes_partial_output(tmp_path):
    import convert

    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"this is not an image")
    output = tmp_path / "corrupt.pdf"

    with pytest.raises(ValueError, match="Invalid or unsupported image"):
        convert.images_to_pdf([corrupt], output)

    assert not output.exists()


def test_images_to_pdf_rejects_empty(tmp_path):
    import convert

    with pytest.raises(ValueError):
        convert.images_to_pdf([], tmp_path / "empty.pdf")


def test_pdf_to_word_roundtrip(tmp_path):
    import fitz
    import convert

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello School Notes")
    pdf = tmp_path / "in.pdf"
    doc.save(str(pdf))
    doc.close()

    out = tmp_path / "out.docx"
    convert.pdf_to_word(pdf, out)
    from docx import Document

    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "Hello School Notes" in text


def test_word_to_pdf_reports_missing_libreoffice(tmp_path, monkeypatch):
    import convert

    monkeypatch.setattr(convert, "_libreoffice_bin", lambda: None)
    with pytest.raises(RuntimeError):
        convert.word_to_pdf(tmp_path / "x.docx", tmp_path)
