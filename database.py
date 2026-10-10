"""
Database module for Bot-File-School.
Handles SQLite connection, schema creation, and query execution.
"""

import asyncio
import sqlite3
from contextlib import asynccontextmanager

import aiosqlite
from pathlib import Path
from config import DATABASE_PATH
from logger import logger


SCHEMA_SQL = """
-- Study Fields
CREATE TABLE IF NOT EXISTS study_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Subjects
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (field_id) REFERENCES study_fields(id) ON DELETE CASCADE,
    UNIQUE(field_id, name)
);

-- Chapters
CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    UNIQUE(subject_id, name)
);

-- Notes
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    field_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    chapter_id INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    file_type TEXT DEFAULT '',
    file_id TEXT,
    file_unique_id TEXT,
    file_name TEXT,
    mime_type TEXT,
    file_size INTEGER DEFAULT 0,
    submitted_by INTEGER NOT NULL,
    submitted_by_name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    reviewed_by INTEGER,
    review_note TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (field_id) REFERENCES study_fields(id),
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (chapter_id) REFERENCES chapters(id)
);

-- Admins
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    is_main_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Admin Permissions
CREATE TABLE IF NOT EXISTS admin_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE CASCADE,
    UNIQUE(admin_id, permission)
);

-- Users
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Allowed Users
CREATE TABLE IF NOT EXISTS allowed_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    can_submit_without_approval INTEGER DEFAULT 1,
    added_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Settings
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT DEFAULT '',
    description TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Logs
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT DEFAULT '',
    action TEXT NOT NULL,
    details TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Weekly class schedule (7 days x 7 columns grid, one row per class/year)
CREATE TABLE IF NOT EXISTS schedule_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER,
    day_index INTEGER NOT NULL,        -- 0=Saturday ... 6=Friday
    col_index INTEGER NOT NULL,        -- 0 = day label, 1..6 = subjects
    content TEXT DEFAULT '',           -- subject/task name shown in that cell
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(field_id, day_index, col_index)
);

-- Per-user task completion records (per scheduled task + week).
-- week_key is Saturday-based e.g. '2026-W40' so records auto-reset weekly.
-- day_index retained for migration/back-compat of old rows.
CREATE TABLE IF NOT EXISTS task_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    day_index INTEGER NOT NULL DEFAULT -1,
    week_key TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    task_key TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, day_index, week_key)
);

-- Per-user per-task completion for the new day-based schedule system.
-- task_key = 'sched:{day}:{period}' (schedule items) or 'task:{tasks.id}'.
CREATE TABLE IF NOT EXISTS task_done (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_key TEXT NOT NULL,
    week_key TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, task_key, week_key)
);

-- Ownership and allowed actions for every bot message with inline callbacks.
-- Ownership is immutable after insertion; edits only update the active actions.
CREATE TABLE IF NOT EXISTS inline_keyboard_ownership (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    owner_user_id INTEGER NOT NULL,
    operation_types TEXT NOT NULL,
    callback_data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, message_id)
);

-- Online classes (کلاس‌های آنلاین) - admin-defined, per day of week
-- start_hour/start_minute/end_hour are in Asia/Tehran time (class source
-- timetable). They are converted to the project timezone for display/sending.
CREATE TABLE IF NOT EXISTS online_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_index INTEGER NOT NULL,          -- 0=Saturday .. 6=Friday
    title TEXT NOT NULL,                 -- e.g. ریاضی
    time_text TEXT DEFAULT '',           -- e.g. ۱۶ تا ۱۸
    link TEXT DEFAULT '',                -- meeting URL (optional)
    start_hour INTEGER,                  -- Tehran-hour start (nullable)
    start_minute INTEGER DEFAULT 0,      -- Tehran-minute start
    end_hour INTEGER,                    -- Tehran-hour end (nullable)
    notify_enabled INTEGER DEFAULT 1,    -- per-class notification on/off
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- School timetable classes, independent by track and weekday.
CREATE TABLE IF NOT EXISTS weekly_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_key TEXT NOT NULL CHECK (track_key IN ('math', 'experimental', 'humanities')),
    day_index INTEGER NOT NULL CHECK (day_index BETWEEN 0 AND 6),
    class_name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    submission_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_weekly_classes_track_day_time
    ON weekly_classes(track_key, day_index, start_time, id);

-- Group activity tracking (for the "bot unused for 4 days" nudge feature)
CREATE TABLE IF NOT EXISTS group_activity (
    chat_id INTEGER PRIMARY KEY,
    chat_title TEXT DEFAULT '',
    last_use_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_nudge_at TIMESTAMP
);

-- Members seen in each group (used by /all and stats)
CREATE TABLE IF NOT EXISTS group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, user_id)
);

-- Per-user usage counter (most active users / Top-5 stats)
CREATE TABLE IF NOT EXISTS usage_stats (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    uses INTEGER DEFAULT 0,
    last_use_at TIMESTAMP
);

-- /all command cooldown per group (1 minute per chat, enforced in DB)
CREATE TABLE IF NOT EXISTS all_cooldowns (
    chat_id INTEGER PRIMARY KEY,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sent-notification dedupe so a restart never double-sends a class alert
CREATE TABLE IF NOT EXISTS class_alerts_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    alert_date TEXT NOT NULL,            -- YYYY-MM-DD (Tehran date of the class)
    UNIQUE(class_id, alert_date)
);

-- Conversion job history (for admin file conversion tracking)
CREATE TABLE IF NOT EXISTS convert_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    src_type TEXT NOT NULL,
    dst_type TEXT NOT NULL,
    input_ids TEXT DEFAULT '',
    output_type TEXT DEFAULT '',
    status TEXT DEFAULT 'done',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Task categories (دسته‌بندی تکالیف) - managed by admins
CREATE TABLE IF NOT EXISTS task_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Assignments/homework (تکالیف) - each linked to one category
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    details TEXT DEFAULT '',
    created_by INTEGER,
    field_id INTEGER,
    subject_id INTEGER,
    day_index INTEGER,
    due_at TEXT,
    file_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (category_id) REFERENCES task_categories(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_notes_field ON notes(field_id);
CREATE INDEX IF NOT EXISTS idx_notes_subject ON notes(subject_id);
CREATE INDEX IF NOT EXISTS idx_notes_chapter ON notes(chapter_id);
CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_subjects_field ON subjects(field_id);
CREATE INDEX IF NOT EXISTS idx_chapters_subject ON chapters(subject_id);
CREATE INDEX IF NOT EXISTS idx_logs_user ON logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_action ON logs(action);
CREATE INDEX IF NOT EXISTS idx_schedule_field ON schedule_entries(field_id);
CREATE INDEX IF NOT EXISTS idx_task_status_user ON task_status(user_id, week_key);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category_id);
CREATE INDEX IF NOT EXISTS idx_task_done_user ON task_done(user_id, week_key);
CREATE INDEX IF NOT EXISTS idx_online_classes_day ON online_classes(day_index);
CREATE INDEX IF NOT EXISTS idx_inline_keyboard_owner
    ON inline_keyboard_ownership(owner_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_group_members_chat ON group_members(chat_id);
CREATE INDEX IF NOT EXISTS idx_usage_stats_uses ON usage_stats(uses DESC);
"""

