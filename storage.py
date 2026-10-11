"""Private Google Drive storage with SQLite-backed file metadata."""

import asyncio
import hashlib
import mimetypes
import os
import tempfile
import threading
import time
import uuid
import weakref
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message

from config import (
    GOOGLE_DRIVE_CLIENT_ID,
    GOOGLE_DRIVE_CLIENT_SECRET,
    GOOGLE_DRIVE_FOLDER_ID,
    GOOGLE_DRIVE_REFRESH_TOKEN,
)
from database import db_session, db_write_session
from logger import logger

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_TEMP_DIR = Path(tempfile.gettempdir()) / "brochure_drive"
_MAX_RETRIES = 3
_token_lock = threading.Lock()
_access_token: str | None = None
_access_token_expiry: datetime | None = None
_asset_upload_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


class StorageConfigurationError(RuntimeError):
    """Raised when Google Drive credentials are missing or invalid."""


class StoredFileNotFoundError(FileNotFoundError):
    """Raised when a file or its private Drive object no longer exists."""


@dataclass(frozen=True)
class StoredFile:
    id: str
    drive_file_id: str
    source_key: str
    telegram_file_id: str
    telegram_file_unique_id: str
    original_filename: str
    mime_type: str
    file_size: int | None
    md5_checksum: str
    uploaded_by: int | None
    purpose: str
    created_at: str
    verified_at: str | None


def _safe_filename(filename: str) -> str:
    cleaned = (filename or "upload").replace("\\", "/").split("/")[-1]
    cleaned = "".join(
        char for char in cleaned
        if char.isprintable() and char not in '<>:"|?*'
    ).strip(" .")
    return cleaned[:180] or "upload"


def _build_drive_service():
    if not all(
        (
            GOOGLE_DRIVE_CLIENT_ID,
            GOOGLE_DRIVE_CLIENT_SECRET,
            GOOGLE_DRIVE_REFRESH_TOKEN,
        )
    ):
        raise StorageConfigurationError(
            "Google Drive OAuth is not configured. Set "
            "GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, and "
            "GOOGLE_DRIVE_REFRESH_TOKEN."
        )

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        global _access_token, _access_token_expiry
        with _token_lock:
            now = datetime.now(timezone.utc)
            if (
                not _access_token
                or _access_token_expiry is None
                or _access_token_expiry <= now + timedelta(minutes=5)
            ):
                credentials = Credentials(
                    token=None,
                    refresh_token=GOOGLE_DRIVE_REFRESH_TOKEN,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_DRIVE_CLIENT_ID,
                    client_secret=GOOGLE_DRIVE_CLIENT_SECRET,
                    scopes=[_DRIVE_SCOPE],
                )
                credentials.refresh(Request())
                _access_token = credentials.token
                _access_token_expiry = credentials.expiry
            credentials = Credentials(
                token=_access_token,
                refresh_token=GOOGLE_DRIVE_REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_DRIVE_CLIENT_ID,
                client_secret=GOOGLE_DRIVE_CLIENT_SECRET,
                scopes=[_DRIVE_SCOPE],
                expiry=_access_token_expiry,
            )
        return build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
    except StorageConfigurationError:
        raise
    except Exception as exc:
        logger.error("Google Drive authentication failed (%s)", type(exc).__name__)
        raise StorageConfigurationError(
            "Google Drive authentication failed; verify OAuth variables and consent."
        ) from exc


def _drive_idempotency_key(source_key: str) -> str:
    return hashlib.sha256(source_key.encode("utf-8")).hexdigest()


def _find_remote_file(service, source_key: str) -> dict | None:
    key = _drive_idempotency_key(source_key)
    response = service.files().list(
        q=f"appProperties has {{ key='brochureSource' and value='{key}' }} "
          "and trashed = false",
        spaces="drive",
        pageSize=2,
        fields="files(id,name,mimeType,size,md5Checksum,createdTime,appProperties)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute(num_retries=_MAX_RETRIES)
    files = response.get("files", [])
    if len(files) > 1:
        logger.error("Duplicate Drive objects found for one Brochure source key.")
    return files[0] if files else None


def _get_or_create_app_folder(service) -> str:
    if GOOGLE_DRIVE_FOLDER_ID:
        return GOOGLE_DRIVE_FOLDER_ID
    response = service.files().list(
        q="mimeType = 'application/vnd.google-apps.folder' "
          "and appProperties has { key='brochureFolder' and value='v1' } "
          "and trashed = false",
        spaces="drive",
        pageSize=1,
        fields="files(id)",
    ).execute(num_retries=_MAX_RETRIES)
    folders = response.get("files", [])
    if folders:
        return folders[0]["id"]
    folder = service.files().create(
        body={
            "name": "Brochure",
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"brochureFolder": "v1"},
        },
        fields="id",
    ).execute(num_retries=_MAX_RETRIES)
    if not folder.get("id"):
        raise RuntimeError("Google Drive did not return the Brochure folder ID.")
    return folder["id"]


