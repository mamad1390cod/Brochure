"""
Data models for Bot-File-School.
Provides async database operations for all entities.
"""

from __future__ import annotations
from typing import Optional, List
import aiosqlite
from database import get_db


def _escape_like(keyword: str) -> str:
    """Escape LIKE wildcards so user keywords match literally."""
    return (
        keyword.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# ─── Study Field ─────────────────────────────────────────────────────────────

async def create_field(name: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO study_fields (name) VALUES (?)", (name,)
    )
    await db.commit()
    field_id = cursor.lastrowid
    await db.close()
    return field_id


async def get_fields(active_only: bool = True) -> List[aiosqlite.Row]:
    db = await get_db()
    if active_only:
        rows = await db.execute_fetchall(
            "SELECT * FROM study_fields WHERE is_active = 1 ORDER BY name"
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM study_fields ORDER BY name"
        )
    await db.close()
    return rows


async def get_field_by_id(field_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM study_fields WHERE id = ?", (field_id,)
    )
    await db.close()
    return row[0] if row else None


async def update_field(field_id: int, name: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE study_fields SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (name, field_id),
    )
    await db.commit()
    await db.close()


async def delete_field(field_id: int) -> None:
    """Soft delete a field."""
    db = await get_db()
    await db.execute(
        "UPDATE study_fields SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (field_id,),
    )
    await db.commit()
    await db.close()


# ─── Subject ─────────────────────────────────────────────────────────────────

async def create_subject(field_id: int, name: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO subjects (field_id, name) VALUES (?, ?)", (field_id, name)
    )
    await db.commit()
    subject_id = cursor.lastrowid
    await db.close()
    return subject_id


async def get_subjects_by_field(field_id: int, active_only: bool = True) -> List[aiosqlite.Row]:
    db = await get_db()
    if active_only:
        rows = await db.execute_fetchall(
            "SELECT * FROM subjects WHERE field_id = ? AND is_active = 1 ORDER BY name",
            (field_id,),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM subjects WHERE field_id = ? ORDER BY name",
            (field_id,),
        )
    await db.close()
    return rows


async def get_subject_by_id(subject_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM subjects WHERE id = ?", (subject_id,)
    )
    await db.close()
    return row[0] if row else None


async def update_subject(subject_id: int, name: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE subjects SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (name, subject_id),
    )
    await db.commit()
    await db.close()


async def delete_subject(subject_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE subjects SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (subject_id,),
    )
    await db.commit()
    await db.close()


# ─── Chapter ─────────────────────────────────────────────────────────────────

async def create_chapter(subject_id: int, name: str, sort_order: int = 0) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO chapters (subject_id, name, sort_order) VALUES (?, ?, ?)",
        (subject_id, name, sort_order),
    )
    await db.commit()
    chapter_id = cursor.lastrowid
    await db.close()
    return chapter_id


async def get_chapters_by_subject(subject_id: int, active_only: bool = True) -> List[aiosqlite.Row]:
    db = await get_db()
    if active_only:
        rows = await db.execute_fetchall(
            "SELECT * FROM chapters WHERE subject_id = ? AND is_active = 1 ORDER BY sort_order, name",
            (subject_id,),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM chapters WHERE subject_id = ? ORDER BY sort_order, name",
            (subject_id,),
        )
    await db.close()
    return rows


async def get_chapter_by_id(chapter_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
    )
    await db.close()
    return row[0] if row else None


async def update_chapter(chapter_id: int, name: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE chapters SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (name, chapter_id),
    )
    await db.commit()
    await db.close()


async def delete_chapter(chapter_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE chapters SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (chapter_id,),
    )
    await db.commit()
    await db.close()


# ─── Note ────────────────────────────────────────────────────────────────────

async def create_note(
    title: str,
    description: str,
    field_id: int,
    subject_id: int,
    chapter_id: Optional[int],
    page_start: Optional[int],
    page_end: Optional[int],
    file_type: str,
    file_id: str,
    file_unique_id: str,
    file_name: str,
    mime_type: str,
    file_size: int,
    submitted_by: int,
    submitted_by_name: str,
    status: str = "pending",
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO notes
        (title, description, field_id, subject_id, chapter_id,
         page_start, page_end, file_type, file_id, file_unique_id,
         file_name, mime_type, file_size, submitted_by, submitted_by_name, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, field_id, subject_id, chapter_id,
         page_start, page_end, file_type, file_id, file_unique_id,
         file_name, mime_type, file_size, submitted_by, submitted_by_name, status),
    )
    await db.commit()
    note_id = cursor.lastrowid
    await db.close()
    return note_id


