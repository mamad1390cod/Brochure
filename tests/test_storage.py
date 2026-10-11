import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendDocument

import database
import migrate_files_to_drive
import migrate_database_path
import storage
from database import db_session

REAL_UPLOAD_FILE = storage.upload_file
REAL_UPLOAD_TELEGRAM_FILE = storage.upload_telegram_file
REAL_CHECK_DRIVE_READY = storage.check_drive_ready


def test_drive_error_hint_explains_missing_oauth_variables():
    error = storage.StorageConfigurationError(
        "Missing required Google Drive Railway variables: "
        "GOOGLE_DRIVE_REFRESH_TOKEN"
    )
    assert storage.drive_error_hint(error) == str(error)


def test_drive_error_hint_explains_expired_refresh_token():
    error = RuntimeError("invalid_grant: Token has been expired or revoked.")
    assert "expired or revoked" in storage.drive_error_hint(error)
    assert "GOOGLE_DRIVE_REFRESH_TOKEN" in storage.drive_error_hint(error)


def test_drive_error_hint_explains_full_google_storage_quota():
    error = RuntimeError('{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}')
    assert "no available Drive storage quota" in storage.drive_error_hint(error)


def test_drive_error_hint_does_not_include_raw_api_error_text():
    class FakeHttpError(Exception):
        def __init__(self):
            super().__init__("sensitive response text")
            self.resp = SimpleNamespace(status=403)

    hint = storage.drive_error_hint(FakeHttpError())
    assert "denied access" in hint
    assert "sensitive response text" not in hint


def test_drive_service_reports_missing_variable_names_without_values(monkeypatch, caplog):
    monkeypatch.setattr(storage, "GOOGLE_DRIVE_CLIENT_ID", "configured")
    monkeypatch.setattr(storage, "GOOGLE_DRIVE_CLIENT_SECRET", "")
    monkeypatch.setattr(storage, "GOOGLE_DRIVE_REFRESH_TOKEN", "")

    with pytest.raises(storage.StorageConfigurationError) as error:
        storage._build_drive_service()

    assert "GOOGLE_DRIVE_CLIENT_SECRET" in str(error.value)
    assert "GOOGLE_DRIVE_REFRESH_TOKEN" in str(error.value)
    assert "configured" not in caplog.text


