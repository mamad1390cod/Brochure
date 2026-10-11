"""Resumably copy legacy Telegram-hosted note and homework media to Drive."""

import asyncio
import logging

from aiogram import Bot

import storage
from config import BOT_TOKEN
from database import db_session, db_write_session, init_database
from logger import logger

BATCH_SIZE = 100


async def _legacy_rows(table: str, after_id: int):
    if table == "notes":
        query = """SELECT id, file_id, file_unique_id, file_name, mime_type,
                          file_size, submitted_by AS uploaded_by
                   FROM notes
                   WHERE file_id IS NOT NULL AND file_id != ''
                     AND (storage_file_id IS NULL OR storage_file_id = '')
                     AND id > ?
                   ORDER BY id LIMIT ?"""
    elif table == "tasks":
        query = """SELECT id, file_id, '' AS file_unique_id, title AS file_name,
                          'image/*' AS mime_type, NULL AS file_size,
                          created_by AS uploaded_by
                   FROM tasks
                   WHERE file_id IS NOT NULL AND file_id != ''
                     AND (storage_file_id IS NULL OR storage_file_id = '')
                     AND id > ?
                   ORDER BY id LIMIT ?"""
    else:
        raise ValueError(f"Unsupported legacy file table: {table}")

    async with db_session() as db:
        return await db.execute_fetchall(query, (after_id, BATCH_SIZE))


async def _link_file(table: str, row_id: int, stored_file_id: str) -> None:
    if table not in {"notes", "tasks"}:
        raise ValueError(f"Unsupported legacy file table: {table}")
    async with db_write_session() as db:
        await db.execute(
            f"""UPDATE {table} SET storage_file_id = ?
                WHERE id = ? AND (storage_file_id IS NULL OR storage_file_id = '')""",
            (stored_file_id, row_id),
        )
        await db.commit()


async def migrate_legacy_files() -> tuple[int, int, int]:
    await init_database()
    bot = Bot(token=BOT_TOKEN)
    migrated = 0
    failed = 0
    failures: list[str] = []
    try:
        for table in ("notes", "tasks"):
            after_id = 0
            while True:
                rows = await _legacy_rows(table, after_id)
                if not rows:
                    break
                for row in rows:
                    row_id = int(row["id"])
                    after_id = row_id
                    try:
                        stored = await storage.upload_telegram_file(
                            bot,
                            telegram_file_id=row["file_id"],
                            telegram_file_unique_id=row["file_unique_id"] or "",
                            original_filename=row["file_name"] or f"{table}_{row_id}",
                            mime_type=(
                                row["mime_type"]
                                if table == "notes"
                                else "application/octet-stream"
                            ),
                            file_size=row["file_size"],
                            uploaded_by=row["uploaded_by"],
                            purpose="note" if table == "notes" else "homework",
                        )
                        await _link_file(table, row_id, stored.id)
                        migrated += 1
                    except Exception as exc:
                        failed += 1
                        failures.append(
                            f"{table}#{row_id}: {type(exc).__name__}"
                        )
                        logger.error(
                            "Legacy file migration failed for %s row %s (%s)",
                            table,
                            row_id,
                            type(exc).__name__,
                        )
    finally:
        await bot.session.close()

    for failure in failures:
        print(f"FAILED {failure}")
    print(
        f"Migration summary: migrated={migrated}, "
        f"failed={failed}, skipped=0"
    )
    return migrated, failed, 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate_legacy_files())