async def get_note_by_id(note_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM notes WHERE id = ?", (note_id,)
    )
    await db.close()
    return row[0] if row else None


async def get_approved_notes(
    field_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[aiosqlite.Row]:
    db = await get_db()
    query = "SELECT * FROM notes WHERE status = 'approved' AND is_active = 1"
    params: list = []
    if field_id:
        query += " AND field_id = ?"
        params.append(field_id)
    if subject_id:
        query += " AND subject_id = ?"
        params.append(subject_id)
    if chapter_id:
        query += " AND chapter_id = ?"
        params.append(chapter_id)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = await db.execute_fetchall(query, params)
    await db.close()
    return rows


async def search_notes(keyword: str, limit: int = 10) -> List[aiosqlite.Row]:
    """Search approved notes by keyword in title or description."""
    db = await get_db()
    like = f"%{_escape_like(keyword)}%"
    rows = await db.execute_fetchall(
        """SELECT n.*, sf.name as field_name, s.name as subject_name, c.name as chapter_name
        FROM notes n
        LEFT JOIN study_fields sf ON n.field_id = sf.id
        LEFT JOIN subjects s ON n.subject_id = s.id
        LEFT JOIN chapters c ON n.chapter_id = c.id
        WHERE n.status = 'approved' AND n.is_active = 1
        AND (n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\' OR sf.name LIKE ? ESCAPE '\\' OR s.name LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\')
        ORDER BY n.created_at DESC LIMIT ?""",
        (like, like, like, like, like, limit),
    )
    await db.close()
    return rows


async def get_recent_notes(limit: int = 10) -> List[aiosqlite.Row]:
    """Get the most recent approved notes with joined names."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT n.*, sf.name as field_name, s.name as subject_name, c.name as chapter_name
        FROM notes n
        LEFT JOIN study_fields sf ON n.field_id = sf.id
        LEFT JOIN subjects s ON n.subject_id = s.id
        LEFT JOIN chapters c ON n.chapter_id = c.id
        WHERE n.status = 'approved' AND n.is_active = 1
        ORDER BY n.created_at DESC LIMIT ?""",
        (limit,),
    )
    await db.close()
    return rows


async def update_note(note_id: int, **kwargs) -> None:
    """Update note fields dynamically."""
    if not kwargs:
        return
    db = await get_db()
    set_parts = []
    values = []
    for key, value in kwargs.items():
        set_parts.append(f"{key} = ?")
        values.append(value)
    values.append(note_id)
    query = f"UPDATE notes SET {', '.join(set_parts)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
    await db.execute(query, values)
    await db.commit()
    await db.close()


async def delete_note(note_id: int) -> None:
    """Soft delete a note."""
    await update_note(note_id, is_active=0)


async def delete_notes_bulk(note_ids: list) -> None:
    """Soft delete multiple notes."""
    if not note_ids:
        return
    db = await get_db()
    placeholders = ",".join("?" for _ in note_ids)
    await db.execute(
        f"UPDATE notes SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        note_ids,
    )
    await db.commit()
    await db.close()