def test_drive_service_accepts_cached_naive_oauth_expiry(monkeypatch):
    monkeypatch.setattr(storage, "GOOGLE_DRIVE_CLIENT_ID", "test-client")
    monkeypatch.setattr(storage, "GOOGLE_DRIVE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(storage, "GOOGLE_DRIVE_REFRESH_TOKEN", "test-refresh-token")
    monkeypatch.setattr(storage, "_access_token", "cached-access-token")
    monkeypatch.setattr(
        storage,
        "_access_token_expiry",
        (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None),
    )

    service = storage._build_drive_service()

    assert service is not None


@pytest.mark.asyncio
async def test_upload_persists_drive_metadata_and_reuses_existing_file(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(storage, "upload_file", REAL_UPLOAD_FILE)
    local_file = tmp_path / "lesson.pdf"
    local_file.write_bytes(b"pdf payload")
    uploads = 0

    def fake_upload(path, *, source_key, original_filename, mime_type):
        nonlocal uploads
        uploads += 1
        data = Path(path).read_bytes()
        return {
            "id": "drive-file-1",
            "name": original_filename,
            "mimeType": mime_type,
            "size": str(len(data)),
            "md5Checksum": "checksum",
            "createdTime": "2026-10-10T12:00:00Z",
        }

    monkeypatch.setattr(storage, "_upload_local_file_sync", fake_upload)
    monkeypatch.setattr(
        storage,
        "_get_remote_metadata_sync",
        lambda drive_id: {
            "id": drive_id,
            "name": "lesson.pdf",
            "mimeType": "application/pdf",
            "size": "11",
            "md5Checksum": "checksum",
        },
    )

    saved, concurrent = await asyncio.gather(
        storage.upload_file(
            local_file,
            source_key="telegram:unique-lesson",
            original_filename="lesson.pdf",
            mime_type="application/pdf",
            telegram_file_id="telegram-file-1",
            telegram_file_unique_id="unique-lesson",
            uploaded_by=123,
            purpose="note",
        ),
        storage.upload_file(
            local_file,
            source_key="telegram:unique-lesson",
            original_filename="lesson.pdf",
            mime_type="application/pdf",
            telegram_file_id="telegram-file-1",
            telegram_file_unique_id="unique-lesson",
            uploaded_by=123,
            purpose="note",
        ),
    )
    reused = await storage.upload_file(
        local_file,
        source_key="telegram:unique-lesson",
        original_filename="lesson.pdf",
        mime_type="application/pdf",
        telegram_file_id="telegram-file-1",
        telegram_file_unique_id="unique-lesson",
        uploaded_by=123,
        purpose="note",
    )

    assert saved.id == concurrent.id == reused.id
    assert saved.drive_file_id == "drive-file-1"
    assert saved.telegram_file_id == "telegram-file-1"
    assert saved.uploaded_by == 123
    assert saved.file_size == len(b"pdf payload")
    assert uploads == 1
    async with db_session() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM stored_files WHERE source_key = ?",
            ("telegram:unique-lesson",),
        )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_drive_startup_check_verifies_oauth_and_folder(monkeypatch):
    checked = []
    monkeypatch.setattr(storage, "check_drive_ready", REAL_CHECK_DRIVE_READY)
    monkeypatch.setattr(storage, "_check_drive_ready_sync", lambda: checked.append(True))

    await storage.check_drive_ready()

    assert checked == [True]


@pytest.mark.asyncio
async def test_drive_startup_check_logs_actionable_failure(monkeypatch, caplog):
    monkeypatch.setattr(storage, "check_drive_ready", REAL_CHECK_DRIVE_READY)

    def fail_check():
        raise storage.StorageConfigurationError(
            "Missing required Google Drive Railway variables: GOOGLE_DRIVE_REFRESH_TOKEN"
        )

    monkeypatch.setattr(storage, "_check_drive_ready_sync", fail_check)
    with pytest.raises(RuntimeError, match="GOOGLE_DRIVE_REFRESH_TOKEN"):
        await storage.check_drive_ready()

    assert "Google Drive startup check failed" in caplog.text
    assert "GOOGLE_DRIVE_REFRESH_TOKEN" in caplog.text


@pytest.mark.asyncio
async def test_drive_upload_failure_does_not_create_metadata(app, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "upload_file", REAL_UPLOAD_FILE)
    local_file = tmp_path / "broken.pdf"
    local_file.write_bytes(b"payload")

    def fail_upload(*args, **kwargs):
        raise RuntimeError("simulated Google API outage")

    monkeypatch.setattr(storage, "_upload_local_file_sync", fail_upload)
    with pytest.raises(RuntimeError, match="simulated"):
        await storage.upload_file(
            local_file,
            source_key="generated:broken",
            original_filename="broken.pdf",
            mime_type="application/pdf",
            uploaded_by=123,
            purpose="generated_pdf",
        )

    async with db_session() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM stored_files WHERE source_key = ?",
            ("generated:broken",),
        )
    assert rows == []


@pytest.mark.asyncio
async def test_telegram_bad_file_reference_falls_back_to_private_drive(
    tmp_path, monkeypatch
):
    fallback_file = tmp_path / "restored.pdf"
    fallback_file.write_bytes(b"drive payload")
    stored = SimpleNamespace(original_filename="lesson.pdf")

    async def fake_get_stored_file(_stored_id):
        return stored

    async def fake_download_file(_stored_id):
        return fallback_file

    monkeypatch.setattr(storage, "get_stored_file", fake_get_stored_file)
    monkeypatch.setattr(storage, "download_file", fake_download_file)

    class FakeMessage:
        def __init__(self):
            self.sent = []

        async def answer_document(self, document, *, caption):
            if isinstance(document, str):
                raise TelegramBadRequest(
                    method=SendDocument(chat_id=123, document=document),
                    message="wrong file identifier",
                )
            self.sent.append((document.path, caption))

    message = FakeMessage()
    await storage.send_stored_file(
        message,
        telegram_file_id="expired-telegram-reference",
        storage_file_id="stored-asset-id",
        file_type="document",
        caption="lesson",
    )

    assert len(message.sent) == 1
    assert message.sent[0][0] == fallback_file
    assert not fallback_file.exists()


