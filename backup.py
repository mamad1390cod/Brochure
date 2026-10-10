"""Create and deliver verified backups of persistent Brochure user data."""

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import FSInputFile

from config import DATABASE_PATH, MAIN_ADMIN_ID
from logger import logger

BACKUP_INTERVAL_SECONDS = 4 * 60 * 60
BACKUP_DIR = Path(DATABASE_PATH).parent / "backups"
BACKUP_TIMEZONE = ZoneInfo("Asia/Tehran")
_backup_lock = asyncio.Lock()


class BackupAlreadyRunningError(RuntimeError):
    """Raised when another process currently owns the backup lock."""


@dataclass(frozen=True)
class BackupArchive:
    path: Path
    created_at: datetime
    size_bytes: int
    file_count: int
    sha256: str


@dataclass(frozen=True)
class BackupResult:
    archive: BackupArchive
    delivered: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_backup_archive_sync(
    database_path: Path,
    backup_dir: Path,
    created_at: datetime,
) -> BackupArchive:
    database_path = Path(database_path)
    backup_dir = Path(backup_dir)
    if not database_path.is_file():
        raise FileNotFoundError(f"Configured database is not a file: {database_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = created_at.astimezone(BACKUP_TIMEZONE).strftime("%Y-%m-%d_%H%M%S")
    archive_path = backup_dir / f"Brochure_Backup_{timestamp}.zip"
    if archive_path.exists():
        raise FileExistsError(f"Backup already exists for {timestamp}")

    with tempfile.TemporaryDirectory(prefix=".brochure_backup_", dir=backup_dir) as temp:
        temp_dir = Path(temp)
        snapshot_path = temp_dir / "main_database.db"
        partial_archive = temp_dir / f"{archive_path.name}.part"

        source = sqlite3.connect(database_path, timeout=30)
        snapshot = sqlite3.connect(snapshot_path, timeout=30)
        try:
            source.execute("PRAGMA busy_timeout=30000")
            snapshot.execute("PRAGMA busy_timeout=30000")
            source.backup(snapshot, pages=256, sleep=0.01)
            integrity = snapshot.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise sqlite3.DatabaseError("Database snapshot integrity check failed")
            snapshot.commit()
        finally:
            snapshot.close()
            source.close()

        db_entry = {
            "path": "database/main_database.db",
            "size_bytes": snapshot_path.stat().st_size,
            "sha256": _sha256(snapshot_path),
        }
        manifest = {
            "project": "Brochure",
            "created_at": created_at.isoformat(),
            "backup_format_version": 1,
            "file_count": 2,
            "payload_file_count": 1,
            "files": [
                db_entry,
                {
                    "path": "backup_manifest.json",
                    "size_bytes": 0,
                    "sha256": None,
                },
            ],
            "database_integrity_check": "ok",
            "archive_crc_check": "passed",
            "notes": [
                "Uploaded note and homework media are stored by Telegram; "
                "the database contains their Telegram file identifiers.",
                "Temporary conversion files, source code, logs, and secrets "
                "are intentionally excluded.",
            ],
        }
        manifest_path = temp_dir / "backup_manifest.json"
        for _ in range(5):
            manifest_bytes = (
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            manifest["files"][1]["size_bytes"] = len(manifest_bytes)
            verified_bytes = (
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            if len(verified_bytes) == manifest["files"][1]["size_bytes"]:
                manifest_bytes = verified_bytes
                break
        else:
            raise RuntimeError("Could not resolve manifest's own archive size")
        manifest_path.write_bytes(manifest_bytes)

        with zipfile.ZipFile(
            partial_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(snapshot_path, db_entry["path"])
            archive.write(manifest_path, "backup_manifest.json")

        with zipfile.ZipFile(partial_archive, "r") as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise zipfile.BadZipFile(f"ZIP CRC check failed for {bad_entry}")
            if set(archive.namelist()) != {
                db_entry["path"],
                "backup_manifest.json",
            }:
                raise zipfile.BadZipFile("Unexpected entry in backup archive")

        os.replace(partial_archive, archive_path)

    return BackupArchive(
        path=archive_path,
        created_at=created_at,
        size_bytes=archive_path.stat().st_size,
        file_count=2,
        sha256=_sha256(archive_path),
    )


async def create_backup_archive(
    database_path: Path = DATABASE_PATH,
    backup_dir: Path = BACKUP_DIR,
    created_at: datetime | None = None,
) -> BackupArchive:
    """Snapshot SQLite and build a verified ZIP without blocking the event loop."""
    timestamp = created_at or datetime.now().astimezone()
    return await asyncio.to_thread(
        _create_backup_archive_sync,
        Path(database_path),
        Path(backup_dir),
        timestamp,
    )


def _remove_old_archives(backup_dir: Path, keep: Path) -> None:
    for old_archive in backup_dir.glob("Brochure_Backup_*.zip"):
        if old_archive != keep:
            try:
                old_archive.unlink()
            except OSError as exc:
                logger.warning(
                    "Could not remove superseded backup %s (%s)",
                    old_archive.name,
                    type(exc).__name__,
                )


def _success_caption(archive: BackupArchive) -> str:
    timestamp = archive.created_at.astimezone(BACKUP_TIMEZONE).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    size_mb = archive.size_bytes / (1024 * 1024)
    return (
        "✅ بکاپ خودکار Brochure با موفقیت ایجاد و ارسال شد.\n\n"
        f"زمان بکاپ: {timestamp}\n"
        f"حجم فایل: {size_mb:.2f} MB\n"
        f"تعداد فایل‌ها: {archive.file_count}\n"
        "وضعیت: موفق"
    )


@contextmanager
def _process_backup_lock(backup_dir: Path) -> Generator[None, None, None]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    lock_file = (backup_dir / ".backup.lock").open("a+b")
    acquired = False
    try:
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise BackupAlreadyRunningError from exc

        yield
    finally:
        if acquired:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()
        else:
            lock_file.close()


async def _notify_failure(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(chat_id=MAIN_ADMIN_ID, text=text)
    except Exception as exc:
        logger.error(
            "Could not notify Owner about backup failure (%s)",
            type(exc).__name__,
        )


async def _run_backup_locked(
    bot: Bot,
    database_path: Path,
    backup_dir: Path,
) -> BackupResult:
    try:
        archive = await create_backup_archive(database_path, backup_dir)
    except Exception as exc:
        logger.error(
            "Automatic backup creation failed (%s)",
            type(exc).__name__,
        )
        await _notify_failure(
            bot,
            "❌ ایجاد بکاپ خودکار Brochure ناموفق بود. "
            "جزئیات خطا در گزارش برنامه ثبت شد.",
        )
        raise

    try:
        await bot.send_document(
            chat_id=MAIN_ADMIN_ID,
            document=FSInputFile(archive.path),
            caption=_success_caption(archive),
        )
    except Exception as exc:
        logger.error(
            "Automatic backup delivery failed (%s); archive retained at %s",
            type(exc).__name__,
            archive.path,
        )
        await _notify_failure(
            bot,
            "⚠️ بکاپ Brochure ساخته و بررسی شد، اما ارسال آن ناموفق بود. "
            "فایل در محل محلی بکاپ نگه داشته شده است.",
        )
        return BackupResult(archive=archive, delivered=False)

    _remove_old_archives(Path(backup_dir), archive.path)
    return BackupResult(archive=archive, delivered=True)


async def run_backup_once(
    bot: Bot,
    database_path: Path = DATABASE_PATH,
    backup_dir: Path = BACKUP_DIR,
) -> BackupResult | None:
    """Create a backup and send it to the configured Owner."""
    if _backup_lock.locked():
        logger.warning("Skipping backup request because another backup is running.")
        return None

    async with _backup_lock:
        try:
            with _process_backup_lock(Path(backup_dir)):
                return await _run_backup_locked(
                    bot, Path(database_path), Path(backup_dir)
                )
        except BackupAlreadyRunningError:
            logger.warning(
                "Skipping backup request because another process owns the backup lock."
            )
            return None