async def get_pending_notes(limit: int = 20) -> List[aiosqlite.Row]:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT n.*, sf.name as field_name, s.name as subject_name, c.name as chapter_name
        FROM notes n
        LEFT JOIN study_fields sf ON n.field_id = sf.id
        LEFT JOIN subjects s ON n.subject_id = s.id
        LEFT JOIN chapters c ON n.chapter_id = c.id
        WHERE n.status = 'pending'
        ORDER BY n.created_at DESC LIMIT ?""",
        (limit,),
    )
    await db.close()
    return rows


async def approve_note(note_id: int, reviewed_by: int, review_note: str = "") -> None:
    await update_note(note_id, status="approved", reviewed_by=reviewed_by, review_note=review_note)


async def reject_note(note_id: int, reviewed_by: int, review_note: str = "") -> None:
    await update_note(note_id, status="rejected", reviewed_by=reviewed_by, review_note=review_note)


async def count_notes(
    status: Optional[str] = None,
    field_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
) -> int:
    """Count active notes with optional filters (exact, not capped by LIMIT)."""
    db = await get_db()
    query = "SELECT COUNT(*) as cnt FROM notes WHERE is_active = 1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if field_id:
        query += " AND field_id = ?"
        params.append(field_id)
    if subject_id:
        query += " AND subject_id = ?"
        params.append(subject_id)
    if chapter_id:
        query += " AND chapter_id = ?"
        params.append(chapter_id)
    row = await db.execute_fetchall(query, params)
    await db.close()
    return row[0]["cnt"] if row else 0


# ─── Admin ───────────────────────────────────────────────────────────────────

async def create_admin(
    user_id: int,
    username: str,
    full_name: str,
    password_hash: str,
    is_main_admin: bool = False,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO admins (user_id, username, full_name, password_hash, is_main_admin)
        VALUES (?, ?, ?, ?, ?)""",
        (user_id, username, full_name, password_hash, 1 if is_main_admin else 0),
    )
    await db.commit()
    admin_id = cursor.lastrowid
    await db.close()
    return admin_id


async def get_admin_by_user_id(user_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM admins WHERE user_id = ? AND is_active = 1", (user_id,)
    )
    await db.close()
    return row[0] if row else None


async def get_admin_by_id(admin_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM admins WHERE id = ?", (admin_id,)
    )
    await db.close()
    return row[0] if row else None


async def get_all_admins() -> List[aiosqlite.Row]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM admins ORDER BY is_main_admin DESC, created_at")
    await db.close()
    return rows


async def update_admin_password(admin_id: int, password_hash: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE admins SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (password_hash, admin_id),
    )
    await db.commit()
    await db.close()


async def toggle_admin_active(admin_id: int, is_active: bool) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE admins SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (1 if is_active else 0, admin_id),
    )
    await db.commit()
    await db.close()


async def set_admin_owner(admin_id: int, is_owner: bool) -> None:
    """Promote/demote an admin to/from Owner (is_main_admin flag)."""
    db = await get_db()
    await db.execute(
        "UPDATE admins SET is_main_admin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (1 if is_owner else 0, admin_id),
    )
    await db.commit()
    await db.close()


async def delete_admin(admin_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
    await db.commit()
    await db.close()


# ─── Permissions ─────────────────────────────────────────────────────────────

async def set_admin_permissions(admin_id: int, permissions: list) -> None:
    db = await get_db()
    await db.execute("DELETE FROM admin_permissions WHERE admin_id = ?", (admin_id,))
    for perm in permissions:
        await db.execute(
            "INSERT INTO admin_permissions (admin_id, permission) VALUES (?, ?)",
            (admin_id, perm),
        )
    await db.commit()
    await db.close()


async def get_admin_permissions(admin_id: int) -> List[str]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT permission FROM admin_permissions WHERE admin_id = ?", (admin_id,)
    )
    await db.close()
    return [row["permission"] for row in rows]


async def admin_has_permission(admin_id: int, permission: str) -> bool:
    db = await get_db()
    row = await db.execute_fetchall(
        """SELECT 1 FROM admin_permissions ap
        JOIN admins a ON ap.admin_id = a.id
        WHERE a.id = ? AND a.is_active = 1 AND ap.permission = ?""",
        (admin_id, permission),
    )
    await db.close()
    return len(row) > 0