# Column migrations: add new columns to existing tables (idempotent).
# Each entry: (table, column, "COLUMN DDL")
COLUMN_MIGRATIONS = [
    ("online_classes", "start_hour", "INTEGER"),
    ("online_classes", "start_minute", "INTEGER DEFAULT 0"),
    ("online_classes", "end_hour", "INTEGER"),
    ("online_classes", "notify_enabled", "INTEGER DEFAULT 1"),
    ("tasks", "field_id", "INTEGER"),
    ("tasks", "subject_id", "INTEGER"),
    ("tasks", "day_index", "INTEGER"),
    ("tasks", "due_at", "TEXT"),
    ("tasks", "file_id", "TEXT"),
]


async def _migrate_columns(db: aiosqlite.Connection):
    """Add missing columns to existing tables (safe to run on every start)."""
    for table, column, ddl in COLUMN_MIGRATIONS:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in await cursor.fetchall()}
        if column not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            logger.info(f"Migration: added {table}.{column}")


async def init_database():
    """Initialize the database with schema and WAL mode.

    WAL is persistent (stored in the DB file), so it only needs to be set
    once. If the file is temporarily locked (e.g. by cloud sync or another
    bot instance), retry with backoff and continue without WAL rather than
    crashing the whole bot.
    """
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DATABASE_PATH, timeout=10)
    try:
        await db.execute("PRAGMA busy_timeout=10000")
        for attempt in range(3):
            try:
                await db.execute("PRAGMA journal_mode=WAL")
                break
            except aiosqlite.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 2:
                    logger.warning(
                        f"Database locked, retrying WAL setup "
                        f"(attempt {attempt + 1}/3)..."
                    )
                    await asyncio.sleep(2)
                else:
                    logger.warning(
                        f"Could not enable WAL mode: {e} - continuing without it. "
                        f"(If this persists: pause OneDrive sync, close other "
                        f"bot instances, or delete stale -wal/-shm files.)"
                    )
                    break
        await db.execute("PRAGMA foreign_keys=ON")
        for attempt in range(3):
            try:
                await db.executescript(SCHEMA_SQL)
                await _migrate_columns(db)
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_active_deadline "
                    "ON tasks(is_active, due_at)"
                )
                await db.commit()
                break
            except aiosqlite.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 2:
                    logger.warning(
                        f"Database locked during schema setup "
                        f"(attempt {attempt + 1}/3)..."
                    )
                    await asyncio.sleep(3)
                else:
                    raise RuntimeError(
                        f"Cannot initialize database: {e}. "
                        f"Another process (cloud sync, antivirus or a second "
                        f"bot instance) is locking {DATABASE_PATH}. "
                        f"Close it or move the project out of the synced folder."
                    ) from e
    finally:
        await db.close()