@pytest.mark.asyncio
async def test_legacy_schema_gets_nullable_drive_reference_columns(tmp_path):
    legacy_path = tmp_path / "legacy.db"
    legacy_schema = database.SCHEMA_SQL.replace("    storage_file_id TEXT,\n", "")
    with sqlite3.connect(legacy_path) as connection:
        connection.executescript(legacy_schema)
        connection.execute(
            "INSERT INTO notes "
            "(title, field_id, subject_id, file_id, submitted_by) "
            "VALUES ('legacy note', 1, 1, 'old-telegram-id', 42)"
        )
        connection.execute(
            "INSERT INTO tasks (category_id, title, file_id) "
            "VALUES (1, 'legacy task', 'old-homework-id')"
        )

    original_path = database.DATABASE_PATH
    database.DATABASE_PATH = legacy_path
    try:
        await database.init_database()
    finally:
        database.DATABASE_PATH = original_path

    with sqlite3.connect(legacy_path) as connection:
        note = connection.execute(
            "SELECT file_id, storage_file_id FROM notes"
        ).fetchone()
        task = connection.execute(
            "SELECT file_id, storage_file_id FROM tasks"
        ).fetchone()
        assert connection.execute(
            "SELECT COUNT(*) FROM stored_files"
        ).fetchone()[0] == 0
    assert note == ("old-telegram-id", None)
    assert task == ("old-homework-id", None)


@pytest.mark.asyncio
async def test_legacy_media_migration_is_resumable_and_preserves_rows(
    app, monkeypatch
):
    async with database.db_write_session() as db:
        await db.execute(
            "INSERT INTO study_fields (id, name) VALUES (1, 'legacy field')"
        )
        await db.execute(
            "INSERT INTO subjects (id, field_id, name) "
            "VALUES (1, 1, 'legacy subject')"
        )
        await db.execute(
            "INSERT INTO task_categories (id, name) "
            "VALUES (1, 'legacy category')"
        )
        await db.execute(
            """INSERT INTO notes
            (title, field_id, subject_id, file_type, file_id, file_unique_id,
             file_name, mime_type, submitted_by)
            VALUES ('legacy note', 1, 1, 'document', 'note-telegram-id',
                    'note-unique-id', 'lesson.pdf', 'application/pdf', 81)"""
        )
        await db.execute(
            """INSERT INTO tasks (category_id, title, created_by, file_id)
            VALUES (1, 'legacy task', 82, 'task-telegram-id')"""
        )
        await db.commit()

    calls = []

    async def fake_upload(_bot, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=f"drive:{kwargs['telegram_file_id']}")

    monkeypatch.setattr(storage, "upload_telegram_file", fake_upload)
    migrated, failed, skipped = await migrate_files_to_drive.migrate_legacy_files()

    async with db_session() as db:
        notes = await db.execute_fetchall(
            "SELECT id, file_id, storage_file_id FROM notes"
        )
        tasks = await db.execute_fetchall(
            "SELECT id, file_id, storage_file_id FROM tasks"
        )

    assert (migrated, failed, skipped) == (2, 0, 0)
    assert len(calls) == 2
    assert notes[0]["file_id"] == "note-telegram-id"
    assert notes[0]["storage_file_id"] == "drive:note-telegram-id"
    assert tasks[0]["file_id"] == "task-telegram-id"
    assert tasks[0]["storage_file_id"] == "drive:task-telegram-id"