# ─── User ────────────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str, full_name: str) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        username = excluded.username,
        full_name = excluded.full_name""",
        (user_id, username, full_name),
    )
    await db.commit()
    await db.close()


async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    )
    await db.close()
    return row[0] if row else None


# ─── Allowed Users ────────────────────────────────────────────────────────────

async def add_allowed_user(
    user_id: int, username: str, full_name: str, added_by: int
) -> None:
    db = await get_db()
    await db.execute(
        """INSERT OR REPLACE INTO allowed_users (user_id, username, full_name, added_by)
        VALUES (?, ?, ?, ?)""",
        (user_id, username, full_name, added_by),
    )
    await db.commit()
    await db.close()


async def remove_allowed_user(user_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
    await db.commit()
    await db.close()


async def is_allowed_user(user_id: int) -> bool:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT 1 FROM allowed_users WHERE user_id = ? AND can_submit_without_approval = 1",
        (user_id,),
    )
    await db.close()
    return len(row) > 0


async def toggle_allowed_user(user_id: int, enabled: bool) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE allowed_users SET can_submit_without_approval = ? WHERE user_id = ?",
        (1 if enabled else 0, user_id),
    )
    await db.commit()
    await db.close()


async def get_allowed_users() -> List[aiosqlite.Row]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM allowed_users ORDER BY created_at DESC")
    await db.close()
    return rows


# ─── Settings ─────────────────────────────────────────────────────────────────

async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT value FROM settings WHERE key = ?", (key,)
    )
    await db.close()
    return row[0]["value"] if row else default


async def set_setting(key: str, value: str, description: str = "") -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO settings (key, value, description)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
        (key, value, description),
    )
    await db.commit()
    await db.close()


# ─── Logs ────────────────────────────────────────────────────────────────────

async def add_log(
    user_id: Optional[int],
    username: str,
    action: str,
    details: str = "",
) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO logs (user_id, username, action, details) VALUES (?, ?, ?, ?)",
        (user_id, username, action, details),
    )
    await db.commit()
    await db.close()


async def get_logs(limit: int = 50, offset: int = 0) -> List[aiosqlite.Row]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    await db.close()
    return rows


# ─── Weekly Schedule ────────────────────────────────────────────────────────

DAYS_FA = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]

async def set_schedule_cell(field_id: Optional[int], day_index: int, col_index: int, content: str) -> None:
    """Insert or update a single schedule cell."""
    db = await get_db()
    await db.execute(
        """INSERT INTO schedule_entries (field_id, day_index, col_index, content)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(field_id, day_index, col_index) DO UPDATE SET
        content = excluded.content, updated_at = CURRENT_TIMESTAMP""",
        (field_id, day_index, col_index, content),
    )
    await db.commit()
    await db.close()


async def clear_schedule(field_id: Optional[int] = None) -> None:
    db = await get_db()
    if field_id is None:
        await db.execute("DELETE FROM schedule_entries")
    else:
        await db.execute("DELETE FROM schedule_entries WHERE field_id = ?", (field_id,))
    await db.commit()
    await db.close()


async def get_schedule(field_id: Optional[int] = None) -> dict:
    """Return {(day_index, col_index): content} for a field (or global)."""
    db = await get_db()
    if field_id is None:
        rows = await db.execute_fetchall("SELECT day_index, col_index, content FROM schedule_entries")
    else:
        rows = await db.execute_fetchall(
            "SELECT day_index, col_index, content FROM schedule_entries WHERE field_id = ?",
            (field_id,),
        )
    await db.close()
    return {(r["day_index"], r["col_index"]): r["content"] for r in rows}


async def get_day_tasks(field_id: Optional[int], day_index: int) -> List[str]:
    """Get the tasks/subjects listed for a single day (columns 1..6)."""
    sched = await get_schedule(field_id)
    return [sched.get((day_index, c), "") for c in range(1, 8) if sched.get((day_index, c), "")]


# ─── Task Status (per-user, weekly reset) ───────────────────────────────────

async def set_task_status(user_id: int, day_index: int, week_key: str, done: bool) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO task_status (user_id, day_index, week_key, done)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, day_index, week_key) DO UPDATE SET
        done = excluded.done, updated_at = CURRENT_TIMESTAMP""",
        (int(user_id), int(day_index), str(week_key), 1 if done else 0),
    )
    await db.commit()
    await db.close()