async def get_db() -> aiosqlite.Connection:
    """Get a database connection with proper settings.

    Prefer `db_session()` - it guarantees the connection is rolled back and
    closed even when a query raises (see the note there). Use this raw form
    only when the connection is handed to another component.

    Note: journal_mode is intentionally NOT set here - WAL persists in the
    database file and re-running the pragma on every connection requires
    an exclusive lock, which causes 'database is locked' errors.
    """
    db = await aiosqlite.connect(DATABASE_PATH, timeout=30)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout=30000")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


@asynccontextmanager
async def db_session():
    """Async context manager around a database connection (read or write).

    A connection that is left open after a failed statement keeps its write
    transaction (and therefore the SQLite write lock) alive until it is
    garbage collected. Every other writer then blocks for the full
    busy_timeout and finally fails with 'database is locked'. Using this
    context manager makes that impossible: the transaction is rolled back
    and the connection closed on every exit path, including exceptions.

    Write statements should use `db_write_session()` instead - see the note
    about transaction upgrades there.
    """
    db = await get_db()
    try:
        yield db
    except BaseException:
        try:
            await db.rollback()
        except Exception:  # pragma: no cover - best effort cleanup
            pass
        raise
    finally:
        try:
            await db.close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


# One write lock per event loop. SQLite allows a single writer at a time; the
# lock keeps that serialisation inside the process instead of letting N
# connections fight for it in the C library.
_write_locks: dict[int, asyncio.Lock] = {}


def _write_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _write_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _write_locks[id(loop)] = lock
    return lock


@asynccontextmanager
async def db_write_session():
    """Like db_session(), but serialised against other writers.

    Every connection opens SQLite in 'deferred' mode: the transaction starts
    with the first statement, and a transaction that has already READ and then
    wants to WRITE must wait for the write lock. That upgrade cannot use the
    busy handler, so under concurrency SQLite returns SQLITE_BUSY immediately -
    'database is locked' regardless of busy_timeout. Taking this lock first
    means at most one write transaction exists at any moment, so the upgrade
    can never conflict. Reads are unaffected and stay concurrent (WAL).
    """
    async with _write_lock():
        async with db_session() as db:
            yield db


# ─── Synchronous helpers for inline queries ──────────────────────────────────

def get_sync_db() -> sqlite3.Connection:
    """Get a synchronous database connection (for inline queries).

    WAL persists in the DB file, so it is not re-set here (see get_db).
    """
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
