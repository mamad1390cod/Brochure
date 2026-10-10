"""
Weekly schedule router for Bot-File-School (new day-based design).

User flow:
  🗓 برنامه هفتگی  ->  choose a study track -> choose a day -> view classes

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
from config import BOT_USERNAME
from utils import escape_html, safe_edit_text
from logger import logger

router = Router()

TRACKS = models.WEEKLY_TRACKS
CLASSES_PER_PAGE = 5


async def _day_tasks(day_index: int) -> list[tuple[int, str]]:
    """Read optional legacy schedule grid tasks without inventing defaults."""
    raw = await models.get_schedule()
    return [(c, raw[(day_index, c)]) for c in range(1, 8)
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
    await safe_edit_text(
        callback.message,
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
    """Choose a study track for the weekly class timetable."""
    await callback.answer()
    if _in_group(callback):
        await _private_handoff(callback, "برنامه هفتگی")
        return

    kb = _track_keyboard("week_track", back="menu_main")
    await safe_edit_text(
        callback.message,
        "🗓 <b>برنامه هفتگی کلاس‌ها</b>\n\nرشته تحصیلی را انتخاب کنید:",
        reply_markup=kb,
        parse_mode="HTML",
    )


def _track_keyboard(prefix: str, back: str | None = None):
    kb = InlineKeyboardBuilder()
    for key, (emoji, label) in TRACKS.items():
        kb.row(InlineKeyboardButton(
            text=f"{emoji} رشته {label}",
            callback_data=f"{prefix}:{key}",
        ))
    if back:
        kb.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back))
    return kb.as_markup()


def _day_keyboard(track_key: str):
    kb = InlineKeyboardBuilder()
    for day_index, day in enumerate(models.DAYS_FA):
        kb.row(InlineKeyboardButton(
            text=day,
            callback_data=f"week_show:{track_key}:{day_index}:0",
        ))
    kb.row(InlineKeyboardButton(
        text="🔙 بازگشت به انتخاب رشته",
        callback_data="week_back_tracks",
    ))
    return kb.as_markup()


@router.callback_query(F.data.startswith("week_track:"))
async def week_track_handler(callback: CallbackQuery):
    await callback.answer()
    track_key = callback.data.split(":", 1)[1]
    if track_key not in TRACKS:
        await callback.answer("رشته انتخاب‌شده معتبر نیست.", show_alert=True)
        return
    _, label = TRACKS[track_key]
    await safe_edit_text(
        callback.message,
        f"🗓 <b>برنامه هفتگی کلاس‌ها</b>\n\n📐 رشته: {label}\n\nروز هفته را انتخاب کنید:",
        reply_markup=_day_keyboard(track_key),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "week_back_tracks")
async def week_back_tracks_handler(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "🗓 <b>برنامه هفتگی کلاس‌ها</b>\n\nرشته تحصیلی را انتخاب کنید:",
        reply_markup=_track_keyboard("week_track", back="menu_main"),
        parse_mode="HTML",
    )


def _format_weekly_classes(
    track_key: str, day_index: int, classes, first_number: int = 1
) -> str:
    emoji, track_label = TRACKS[track_key]
    text = (
        "📅 <b>برنامه هفتگی کلاس‌ها</b>\n\n"
        f"{emoji} رشته: {track_label}\n"
        f"🗓 روز: {models.DAYS_FA[day_index]}\n\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    for number, item in enumerate(classes, start=first_number):
        text += (
            f"🕗 <b>کلاس {number}</b>\n"
            f"📖 نام کلاس: {escape_html(item['class_name'])}\n"
            f"⏰ ساعت: {item['start_time']} تا {item['end_time']}\n\n"
            "━━━━━━━━━━━━━━\n\n"
        )
    return text


@router.callback_query(F.data.startswith("week_show:"))
async def week_show_handler(callback: CallbackQuery):
    await callback.answer()
    _, track_key, day_value, page_value = callback.data.split(":")
    if track_key not in TRACKS:
        await callback.answer("رشته انتخاب‌شده معتبر نیست.", show_alert=True)
        return
    day_index, page = int(day_value), int(page_value)
    if not 0 <= day_index < len(models.DAYS_FA) or page < 0:
        await callback.answer("روز یا صفحه معتبر نیست.", show_alert=True)
        return

    all_classes = await models.get_weekly_classes(track_key, day_index)
    page_count = max(1, (len(all_classes) + CLASSES_PER_PAGE - 1) // CLASSES_PER_PAGE)
    page = min(page, page_count - 1)
    start = page * CLASSES_PER_PAGE
    visible = all_classes[start:start + CLASSES_PER_PAGE]
    if all_classes:
        text = _format_weekly_classes(
            track_key, day_index, visible, first_number=start + 1
        )
        if page_count > 1:
            text += f"صفحه {page + 1} از {page_count}"
    else:
        _, label = TRACKS[track_key]
        text = (
            f"📭 برای رشته {label} و روز {models.DAYS_FA[day_index]} "
            "هنوز کلاسی ثبت نشده است."
        )

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(
            text="⬅️ قبلی",
            callback_data=f"week_show:{track_key}:{day_index}:{page - 1}",
        )
    if page + 1 < page_count:
        kb.button(
            text="بعدی ➡️",
            callback_data=f"week_show:{track_key}:{day_index}:{page + 1}",
        )
    if page > 0 or page + 1 < page_count:
        kb.adjust(2)
    kb.row(InlineKeyboardButton(
        text="🔙 انتخاب روز دیگر",
        callback_data=f"week_days:{track_key}",
    ))
    kb.row(InlineKeyboardButton(
        text="🔄 انتخاب رشته دیگر",
        callback_data="week_back_tracks",
    ))
    await safe_edit_text(
        callback.message, text, reply_markup=kb.as_markup(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("week_days:"))
async def week_days_handler(callback: CallbackQuery):
    await callback.answer()
    track_key = callback.data.split(":", 1)[1]
    if track_key not in TRACKS:
        await callback.answer("رشته انتخاب‌شده معتبر نیست.", show_alert=True)
        return
    _, label = TRACKS[track_key]
    await safe_edit_text(
        callback.message,
        f"🗓 <b>برنامه هفتگی کلاس‌ها</b>\n\n📐 رشته: {label}\n\nروز هفته را انتخاب کنید:",
        reply_markup=_day_keyboard(track_key),
        parse_mode="HTML",
    )


# ─── Day view: online classes + tasks with per-task buttons ────────────────

@router.callback_query(F.data.startswith("sched_day:"))
async def sched_day_handler(callback: CallbackQuery):
    await callback.answer()
    await render_day(callback, int(callback.data.split(":")[1]))


async def render_day(callback: CallbackQuery, day_index: int):
    """Render one day for the calling user (classes + per-task buttons).

    Kept as a function because the task toggle re-renders the same view:
    callback.data cannot be rewritten in place - aiogram's models are frozen.
    """
    if _in_group(callback):
        await _private_handoff(callback, "جزئیات روز")
        return

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
        for period, item in items:
            done = await models.get_task_done(user.id, _task_key(day_index, period), week)
            mark = "✅" if done else "⬜"
            text += f"{mark} {escape_html(item)}\n"
            done_count += 1 if done else 0
            # one button per task
            kb.row(InlineKeyboardButton(
                text=f"{'↩️ لغو' if done else '✓ انجام شد'} — {item[:18]}",
                callback_data=f"task_done:{day_index}:{period}",
            ))
        text += f"\n📊 وضعیت شما: {done_count}/{len(items)} انجام شده"

    kb.row(InlineKeyboardButton(text="🔙 بازگشت به روزها", callback_data="menu_schedule"))
    await safe_edit_text(
        callback.message, text, reply_markup=kb.as_markup(), parse_mode="HTML"
    )


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
    await render_day(callback, day_index)


@router.callback_query(F.data.startswith("task_toggle:"))
async def legacy_task_toggle(callback: CallbackQuery):
    """Back-compat for old buttons: redirect to new day view."""
    await callback.answer()
    await render_day(callback, int(callback.data.split(":")[1]))