async def get_task_status(user_id: int, week_key: str) -> dict:
    """Return {day_index: done_boolean} for the given user/week."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT day_index, done FROM task_status WHERE user_id = ? AND week_key = ?",
        (user_id, week_key),
    )
    await db.close()
    return {row["day_index"]: bool(row["done"]) for row in rows}


async def reset_week_tasks() -> int:
    """Delete old task records from previous weeks (called by scheduler).
    Returns the number of deleted rows."""
    from datetime import datetime
    current_week = current_week_key()
    db = await get_db()
    cursor = await db.execute("DELETE FROM task_status WHERE week_key != ?", (current_week,))
    cursor2 = await db.execute("DELETE FROM task_done WHERE week_key != ?", (current_week,))
    await db.commit()
    await db.close()
    return (cursor.rowcount or 0) + (cursor2.rowcount or 0)


def current_week_key() -> str:
    """Saturday-based week key, e.g. '2026-W40'."""
    from datetime import datetime, timedelta
    today = datetime.now()
    # Saturday = start of Iranian school week.  Python: Monday=0 ... Sunday=6
    days_since_saturday = (today.weekday() + 2) % 7
    week_start = today - timedelta(days=days_since_saturday)
    return f"{week_start.isocalendar()[0]}-W{week_start.isocalendar()[1]}"


# ─── Task Done (per-user, per-task, weekly) ───────────────────────────────

async def set_task_done(user_id: int, task_key: str, week_key: str, done: bool) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO task_done (user_id, task_key, week_key, done)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, task_key, week_key) DO UPDATE SET
        done = excluded.done, updated_at = CURRENT_TIMESTAMP""",
        (int(user_id), str(task_key), str(week_key), 1 if done else 0),
    )
    await db.commit()
    await db.close()


async def get_task_done(user_id: int, task_key: str, week_key: str) -> bool:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT done FROM task_done WHERE user_id = ? AND task_key = ? AND week_key = ?",
        (user_id, task_key, week_key),
    )
    await db.close()
    return bool(rows and rows[0]["done"])


async def get_day_done_status(user_id: int, day_index: int, week_key: str) -> tuple[int, int]:
    """Return (done_count, total_count) of a day's tasks for one user.
    Counts schedule items (sched:{day}:{period} non-empty) plus the
    homework tasks of that day are NOT included here (they are global,
    category-based) - day tasks come from the schedule grid."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT col_index, content FROM schedule_entries WHERE day_index = ? AND content != ''",
        (day_index,),
    )
    if not rows:
        await db.close()
        return (0, 0)
    keys = [f"sched:{day_index}:{r['col_index']}" for r in rows]
    placeholders = ",".join("?" for _ in keys)
    done_rows = await db.execute_fetchall(
        f"SELECT task_key FROM task_done WHERE user_id = ? AND week_key = ? "
        f"AND done = 1 AND task_key IN ({placeholders})",
        [user_id, week_key, *keys],
    )
    await db.close()
    return (len(done_rows), len(keys))


def day_status_emoji(done: int, total: int) -> str:
    """🔴 none done / 🟡 partially done / 🟢 all done / ⚪ no tasks."""
    if total == 0:
        return "⚪"
    if done == 0:
        return "🔴"
    if done < total:
        return "🟡"
    return "🟢"


# ─── Online Classes (کلاس‌های آنلاین) ────────────────────────────────────────

async def add_online_class(day_index: int, title: str, time_text: str = "", link: str = "") -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO online_classes (day_index, title, time_text, link) VALUES (?, ?, ?, ?)",
        (int(day_index), title.strip(), time_text.strip(), link.strip()),
    )
    await db.commit()
    cid = cursor.lastrowid
    await db.close()
    return cid


async def get_online_classes(day_index: Optional[int] = None) -> List[aiosqlite.Row]:
    """Active online classes, optionally for one day."""
    db = await get_db()
    if day_index is None:
        rows = await db.execute_fetchall(
            "SELECT * FROM online_classes WHERE is_active = 1 ORDER BY day_index, id")
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM online_classes WHERE is_active = 1 AND day_index = ? ORDER BY id",
            (int(day_index),),
        )
    await db.close()
    return rows


async def delete_online_class(class_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM online_classes WHERE id = ?", (class_id,))
    await db.commit()
    await db.close()


async def clear_online_classes(day_index: Optional[int] = None) -> None:
    db = await get_db()
    if day_index is None:
        await db.execute("DELETE FROM online_classes")
    else:
        await db.execute("DELETE FROM online_classes WHERE day_index = ?", (day_index,))
    await db.commit()
    await db.close()


# ─── Convert Jobs ──────────────────────────────────────────────────────────

async def add_convert_job(user_id: int, src_type: str, dst_type: str,
                          input_ids: str = "", output_type: str = "") -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO convert_jobs (user_id, src_type, dst_type, input_ids, output_type)
        VALUES (?, ?, ?, ?, ?)""",
        (user_id, src_type, dst_type, input_ids, output_type),
    )
    await db.commit()
    await db.close()
    return cursor.lastrowid


