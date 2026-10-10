"""
Group features for Bot-File-School: /all command + activity tracking.

/all  - mention every known group member and add a short funny line.
        Rate limited to once per 60 seconds per chat (stored in the DB,
        so it survives restarts). Remaining time is announced when blocked.

The catch-all group tracker at the bottom records that the group is alive
(used by the nudge feature) and remembers members for /all and stats.
It is registered as the LAST router so it never swallows handled messages.
"""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext

import models
from config import ALLOWED_GROUP_ID
from utils import escape_html
from logger import logger

router = Router()

ALL_COOLDOWN_SECONDS = 60

DEFAULT_ALL_REPLY = (
    "همه سرشون شلوغه ولی این ربات با همه کار داره 😂\n"
    "یه سر به جزوه‌ها بزنید!"
)

# Default funny line for /all (editable via admin settings, key: all_reply_text)


def _is_allowed_group(chat_id: int) -> bool:
    """If ALLOWED_GROUP_ID is configured, only that group is served."""
    return ALLOWED_GROUP_ID is None or chat_id == ALLOWED_GROUP_ID


def _mention_for(row) -> str:
    """Best-effort mention: @username tags for real; otherwise plain name."""
    username = (row["username"] or "").lstrip("@")
    if username:
        return f"@{username}"
    name = (row["full_name"] or "").strip() or "دوست عزیز"
    return escape_html(name)


@router.message(Command("all"))
async def all_command_handler(message: Message, bot: Bot, state: FSMContext):
    """/all - mention all known group members (max once per minute per group)."""
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if state:
        await state.clear()
    if not _is_allowed_group(message.chat.id):
        return

    remaining = await models.all_cooldown_remaining(
        message.chat.id, ALL_COOLDOWN_SECONDS)
    if remaining > 0:
        await message.reply(
            f"⏳ بابا آروم! ⏰ {remaining} ثانیه دیگه دوباره می‌تونی همه رو صدا کنی 😅")
        return

    members = await models.get_group_members(message.chat.id)
    if not members:
        await message.reply(
            "🤷 هنوز کسی رو ثبت نکردم! یکی دو تا پیام تو گروه بفرستید تا بشناسمتون.")
        return

    claimed, remaining = await models.claim_all_cooldown(
        message.chat.id, ALL_COOLDOWN_SECONDS)
    if not claimed:
        await message.reply(
            f"⏳ بابا آروم! ⏰ {remaining} ثانیه دیگه دوباره می‌تونی همه رو صدا کنی 😅")
        return

    mentions = " ".join(_mention_for(m) for m in members[:100])
    reply = await models.get_setting("all_reply_text", DEFAULT_ALL_REPLY)
    reply = reply.replace("{count}", str(len(members)))

    await message.answer(f"{mentions}\n\n{escape_html(reply)}")
    logger.info(f"/all used in chat {message.chat.id} "
                f"({len(members)} members) by {message.from_user.id}")


# ─── Group activity tracker (registered LAST - never swallows anything) ─────

@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_tracker(message: Message):
    """Record group liveness + members. Only tracks the allowed group."""
    if ALLOWED_GROUP_ID is not None and message.chat.id != ALLOWED_GROUP_ID:
        return
    if message.from_user and not message.from_user.is_bot:
        await models.touch_group_activity(
            message.chat.id, message.chat.title or "")
        await models.upsert_group_member(
            message.chat.id, message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name or "",
        )