def _get_remote_metadata(service, drive_file_id: str) -> dict | None:
    try:
        return service.files().get(
            fileId=drive_file_id,
            fields="id,name,mimeType,size,md5Checksum,createdTime",
            supportsAllDrives=True,
        ).execute(num_retries=_MAX_RETRIES)
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 404:
            return None
        raise


async def _find_asset(source_key: str) -> StoredFile | None:
    async with db_session() as db:
        row = await db.execute_fetchall(
            "SELECT * FROM stored_files WHERE source_key = ?",
            (source_key,),
        )
    return StoredFile(**dict(row[0])) if row else None


def _get_remote_metadata_sync(drive_file_id: str) -> dict | None:
    service = _build_drive_service()
    return _get_remote_metadata(service, drive_file_id)


async def get_stored_file(stored_file_id: str | None) -> StoredFile | None:
    if not stored_file_id:
        return None
    async with db_session() as db:
        row = await db.execute_fetchall(
            "SELECT * FROM stored_files WHERE id = ?",
            (stored_file_id,),
        )
    return StoredFile(**dict(row[0])) if row else None


async def find_stored_file_by_source_key(source_key: str) -> StoredFile | None:
    return await _find_asset(source_key)


async def _persist_asset(
    *,
    stored_id: str,
    source_key: str,
    remote: dict,
    telegram_file_id: str,
    telegram_file_unique_id: str,
    original_filename: str,
    mime_type: str,
    uploaded_by: int | None,
    purpose: str,
) -> StoredFile:
    try:
        file_size = int(remote["size"]) if remote.get("size") is not None else None
    except (TypeError, ValueError):
        file_size = None
    remote_name = _safe_filename(remote.get("name") or original_filename)
    remote_mime = remote.get("mimeType") or mime_type or "application/octet-stream"
    async with db_write_session() as db:
        await db.execute(
            """INSERT INTO stored_files
            (id, drive_file_id, source_key, telegram_file_id,
             telegram_file_unique_id, original_filename, mime_type, file_size,
             md5_checksum, uploaded_by, purpose, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_key) DO UPDATE SET
                drive_file_id = excluded.drive_file_id,
                telegram_file_id = excluded.telegram_file_id,
                telegram_file_unique_id = excluded.telegram_file_unique_id,
                original_filename = excluded.original_filename,
                mime_type = excluded.mime_type,
                file_size = excluded.file_size,
                md5_checksum = excluded.md5_checksum,
                uploaded_by = excluded.uploaded_by,
                purpose = excluded.purpose,
                verified_at = CURRENT_TIMESTAMP""",
            (
                stored_id,
                remote["id"],
                source_key,
                telegram_file_id,
                telegram_file_unique_id,
                remote_name,
                remote_mime,
                file_size,
                remote.get("md5Checksum") or "",
                uploaded_by,
                purpose,
            ),
        )
        await db.commit()
        row = await db.execute_fetchall(
            "SELECT * FROM stored_files WHERE source_key = ?",
            (source_key,),
        )
    return StoredFile(**dict(row[0]))


def _upload_local_file_sync(
    path: Path,
    *,
    source_key: str,
    original_filename: str,
    mime_type: str,
) -> dict:
    service = _build_drive_service()
    remote = _find_remote_file(service, source_key)
    if remote is not None:
        verified = _get_remote_metadata(service, remote["id"])
        if verified is not None:
            return verified

    from googleapiclient.http import MediaFileUpload

    folder_id = _get_or_create_app_folder(service)
    metadata: dict = {
        "name": _safe_filename(original_filename),
        "mimeType": mime_type or "application/octet-stream",
        "appProperties": {
            "brochureSource": _drive_idempotency_key(source_key),
        },
        "parents": [folder_id],
    }

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            media = MediaFileUpload(
                str(path),
                mimetype=metadata["mimeType"],
                resumable=True,
                chunksize=5 * 1024 * 1024,
            )
            request = service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,mimeType,size,md5Checksum,createdTime",
                supportsAllDrives=True,
            )
            uploaded = None
            while uploaded is None:
                _, uploaded = request.next_chunk(num_retries=_MAX_RETRIES)
            if not uploaded.get("id"):
                raise RuntimeError("Google Drive upload returned no file ID.")
            verified = _get_remote_metadata(service, uploaded["id"])
            if verified is None:
                raise StoredFileNotFoundError(
                    "Uploaded Google Drive file could not be verified."
                )
            return verified
        except Exception as exc:
            last_error = exc
            try:
                remote = _find_remote_file(service, source_key)
                if remote is not None:
                    verified = _get_remote_metadata(service, remote["id"])
                    if verified is not None:
                        return verified
            except Exception as lookup_exc:
                logger.warning(
                    "Drive retry lookup failed (%s)",
                    type(lookup_exc).__name__,
                )
            if attempt + 1 < _MAX_RETRIES:
                time.sleep(min(2**attempt, 8))

    logger.error(
        "Google Drive upload failed for source %s (%s)",
        _drive_idempotency_key(source_key)[:12],
        type(last_error).__name__ if last_error else "unknown",
    )
    raise RuntimeError("Google Drive upload failed after retries.") from last_error