# ─── Task Categories (دسته‌بندی تکالیف) ───────────────────────────────────────

async def create_task_category(name: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO task_categories (name) VALUES (?)", (name.strip(),)
        )
        await db.commit()
        return cursor.lastrowid
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_task_categories() -> List[aiosqlite.Row]:
    """All categories with their active task counts."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT c.*, COUNT(t.id) AS task_count
        FROM task_categories c
        LEFT JOIN tasks t ON t.category_id = c.id AND t.is_active = 1
        GROUP BY c.id
        ORDER BY c.name"""
    )
    await db.close()
    return rows


async def get_task_category_by_id(cat_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM task_categories WHERE id = ?", (cat_id,)
    )
    await db.close()
    return row[0] if row else None


async def rename_task_category(cat_id: int, new_name: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE task_categories SET name = ? WHERE id = ?", (new_name.strip(), cat_id)
    )
    await db.commit()
    await db.close()

async def delete_task_category(cat_id: int) -> int:
    """Delete a category and (cascade) its tasks. Returns deleted task count."""
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT COUNT(*) AS cnt FROM tasks WHERE category_id = ? AND is_active = 1", (cat_id,)
    )
    count = row[0]["cnt"] if row else 0
    await db.execute("DELETE FROM tasks WHERE category_id = ?", (cat_id,))
    await db.execute("DELETE FROM task_categories WHERE id = ?", (cat_id,))
    await db.commit()
    await db.close()
    return count


# ─── Tasks (تکالیف) ────────────────────────────────────────────────────────

async def create_task(category_id: int, title: str, details: str, created_by: int) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO tasks (category_id, title, details, created_by) VALUES (?, ?, ?, ?)",
        (category_id, title.strip(), details.strip(), created_by),
    )
    await db.commit()
    task_id = cursor.lastrowid
    await db.close()
    return task_id


async def get_all_tasks_grouped() -> dict:
    """Return {category_row: [task_rows]} for the user view, ordered.
    Categories without active tasks are omitted."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT t.*, c.name AS category_name
        FROM tasks t
        JOIN task_categories c ON t.category_id = c.id
        WHERE t.is_active = 1
        ORDER BY c.name, t.created_at DESC"""
    )
    await db.close()
    grouped: dict = {}
    order: list = []
    for r in rows:
        cat = r["category_name"]
        if cat not in grouped:
            grouped[cat] = []
            order.append(cat)
        grouped[cat].append(r)
    return {cat: grouped[cat] for cat in order}


async def get_tasks_by_category(cat_id: int) -> List[aiosqlite.Row]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM tasks WHERE category_id = ? AND is_active = 1 ORDER BY created_at DESC",
        (cat_id,),
    )
    await db.close()
    return rows


async def get_task_by_id(task_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    row = await db.execute_fetchall("SELECT * FROM tasks WHERE id = ?", (task_id,))
    await db.close()
    return row[0] if row else None


async def delete_task(task_id: int) -> None:
    """Soft delete a task."""
    db = await get_db()
    await db.execute("UPDATE tasks SET is_active = 0 WHERE id = ?", (task_id,))
    await db.commit()
    await db.close()


# ─── Group Activity / Nudge (پیام تشویقی کم‌فعالیتی) ─────────────────────

async def touch_group_activity(chat_id: int, chat_title: str = "") -> None:
    """Record that the bot was just used in a group (resets the 4-day timer)."""
    db = await get_db()
    await db.execute(
        """INSERT INTO group_activity (chat_id, chat_title, last_use_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(chat_id) DO UPDATE SET
        chat_title = excluded.chat_title, last_use_at = CURRENT_TIMESTAMP""",
        (chat_id, chat_title),
    )
    await db.commit()
    await db.close()


async def get_stale_groups(days: int = 4) -> List[aiosqlite.Row]:
    """Groups where nobody used the bot for >= `days` days and the last nudge
    is older than the same period (so we never spam)."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM group_activity
        WHERE last_use_at <= datetime('now', ?)
          AND (last_nudge_at IS NULL
               OR last_nudge_at <= datetime('now', ?))""",
        (f"-{days} days", f"-{days} days"),
    )
    await db.close()
    return rows


