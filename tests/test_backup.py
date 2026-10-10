import asyncio
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backup
import scheduler


def _make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE user_data (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO user_data (value) VALUES (?)", ("persisted value",)
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_archive_contains_consistent_database_and_verified_manifest(tmp_path):
    db_path = tmp_path / "active.db"
    _make_database(db_path)
    backup_dir = tmp_path / "backups"
    secret_file = tmp_path / ".env"
    secret_file.write_text("BOT_TOKEN=must-not-be-included", encoding="utf-8")
    source_file = tmp_path / "handler.py"
    source_file.write_text("print('not backup data')", encoding="utf-8")

    result = await backup.create_backup_archive(
        db_path,
        backup_dir,
        datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
    )

    with zipfile.ZipFile(result.path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "database/main_database.db",
            "backup_manifest.json",
        }
        manifest = json.loads(archive.read("backup_manifest.json"))
        assert manifest["database_integrity_check"] == "ok"
        assert manifest["archive_crc_check"] == "passed"
        assert manifest["file_count"] == len(archive.namelist()) == 2
        assert manifest["payload_file_count"] == 1
        db_entry = next(
            item
            for item in manifest["files"]
            if item["path"] == "database/main_database.db"
        )
        manifest_entry = next(
            item
            for item in manifest["files"]
            if item["path"] == "backup_manifest.json"
        )
        assert manifest_entry["size_bytes"] == len(
            archive.read("backup_manifest.json")
        )
        assert manifest_entry["sha256"] is None
        db_bytes = archive.read(db_entry["path"])
        assert len(db_bytes) == db_entry["size_bytes"]
        assert hashlib.sha256(db_bytes).hexdigest() == db_entry["sha256"]

    restored = tmp_path / "restored.db"
    restored.write_bytes(db_bytes)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM user_data").fetchone()[0] == (
            "persisted value"
        )
    assert secret_file.read_bytes() not in db_bytes
    assert source_file.read_bytes() not in db_bytes
    assert result.file_count == 2
    assert result.size_bytes == result.path.stat().st_size


@pytest.mark.asyncio
async def test_archive_includes_committed_wal_data_while_database_is_open(tmp_path):
    db_path = tmp_path / "active.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "CREATE TABLE user_data (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO user_data (value) VALUES (?)", ("committed in WAL",)
        )
        connection.commit()
        wal_path = Path(f"{db_path}-wal")
        assert wal_path.is_file() and wal_path.stat().st_size > 0

        result = await backup.create_backup_archive(
            db_path, tmp_path / "backups"
        )
        with zipfile.ZipFile(result.path) as archive:
            restored = tmp_path / "from_wal.db"
            restored.write_bytes(archive.read("database/main_database.db"))
        with sqlite3.connect(restored) as restored_db:
            assert restored_db.execute(
                "SELECT value FROM user_data"
            ).fetchone()[0] == "committed in WAL"
    finally:
        connection.close()


class _FakeBot:
    def __init__(self, fail_document: bool = False):
        self.fail_document = fail_document
        self.documents = []
        self.messages = []

    async def send_document(self, *, chat_id, document, caption):
        self.documents.append((chat_id, Path(document.path), caption))
        if self.fail_document:
            raise OSError("simulated network outage")

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_delivery_failure_keeps_archive_and_reports_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "active.db"
    _make_database(db_path)
    bot = _FakeBot(fail_document=True)
    monkeypatch.setattr(backup, "MAIN_ADMIN_ID", 12345)

    result = await backup.run_backup_once(bot, db_path, tmp_path / "backups")

    assert result is not None and not result.delivered
    assert result.archive.path.is_file()
    assert bot.documents[0][0] == 12345
    assert bot.messages[0][0] == 12345
    assert "ناموفق" in bot.messages[0][1]


@pytest.mark.asyncio
async def test_delivery_success_sends_document_and_preserves_latest_backup(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "active.db"
    _make_database(db_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    previous = backup_dir / "Brochure_Backup_2026-10-09_120000.zip"
    previous.write_bytes(b"older archive")
    bot = _FakeBot()
    monkeypatch.setattr(backup, "MAIN_ADMIN_ID", 54321)

    result = await backup.run_backup_once(bot, db_path, backup_dir)

    assert result is not None and result.delivered
    assert result.archive.path.is_file()
    assert not previous.exists()
    assert bot.documents[0][0] == 54321
    assert "وضعیت: موفق" in bot.documents[0][2]


@pytest.mark.asyncio
async def test_parallel_backup_request_is_skipped_while_delivery_is_in_progress(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "active.db"
    _make_database(db_path)
    monkeypatch.setattr(backup, "MAIN_ADMIN_ID", 54321)

    class _PausedBot(_FakeBot):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.finish = asyncio.Event()

        async def send_document(self, *, chat_id, document, caption):
            self.started.set()
            await self.finish.wait()
            await super().send_document(
                chat_id=chat_id, document=document, caption=caption
            )

    bot = _PausedBot()
    task = asyncio.create_task(
        backup.run_backup_once(bot, db_path, tmp_path / "backups")
    )
    try:
        await bot.started.wait()
        assert await backup.run_backup_once(
            bot, db_path, tmp_path / "backups"
        ) is None
    finally:
        bot.finish.set()
    result = await task
    assert result is not None and result.delivered


@pytest.mark.asyncio
async def test_backup_scheduler_is_singleton_and_stops_cleanly(monkeypatch):
    calls = 0
    bot = object()

    async def fake_run_backup(received_bot):
        nonlocal calls
        assert received_bot is bot
        calls += 1

    monkeypatch.setattr(scheduler.backup, "BACKUP_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(scheduler.backup, "run_backup_once", fake_run_backup)
    try:
        first = scheduler.start_backup_scheduler(bot)
        second = scheduler.start_backup_scheduler(bot)
        assert first is second
        await asyncio.sleep(0.035)
    finally:
        await scheduler.stop_backup_scheduler()

    assert calls >= 1
    assert first.done()
