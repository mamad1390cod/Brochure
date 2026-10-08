"""
Inline search handler for Bot-File-School.
Allows users to search notes via Telegram inline mode.
Uses async database access so the event loop is never blocked.
"""

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from config import ENABLE_INLINE_SEARCH, INLINE_SEARCH_ALLOWED_USERS
import models
from utils import format_page_range, escape_html

router = Router()


@router.inline_query()
async def inline_search_handler(query: InlineQuery):
    """Handle inline search queries."""
    if not ENABLE_INLINE_SEARCH:
        return

    search_text = query.query.strip()

    # Check if inline search is restricted to specific users
    if INLINE_SEARCH_ALLOWED_USERS:
        user_id_str = str(query.from_user.id)
        if user_id_str not in INLINE_SEARCH_ALLOWED_USERS:
            await query.answer(
                results=[],
                cache_time=0,
                switch_pm_text="🔒 جستجو برای شما محدود است",
                switch_pm_parameter="inline_denied",
            )
            return

    if not search_text:
        rows = await models.get_recent_notes(limit=10)
    else:
        rows = await models.search_notes(search_text, limit=50)

    results = [_build_inline_result(row) for row in rows]

    await query.answer(
        results=results[:50],  # Telegram limit
        cache_time=30,
        switch_pm_text="📚 مشاهده جزوه‌ها",
        switch_pm_parameter="inline_results",
    )


def _build_inline_result(row) -> InlineQueryResultArticle:
    """Build an inline query result from a database row."""
    title = escape_html(row["title"])
    field_name = row["field_name"] or ""
    subject_name = row["subject_name"] or ""
    chapter_name = row["chapter_name"] or "بدون فصل"
    page_text = format_page_range(row["page_start"], row["page_end"])
    file_type = row["file_type"] or ""

    description_parts = []
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

    description = " | ".join(description_parts) if description_parts else "جزوه"

    # Build the message content
    message_text = (
        f"📄 <b>{title}</b>\n\n"
        f"📚 رشته: {escape_html(field_name)}\n"
        f"📖 درس: {escape_html(subject_name)}\n"
        f"📕 فصل: {escape_html(chapter_name)}\n"
        f"📄 صفحات: {page_text}\n"
        f"📎 نوع: {file_type}\n"
    )
    if row["description"]:
        message_text += f"\n📝 {escape_html(row['description'])}\n"

    return InlineQueryResultArticle(
        id=str(row["id"]),
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(
            message_text=message_text,
            parse_mode="HTML",
        ),
    )