async def upload_file(
    path: str | Path,
    *,
    source_key: str,
    original_filename: str,
    mime_type: str | None = None,
    telegram_file_id: str = "",
    telegram_file_unique_id: str = "",
    uploaded_by: int | None = None,
    purpose: str,
) -> StoredFile:
    lock = _asset_upload_locks.setdefault(source_key, asyncio.Lock())
    async with lock:
        return await _upload_file_locked(
            path,
            source_key=source_key,
            original_filename=original_filename,
            mime_type=mime_type,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            uploaded_by=uploaded_by,
            purpose=purpose,
        )


async def _upload_file_locked(
    path: str | Path,
    *,
    source_key: str,
    original_filename: str,
    mime_type: str | None,
    telegram_file_id: str,
    telegram_file_unique_id: str,
    uploaded_by: int | None,
    purpose: str,
) -> StoredFile:
    local_path = Path(path)
    if not local_path.is_file():
        raise FileNotFoundError(f"Upload source is not a file: {local_path}")
    safe_name = _safe_filename(original_filename or local_path.name)
    resolved_mime = mime_type or mimetypes.guess_type(safe_name)[0]
    resolved_mime = resolved_mime or "application/octet-stream"
    existing = await _find_asset(source_key)
    if existing is not None:
        remote = await asyncio.to_thread(
            _get_remote_metadata_sync, existing.drive_file_id
        )
        if remote is not None:
            return existing

    remote = await asyncio.to_thread(
        _upload_local_file_sync,
        local_path,
        source_key=source_key,
        original_filename=safe_name,
        mime_type=resolved_mime,
    )
    stored_id = existing.id if existing else str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"brochure:{source_key}")
    )
    return await _persist_asset(
        stored_id=stored_id,
        source_key=source_key,
        remote=remote,
        telegram_file_id=telegram_file_id,
        telegram_file_unique_id=telegram_file_unique_id,
        original_filename=safe_name,
        mime_type=resolved_mime,
        uploaded_by=uploaded_by,
        purpose=purpose,
    )


async def upload_telegram_file(
    bot: Bot,
    *,
    telegram_file_id: str,
    telegram_file_unique_id: str = "",
    original_filename: str,
    mime_type: str | None = None,
    file_size: int | None = None,
    uploaded_by: int | None = None,
    purpose: str,
    source_key: str | None = None,
) -> StoredFile:
    if source_key is None:
        stable_source = telegram_file_unique_id or hashlib.sha256(
            telegram_file_id.encode("utf-8")
        ).hexdigest()
        source_key = f"telegram:{stable_source}"
    existing = await _find_asset(source_key)
    if existing is not None:
        remote = await asyncio.to_thread(
            _get_remote_metadata_sync, existing.drive_file_id
        )
        if remote is not None:
            return existing

    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(_safe_filename(original_filename)).suffix[:16]
    fd, raw_path = tempfile.mkstemp(prefix="upload_", suffix=suffix, dir=_TEMP_DIR)
    os.close(fd)
    local_path = Path(raw_path)
    try:
        await bot.download(telegram_file_id, destination=local_path)
        actual_size = local_path.stat().st_size
        if actual_size <= 0:
            raise ValueError("Telegram returned an empty file.")
        if file_size and actual_size != file_size:
            logger.warning(
                "Telegram file size differs from metadata for source %s",
                _drive_idempotency_key(source_key)[:12],
            )
        return await upload_file(
            local_path,
            source_key=source_key,
            original_filename=original_filename,
            mime_type=mime_type,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            uploaded_by=uploaded_by,
            purpose=purpose,
        )
    finally:
        local_path.unlink(missing_ok=True)


