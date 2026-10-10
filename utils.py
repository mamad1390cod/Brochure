"""
Utility functions for Bot-File-School.
"""

from typing import Any, Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from logger import logger


async def safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs: Any,
) -> None:
    """Edit a message while treating Telegram's exact no-op response as success."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).casefold():
            raise
        logger.debug(
            "Skipped unchanged Telegram message edit (chat=%s, message=%s)",
            message.chat.id,
            message.message_id,
        )


def format_file_size(size) -> str:
    """Format a byte size into a human-readable string (KB/MB)."""
    size = size or 0
    if size >= 1024 * 1024:
        return f"{size / 1048576:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B" if size else ""


def note_file_label(note) -> str:
    """Build an inline button label for a note file: name + size."""
    title = note["title"]
    title = title[:30] + "..." if len(title) > 30 else title
    icon = {"photo": "\U0001f5bc", "video": "\U0001f3ac", "audio": "\U0001f3b5",
            "voice": "\U0001f3a4"}.get((note["file_type"] or ""), "\U0001f4c4")
    label = f"{icon} {title}"
    if isinstance(note, dict):
        raw_size = note.get("file_size", 0)
    else:
        raw_size = note["file_size"]
    size_str = format_file_size(raw_size)
    if size_str:
        label += f" | \U0001f4e6 {size_str}"
    return label


def format_note_info(note: dict) -> str:
    """Format a note's information for display (HTML-safe)."""
    lines = [
        f"📄 <b>{escape_html(note.get('title', 'بدون عنوان'))}</b>",
        f"",
    ]

    if note.get("description"):
        lines.append(f"📝 {escape_html(note['description'])}")
        lines.append("")

    if note.get("field_name"):
        lines.append(f"📚 رشته: {escape_html(note['field_name'])}")
    if note.get("subject_name"):
        lines.append(f"📖 درس: {escape_html(note['subject_name'])}")
    if note.get("chapter_name"):
        lines.append(f"📕 فصل: {escape_html(note['chapter_name'])}")

    page_start = note.get("page_start")
    page_end = note.get("page_end")
    if page_start and page_end:
        lines.append(f"📄 صفحات: {page_start} تا {page_end}")
    elif page_start:
        lines.append(f"📄 صفحه: {page_start}")

    if note.get("file_type"):
        lines.append(f"📎 نوع فایل: {note['file_type']}")
    if note.get("file_size"):
        lines.append(f"📦 حجم: {format_file_size(note['file_size'])}")
    if note.get("created_at"):
        lines.append(f"📅 تاریخ افزودن: {str(note['created_at'])[:10]}")

    lines.append(f"👤 ثبت‌کننده: {escape_html(note.get('submitted_by_name', 'نامشخص'))}")

    status = note.get("status", "")
    status_text = {
        "pending": "⏳ در انتظار تأیید",
        "approved": "✅ تأیید شده",
        "rejected": "❌ رد شده",
    }.get(status, status)
    lines.append(f"📊 وضعیت: {status_text}")

    return "\n".join(lines)


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to a maximum length."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def get_file_type_emoji(file_type: str) -> str:
    """Get an emoji for a file type."""
    emojis = {
        "photo": "🖼",
        "video": "🎬",
        "document": "📎",
        "audio": "🎵",
        "voice": "🎤",
        "text": "📝",
    }
    return emojis.get(file_type.lower(), "📎")


def format_page_range(page_start: Optional[int], page_end: Optional[int]) -> str:
    """Format page range for display."""
    if page_start and page_end:
        return f"{page_start} تا {page_end}"
    elif page_start:
        return str(page_start)
    return "—"


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