async def mark_group_nudged(chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE group_activity SET last_nudge_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
        (chat_id,),
    )
    await db.commit()
    await db.close()


async def upsert_group_member(chat_id: int, user_id: int,
                              username: str = "", full_name: str = "") -> None:
    """Remember a member seen in a group (for /all mentions + stats)."""
    db = await get_db()
    await db.execute(
        """INSERT INTO group_members (chat_id, user_id, username, full_name, last_seen_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
        username = excluded.username, full_name = excluded.full_name,
        last_seen_at = CURRENT_TIMESTAMP""",
        (chat_id, user_id, username, full_name),
    )
    await db.commit()
    await db.close()


async def get_group_members(chat_id: int) -> List[aiosqlite.Row]:
    """Members seen in the group during the last 30 days."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM group_members WHERE chat_id = ?
        AND last_seen_at >= datetime('now', '-30 days')
        ORDER BY username != '' DESC, full_name""",
        (chat_id,),
    )
    await db.close()
    return rows


# ─── Usage Stats (آمار استفاده / Top-5) ───────────────────────────────────

async def bump_usage(user_id: int, username: str = "", full_name: str = "") -> None:
    """Count one more feature use by this user."""
    db = await get_db()
    await db.execute(
        """INSERT INTO usage_stats (user_id, username, full_name, uses, last_use_at)
        VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        username = excluded.username, full_name = excluded.full_name,
        uses = uses + 1, last_use_at = CURRENT_TIMESTAMP""",
        (user_id, username, full_name),
    )
    await db.commit()
    await db.close()


async def get_top_users(limit: int = 5) -> List[aiosqlite.Row]:
    """Most active users by feature-use count."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM usage_stats ORDER BY uses DESC, last_use_at DESC LIMIT ?",
        (limit,),
    )
    await db.close()
    return rows


async def get_stats_overview() -> dict:
    """General bot stats snapshot for the admin PDF report."""
    db = await get_db()
    async def _one(sql: str) -> int:
        cur = await db.execute(sql)
        row = await cur.fetchone()
        return row[0] if row else 0
    stats = {
        "users_total": await _one("SELECT COUNT(*) FROM users"),
        "group_members": await _one(
            "SELECT COUNT(DISTINCT user_id) FROM group_members"),
        "admins_total": await _one(
            "SELECT COUNT(*) FROM admins WHERE is_active = 1"),
        "notes_total": await _one("SELECT COUNT(*) FROM notes WHERE is_active = 1"),
        "notes_approved": await _one(
            "SELECT COUNT(*) FROM notes WHERE is_active = 1 AND status = 'approved'"),
        "notes_pending": await _one(
            "SELECT COUNT(*) FROM notes WHERE is_active = 1 AND status = 'pending'"),
        "fields_total": await _one("SELECT COUNT(*) FROM study_fields WHERE is_active = 1"),
        "subjects_total": await _one("SELECT COUNT(*) FROM subjects WHERE is_active = 1"),
        "chapters_total": await _one("SELECT COUNT(*) FROM chapters WHERE is_active = 1"),
        "tasks_total": await _one("SELECT COUNT(*) FROM tasks WHERE is_active = 1"),
        "online_classes": await _one(
            "SELECT COUNT(*) FROM online_classes WHERE is_active = 1"),
        "conversions": await _one("SELECT COUNT(*) FROM convert_jobs"),
        "logs_total": await _one("SELECT COUNT(*) FROM logs"),
        "usage_total": await _one("SELECT COALESCE(SUM(uses), 0) FROM usage_stats"),
    }
    await db.close()
    return stats


# ─── /all Cooldown (per group, 60s) ─────────────────────────────────────

async def all_cooldown_remaining(chat_id: int, seconds: int = 60) -> int:
    """Seconds left before /all can be used again in this chat (0 = free)."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT last_used_at FROM all_cooldowns WHERE chat_id = ?", (chat_id,))
    remaining = 0
    if rows:
        cur = await db.execute(
            "SELECT CAST((julianday('now') - julianday(?)) * 86400 AS INTEGER)",
            (rows[0]["last_used_at"],),
        )
        elapsed = (await cur.fetchone())[0] or 0
        remaining = max(0, seconds - int(elapsed))
    await db.close()
    return remaining


