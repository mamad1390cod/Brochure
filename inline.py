"""
Inline search handler for Bot-File-School.
Allows users to search notes via Telegram inline mode.
Uses async database access so the event loop is never blocked.
"""

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedVoice,
    InlineQueryResultUnion,
)
from config import ENABLE_INLINE_SEARCH, INLINE_SEARCH_ALLOWED_USERS
import models
from utils import format_page_range

router = Router()
_INLINE_RESULT_DESCRIPTION_LIMIT = 256
_INLINE_CAPTION_LIMIT = 1024
_INLINE_TITLE_LIMIT = 64


def _truncate_utf16(text: str, limit: int) -> str:
    """Keep Telegram's UTF-16 length limits without splitting Unicode code points."""
    if len(text.encode("utf-16-le")) // 2 <= limit:
        return text

    output: list[str] = []
    units = 0
    for char in text:
        char_units = len(char.encode("utf-16-le")) // 2
        if units + char_units > limit - 1:
            break
        output.append(char)
        units += char_units
    return "".join(output) + "…"


@router.inline_query()
async def inline_search_handler(query: InlineQuery):
    """Handle inline search queries."""
    if not ENABLE_INLINE_SEARCH:
        await query.answer(results=[], cache_time=0, is_personal=True)
        return

    search_text = query.query.strip()

    # Check if inline search is restricted to specific users
    if INLINE_SEARCH_ALLOWED_USERS:
        user_id_str = str(query.from_user.id)
        if user_id_str not in INLINE_SEARCH_ALLOWED_USERS:
            await query.answer(
                results=[],
                cache_time=0,
                is_personal=True,
            )
            return

    if not search_text:
        rows = await models.get_recent_notes(limit=10)
    else:
        rows = await models.search_notes(search_text, limit=50)

    results = [
        result
        for row in rows
        if (result := _build_inline_result(row)) is not None
    ]

    await query.answer(
        results=results[:50],  # Telegram limit
        cache_time=30,
        is_personal=True,
    )


def _build_inline_result(row) -> InlineQueryResultUnion | None:
    """Build a cached-media result using the Telegram ID retained with the note."""
    file_id = (row["file_id"] or row["storage_telegram_file_id"] or "").strip()
    if not file_id:
        return None

    title = row["title"] or "بدون عنوان"
    field_name = row["field_name"] or ""
    subject_name = row["subject_name"] or ""
    chapter_name = row["chapter_name"] or "بدون فصل"
    page_text = format_page_range(row["page_start"], row["page_end"])
    file_type = row["file_type"] or ""

    description_parts: list[str] = []
    if field_name:
        description_parts.append(f"📚 {field_name}")
    if subject_name:
        description_parts.append(f"📖 {subject_name}")
    if chapter_name and chapter_name != "بدون فصل":
        description_parts.append(f"📕 {chapter_name}")
    if page_text != "—":
        description_parts.append(f"📄 صفحه {page_text}")
    if file_type:
        description_parts.append(f"📎 {file_type}")

    description = _truncate_utf16(
        " | ".join(description_parts) if description_parts else "جزوه",
        _INLINE_RESULT_DESCRIPTION_LIMIT,
    )

    caption_parts = [
        f"📄 {title}",
        f"📚 رشته: {field_name}",
        f"📖 درس: {subject_name}",
        f"📕 فصل: {chapter_name}",
        f"📄 صفحات: {page_text}",
        f"📎 نوع: {file_type}",
    ]
    if row["description"]:
        caption_parts.append(f"📝 {row['description']}")
    caption = _truncate_utf16("\n".join(caption_parts), _INLINE_CAPTION_LIMIT)

    result_id = str(row["id"])
    result_title = _truncate_utf16(title, _INLINE_TITLE_LIMIT)
    common = {
        "id": result_id,
        "caption": caption,
        "parse_mode": None,
    }
    if file_type == "photo":
        return InlineQueryResultCachedPhoto(
            **common,
            photo_file_id=file_id,
            title=result_title,
            description=description,
        )
    if file_type == "video":
        return InlineQueryResultCachedVideo(
            **common,
            video_file_id=file_id,
            title=result_title,
            description=description,
        )
    if file_type == "audio":
        return InlineQueryResultCachedAudio(**common, audio_file_id=file_id)
    if file_type == "voice":
        return InlineQueryResultCachedVoice(
            **common,
            voice_file_id=file_id,
            title=result_title,
        )
    return InlineQueryResultCachedDocument(
        **common,
        document_file_id=file_id,
        title=result_title,
        description=description,
    )