@pytest.mark.asyncio
async def test_drive_file_missing_is_reported_without_database_deletion(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(storage, "upload_file", REAL_UPLOAD_FILE)
    local_file = tmp_path / "retained.pdf"
    local_file.write_bytes(b"payload")
    monkeypatch.setattr(
        storage,
        "_upload_local_file_sync",
        lambda *args, **kwargs: {
            "id": "drive-file-missing",
            "name": "retained.pdf",
            "mimeType": "application/pdf",
            "size": "7",
        },
    )
    stored = await storage.upload_file(
        local_file,
        source_key="generated:retained",
        original_filename="retained.pdf",
        mime_type="application/pdf",
        uploaded_by=10,
        purpose="generated_pdf",
    )
    monkeypatch.setattr(storage, "_build_drive_service", lambda: object())
    monkeypatch.setattr(
        storage, "_get_remote_metadata", lambda _service, _drive_id: None
    )

    assert await storage.file_exists(stored.id) is False
    async with db_session() as db:
        rows = await db.execute_fetchall(
            "SELECT drive_file_id FROM stored_files WHERE id = ?",
            (stored.id,),
        )
    assert rows[0]["drive_file_id"] == "drive-file-missing"


@pytest.mark.asyncio
async def test_telegram_media_downloads_to_temp_and_cleans_up_after_drive_upload(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        storage, "upload_telegram_file", REAL_UPLOAD_TELEGRAM_FILE
    )
    monkeypatch.setattr(storage, "_TEMP_DIR", tmp_path / "telegram-tmp")
    uploaded_paths = []

    async def fake_download(_file_id, *, destination):
        destination.write_bytes(b"telegram media")

    async def fake_upload_file(path, **kwargs):
        uploaded_paths.append(Path(path))
        assert kwargs["source_key"] == "telegram:telegram-image-unique"
        assert Path(path).read_bytes() == b"telegram media"
        return SimpleNamespace(id="drive-telegram-media")

    monkeypatch.setattr(storage, "upload_file", fake_upload_file)
    assert storage.upload_file is fake_upload_file
    bot = SimpleNamespace(download=fake_download)
    result = await storage.upload_telegram_file(
        bot,
        telegram_file_id="telegram-image-id",
        telegram_file_unique_id="telegram-image-unique",
        original_filename="image.jpg",
        mime_type="image/jpeg",
        file_size=14,
        uploaded_by=321,
        purpose="note",
    )

    assert result.id == "drive-telegram-media"
    assert uploaded_paths and not uploaded_paths[0].exists()
    assert list((tmp_path / "telegram-tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_telegram_cloud_limit_rejects_large_pdf_before_download(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        storage, "upload_telegram_file", REAL_UPLOAD_TELEGRAM_FILE
    )
    async def no_existing_asset(_source_key):
        return None

    async def unexpected_download(*args, **kwargs):
        pytest.fail("Oversized Telegram media must be rejected before download.")

    temp_dir = tmp_path / "telegram-tmp"
    monkeypatch.setattr(storage, "_find_asset", no_existing_asset)
    monkeypatch.setattr(storage, "_TEMP_DIR", temp_dir)
    bot = SimpleNamespace(download=unexpected_download)

    with pytest.raises(storage.TelegramFileTooLargeError, match="20 MB"):
        await storage.upload_telegram_file(
            bot,
            telegram_file_id="large-pdf-file-id",
            telegram_file_unique_id="large-pdf-unique-id",
            original_filename="lesson.pdf",
            mime_type="application/pdf",
            file_size=storage.TELEGRAM_CLOUD_DOWNLOAD_LIMIT_BYTES + 1,
            uploaded_by=321,
            purpose="note",
        )

    assert not temp_dir.exists()


def test_database_path_migration_copies_without_overwriting_or_modifying_source(
    tmp_path,
):
    source = tmp_path / "current.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO users (name) VALUES ('existing user')")
    destination = tmp_path / "volume" / "school_notes.db"

    counts = migrate_database_path.copy_database(source, destination)

    assert counts == {"users": 1}
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT name FROM users").fetchone()[0] == (
            "existing user"
        )
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT name FROM users").fetchone()[0] == (
            "existing user"
        )
    with pytest.raises(FileExistsError):
        migrate_database_path.copy_database(source, destination)


def test_database_path_migration_removes_partial_destination_if_open_fails(
    tmp_path, monkeypatch
):
    source = tmp_path / "current.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    destination = tmp_path / "volume" / "school_notes.db"
    real_connect = sqlite3.connect

    def fail_connection(*args, **kwargs):
        raise sqlite3.OperationalError("simulated connection failure")

    monkeypatch.setattr(migrate_database_path.sqlite3, "connect", fail_connection)
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        migrate_database_path.copy_database(source, destination)
    assert not destination.exists()
    monkeypatch.setattr(migrate_database_path.sqlite3, "connect", real_connect)
