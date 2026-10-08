"""
Weekly schedule router for Bot-File-School (new day-based design).

User flow:
  🗓 برنامه هفتگی  ->  7 day buttons (🔴🟡🟢⚪ colored PER USER)
  tap a day       ->  that day's online classes + its tasks
  each task       ->  its own "✓ انجام شد" button (per-user state)

Privacy: Telegram group messages are visible to everyone, so real privacy
is impossible inside a group chat. When the user opens the schedule (or
toggles a task) inside the allowed GROUP, the bot sends a short public
notice with a deep-link and continues the whole interaction in the user's
PRIVATE chat - standard Telegram practice for personal data.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType

import models
import keyboards
from permissions import is_admin
from config import BOT_USERNAME
from utils import escape_html
from logger import logger

router = Router()

DEFAULT_DAY_TASKS: dict[int, list[str]] = {
    0: ["مشاهده ویدیو آموزش عربی", "حل تکلیف حفظ‌لایه", "حل تکلیف حرفه‌ای",
        "مطالعه ویدیو آموزش نگارش", "حل تکلیف نگارش"],
    1: ["مطالعه ویدیو آموزشی آنلاین", "حل تکلیف آنلاین", "حل تکلیف آرامش",
        "پیش مطالعه درس فیزیک"],
    2: ["فیزیک", "حل تکلیف فیزیک", "پیش مطالعه درس هندسه", "پیش مطالعه درس عربی"],
    3: ["هندسه", "عربی", "پیش مطالعه درس شیمی", "شیمی", "حل تکلیف شیمی"],
    4: ["حل تکلیف هندسه", "پیش مطالعه فیزیک/ریاضی", "فیزیک (فردیشی)",
        "ریاضی (لفردیشی)", "حل تکلیف فیزیک/ریاضی"],
    5: ["ریاضی", "حل تکلیف عربی", "پیش مطالعه درس فارسی"],
    6: ["فارسی", "حل تکلیف فارسی", "مطالعه ویدیو آموزش دینی", "حل تکلیف ریاضی"],
}


async def _day_tasks(day_index: int) -> list[str]:
    """Tasks of one day from the schedule grid (columns 1..7), preserving
    period order. Seeds the default plan on first ever use."""
    raw = await models.get_schedule()
    if not raw:
        for d, items in DEFAULT_DAY_TASKS.items():
            for i, content in enumerate(items, start=1):
                await models.set_schedule_cell(None, d, i, content)
        raw = await models.get_schedule()
    return [raw.get((day_index, c), "") for c in range(1, 8)
            if raw.get((day_index, c), "")]


def _task_key(day_index: int, idx: int) -> str:
    return f"sched:{day_index}:{idx}"


# ─── Privacy: group -> private chat handoff ────────────────────────────────

def _in_group(callback: CallbackQuery) -> bool:
    return callback.message is not None and callback.message.chat.type in (
        ChatType.GROUP, ChatType.SUPERGROUP)


async def _private_handoff(callback: CallbackQuery, action: str):
    """In a group, replace with a public notice + deep-link to private chat.
    Nothing personal (schedule/tasks/status) is revealed in the group."""
    bot_username = BOT_USERNAME or "BotFileSchoolBot"
    try:
        me = await callback.message.bot.get_me()
        bot_username = me.username or bot_username
    except Exception:
        pass
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="💬 مشاهده در چت خصوصی",
        url=f"https://t.me/{bot_username}"))
    await callback.message.edit_text(
        f"🔒 <b>{action}</b>\n\n"
        "برای حفظ حریم خصوصی شما، این بخش فقط در چت خصوصی نمایش داده می‌شود.\n"
        "روی دکمه زیر بزنید و آنجا دوباره انتخاب کنید:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Week menu: 7 colored day buttons ───────────────────────────────────────

@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "menu_schedule")
async def menu_schedule_handler(callback: CallbackQuery):
    """Day list with per-user color status."""
    await callback.answer()
    if _in_group(callback):
        await _private_handoff(callback, "برنامه هفتگی")
        return

    user = callback.from_user
    admin_user = await is_admin(user.id)
    week = models.current_week_key()

    kb = InlineKeyboardBuilder()
    text = (
        "🗓 <b>برنامه هفتگی کلاس</b>\n"
        f"<i>هفته {week}</i>\n\n"
        "🔴 هیچ تکلیفی انجام نشده  |  🟡 بعضی انجام شده  |  🟢 همه انجام شده  |  ⚪ تکلیفی ندارد\n\n"
        "روی روز موردنظر کلیک کنید:"
    )
    for d, day in enumerate(models.DAYS_FA):
        done, total = await models.get_day_done_status(user.id, d, week)
        emoji = models.day_status_emoji(done, total)
        if total:
            label = f"{emoji} {day} ({done}/{total})"
        else:
            label = f"{emoji} {day}"
        kb.row(InlineKeyboardButton(text=label, callback_data=f"sched_day:{d}"))
    if admin_user:
        kb.row(InlineKeyboardButton(
            text="✏️ ویرایش برنامه (ادمین)", callback_data="admin_schedule_view"))
        kb.row(InlineKeyboardButton(
            text="🟢 مدیریت کلاس‌های آنلاین (ادمین)", callback_data="admin_classes"))
    kb.row(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu_main"))
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ─── Day view: online classes + tasks with per-task buttons ────────────────

@router.callback_query(F.data.startswith("sched_day:"))
async def sched_day_handler(callback: CallbackQuery):
    await callback.answer()
    if _in_group(callback):
        await _private_handoff(callback, "جزئیات روز")
        return

    day_index = int(callback.data.split(":")[1])
    user = callback.from_user
    week = models.current_week_key()

    items = await _day_tasks(day_index)
    classes = await models.get_online_classes(day_index)

    text = f"🗓 <b>{models.DAYS_FA[day_index]}</b> <i>(هفته {week})</i>\n"

    # ── online classes of this day ──
    kb = InlineKeyboardBuilder()
    if classes:
        text += "\n🟢 <b>کلاس‌های آنلاین امروز:</b>\n"
        for c in classes:
            line = f"  • <b>{escape_html(c['title'])}</b>"
            if c["time_text"]:
                line += f" — ⏰ {escape_html(c['time_text'])}"
            text += line + "\n"
            if c["link"]:
                kb.row(InlineKeyboardButton(
                    text=f"🔗 ورود به کلاس {c['title'][:15]}",
                    url=c["link"]))
    else:
        text += "\n⚪ <b>کلاس آنلاینی برای امروز ثبت نشده است.</b>\n"

    # ── tasks of this day (per-user done state) ──
    text += "\n📋 <b>تکالیف امروز:</b>\n"
    if not items:
        text += "⚪ تکلیفی برای این روز ثبت نشده است.\n"
    else:
        done_count = 0
        for idx, item in enumerate(items, start=1):
            done = await models.get_task_done(user.id, _task_key(day_index, idx), week)
            mark = "✅" if done else "⬜"
            text += f"{mark} {escape_html(item)}\n"
            done_count += 1 if done else 0
            # one button per task
            kb.row(InlineKeyboardButton(
                text=f"{'↩️ لغو' if done else '✓ انجام شد'} — {item[:18]}",
                callback_data=f"task_done:{day_index}:{idx}",
            ))
        text += f"\n📊 وضعیت شما: {done_count}/{len(items)} انجام شده"

    kb.row(InlineKeyboardButton(text="🔙 بازگشت به روزها", callback_data="menu_schedule"))
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ─── Per-task toggle (per-user, per-week, persistent) ───────────────────────

@router.callback_query(F.data.startswith("task_done:"))
async def task_done_toggle_handler(callback: CallbackQuery):
    await callback.answer()
    if _in_group(callback):
        await _private_handoff(callback, "وضعیت تکلیف")
        return

    _, d, idx = callback.data.split(":")
    day_index, idx = int(d), int(idx)
    user = callback.from_user
    week = models.current_week_key()
    key = _task_key(day_index, idx)

    current = await models.get_task_done(user.id, key, week)
    await models.set_task_done(user.id, key, week, not current)
    logger.info(f"User {user.id} task {key} week {week} -> {not current}")

    # re-render the same day view (per-user)
    fake = callback
    fake.data = f"sched_day:{day_index}"
    await sched_day_handler(fake)


@router.callback_query(F.data.startswith("task_toggle:"))
async def legacy_task_toggle(callback: CallbackQuery):
    """Back-compat for old buttons: redirect to new day view."""
    day_index = int(callback.data.split(":")[1])
    callback.data = f"sched_day:{day_index}"
    await sched_day_handler(callback)