def telegram_source_key(
    telegram_file_id: str,
    telegram_file_unique_id: str = "",
) -> str:
    stable_source = telegram_file_unique_id or hashlib.sha256(
        telegram_file_id.encode("utf-8")
    ).hexdigest()
    return f"telegram:{stable_source}"


async def upload_generated_file(
    path: str | Path,
    *,
    uploaded_by: int | None,
    purpose: str,
    original_filename: str | None = None,
    mime_type: str | None = None,
) -> StoredFile:
    local_path = Path(path)
    digest = await asyncio.to_thread(_sha256, local_path)
    return await upload_file(
        local_path,
        source_key=f"generated:{purpose}:{digest}",
        original_filename=original_filename or local_path.name,
        mime_type=mime_type,
        uploaded_by=uploaded_by,
        purpose=purpose,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_drive_file_sync(drive_file_id: str, destination: Path) -> None:
    service = _build_drive_service()
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(
        fileId=drive_file_id,
        supportsAllDrives=True,
    )
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=5 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=_MAX_RETRIES)


async def download_file(
    stored_file_id: str,
    destination: str | Path | None = None,
) -> Path:
    stored = await get_stored_file(stored_file_id)
    if stored is None:
        raise StoredFileNotFoundError(f"Stored file {stored_file_id} is not registered.")
    if destination is None:
        _TEMP_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(stored.original_filename).suffix[:16]
        fd, raw_path = tempfile.mkstemp(prefix="download_", suffix=suffix, dir=_TEMP_DIR)
        os.close(fd)
        output_path = Path(raw_path)
    else:
        output_path = Path(destination)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await asyncio.to_thread(
            _download_drive_file_sync,
            stored.drive_file_id,
            output_path,
        )
        if output_path.stat().st_size == 0:
            raise StoredFileNotFoundError("Google Drive returned an empty file.")
        return output_path
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


async def get_file_metadata(stored_file_id: str) -> StoredFile:
    stored = await get_stored_file(stored_file_id)
    if stored is None:
        raise StoredFileNotFoundError(f"Stored file {stored_file_id} is not registered.")
    service = await asyncio.to_thread(_build_drive_service)
    remote = await asyncio.to_thread(
        _get_remote_metadata, service, stored.drive_file_id
    )
    if remote is None:
        raise StoredFileNotFoundError("Google Drive file is missing.")
    return stored


async def file_exists(stored_file_id: str) -> bool:
    try:
        await get_file_metadata(stored_file_id)
        return True
    except StoredFileNotFoundError:
        return False


async def delete_file(stored_file_id: str) -> None:
    stored = await get_stored_file(stored_file_id)
    if stored is None:
        return
    async with db_session() as db:
        references = await db.execute_fetchall(
            """SELECT 1 FROM notes WHERE storage_file_id = ?
               UNION ALL
               SELECT 1 FROM tasks WHERE storage_file_id = ?
               LIMIT 1""",
            (stored_file_id, stored_file_id),
        )
    if references:
        raise ValueError("Cannot delete a Drive file that is linked to a note or task.")
    service = await asyncio.to_thread(_build_drive_service)
    await asyncio.to_thread(
        service.files().delete(
            fileId=stored.drive_file_id,
            supportsAllDrives=True,
        ).execute,
        num_retries=_MAX_RETRIES,
    )
    async with db_write_session() as db:
        await db.execute(
            "DELETE FROM stored_files WHERE id = ?",
            (stored_file_id,),
        )
        await db.commit()


def _send_method(message: Message, file_type: str):
    method_name = {
        "photo": "answer_photo",
        "video": "answer_video",
        "voice": "answer_voice",
    }.get(file_type, "answer_document")
    return getattr(message, method_name)


async def send_stored_file(
    message: Message,
    *,
    telegram_file_id: str | None,
    storage_file_id: str | None,
    file_type: str,
    caption: str,
) -> None:
    send = _send_method(message, file_type)
    if telegram_file_id:
        try:
            await send(telegram_file_id, caption=caption)
            return
        except TelegramBadRequest as exc:
            if not storage_file_id:
                raise
            logger.warning(
                "Telegram file reference failed; trying Drive fallback (%s)",
                type(exc).__name__,
            )
    if not storage_file_id:
        raise StoredFileNotFoundError("No Telegram or Google Drive file reference.")

    stored = await get_stored_file(storage_file_id)
    if stored is None:
        raise StoredFileNotFoundError("Stored file metadata is missing.")
    local_path = await download_file(storage_file_id)
    try:
        await send(
            FSInputFile(local_path, filename=stored.original_filename),
            caption=caption,
        )
    finally:
        local_path.unlink(missing_ok=True)