async def all_cooldown_set(chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO all_cooldowns (chat_id, last_used_at) VALUES (?, CURRENT_TIMESTAMP)
        ON CONFLICT(chat_id) DO UPDATE SET last_used_at = CURRENT_TIMESTAMP""",
        (chat_id,),
    )
    await db.commit()
    await db.close()


# ─── Class Alert Dedupe (survives restarts) ─────────────────────────────

async def class_alert_already_sent(class_id: int, alert_date: str) -> bool:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT 1 FROM class_alerts_sent WHERE class_id = ? AND alert_date = ?",
        (class_id, alert_date),
    )
    await db.close()
    return bool(rows)


async def class_alert_mark_sent(class_id: int, alert_date: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO class_alerts_sent (class_id, alert_date) VALUES (?, ?)",
        (class_id, alert_date),
    )
    await db.commit()
    await db.close()


# ─── Online Classes: structured times + editing ─────────────────────────

async def add_online_class_full(day_index: int, title: str, time_text: str = "",
                                link: str = "", start_hour: Optional[int] = None,
                                start_minute: int = 0,
                                end_hour: Optional[int] = None) -> int:
    """Add a class with structured Tehran-time fields."""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO online_classes
        (day_index, title, time_text, link, start_hour, start_minute, end_hour)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (int(day_index), title.strip(), time_text.strip(), link.strip(),
         start_hour, start_minute, end_hour),
    )
    await db.commit()
    cid = cursor.lastrowid
    await db.close()
    return cid


async def get_online_class_by_id(class_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM online_classes WHERE id = ?", (class_id,))
    await db.close()
    return rows[0] if rows else None


async def update_online_class(class_id: int, *, day_index: Optional[int] = None,
                              title: Optional[str] = None,
                              time_text: Optional[str] = None,
                              link: Optional[str] = None,
                              start_hour: Optional[int] = ...,
                              start_minute: Optional[int] = ...,
                              end_hour: Optional[int] = ...) -> None:
    """Partial update of a class. Sentinel (...) means "leave unchanged";
    explicit None clears the field."""
    db = await get_db()
    sets, vals = [], []
    if day_index is not None:
        sets.append("day_index = ?"); vals.append(int(day_index))
    if title is not None:
        sets.append("title = ?"); vals.append(title.strip())
    if time_text is not None:
        sets.append("time_text = ?"); vals.append(time_text.strip())
    if link is not None:
        sets.append("link = ?"); vals.append(link.strip())
    if start_hour is not ...:
        sets.append("start_hour = ?"); vals.append(start_hour)
    if start_minute is not ...:
        sets.append("start_minute = ?"); vals.append(start_minute)
    if end_hour is not ...:
        sets.append("end_hour = ?"); vals.append(end_hour)
    if sets:
        vals.append(class_id)
        await db.execute(f"UPDATE online_classes SET {', '.join(sets)} WHERE id = ?", vals)
        await db.commit()
    await db.close()


async def set_class_notify(class_id: int, enabled: bool) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE online_classes SET notify_enabled = ? WHERE id = ?",
        (1 if enabled else 0, class_id),
    )
    await db.commit()
    await db.close()


# ─── Chapter File Search + Note Quota ──────────────────────────────────

async def search_chapter_notes(chapter_id: int, query: str,
                               approved_only: bool = True) -> List[aiosqlite.Row]:
    """Find files in one chapter whose title/name matches the query."""
    like = f"%{query.strip()}%"
    db = await get_db()
    sql = """SELECT * FROM notes WHERE is_active = 1 AND chapter_id = ?
    AND (title LIKE ? OR file_name LIKE ?)"""
    if approved_only:
        sql += " AND status = 'approved'"
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = await db.execute_fetchall(sql, (chapter_id, like, like))
    await db.close()
    return rows


async def count_user_notes(user_id: int) -> int:
    """Total active notes submitted by a user (approved + pending)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM notes WHERE is_active = 1 AND submitted_by = ?",
        (user_id,),
    )
    row = await cur.fetchone()
    await db.close()
    return row[0] if row else 0
