"""
Online class notifications + goodnight message for Bot-File-School.

- Class times are stored in Asia/Tehran (the source timetable is Iranian).
- The bot displays/sends times converted to the project timezone
  (setting `timezone`, default Asia/Muscat - configurable in the panel).
- Every class can have its own notify on/off (notify_enabled) and there is
  a global switch (setting class_notify_enabled).
- Sent alerts are recorded in class_alerts_sent so a restart never
  double-sends; after restart everything is reloaded from the database.
- A configurable goodnight message ("شب خوش بچه‌ها") can be sent daily at a
  set time in the project timezone (settings goodnight_*).
"""

import asyncio
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from aiogram import Bot

import models
from config import ALLOWED_GROUP_ID
from logger import logger

TEHRAN_TZ = ZoneInfo("Asia/Tehran")
CHECK_INTERVAL_SECONDS = 30
# If the bot was down for longer than this, skip the stale alert instead of
# waking the group with a "class started" message from hours ago.
STALE_ALERT_WINDOW_MINUTES = 20

DEFAULT_CLASS_TEXT = (
    "🔔 کلاس آنلاین شروع شد!\n\n"
    "📚 درس: {subject}\n"
    "⏰ زمان کلاس: {time}\n"
    "🕐 ساعت محلی: {local_time}"
)
DEFAULT_GOODNIGHT_TEXT = (
    "🌙 شب خوش بچه‌ها!\n"
    "چشم‌هاتو ببند، فردا جزوه‌ها منتظرتن 😴📚"
)


def get_project_tz_name() -> str:
    return "Asia/Muscat"  # fallback; real value is read from DB settings


async def get_tz() -> ZoneInfo:
    name = await models.get_setting("timezone", "Asia/Muscat")
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning(f"Unknown timezone '{name}' - falling back to Asia/Muscat")
        return ZoneInfo("Asia/Muscat")


def tehran_day_index(now_tehran: datetime) -> int:
    """Python weekday (Mon=0) -> school day index (Saturday=0)."""
    return (now_tehran.weekday() + 2) % 7


def to_local(tehran_hour: int, tehran_minute: int, local_tz: ZoneInfo) -> str:
    """Convert a Tehran HH:MM today to the same moment in the project tz."""
    now_t = datetime.now(TEHRAN_TZ)
    moment = now_t.replace(hour=tehran_hour, minute=tehran_minute,
                            second=0, microsecond=0)
    local = moment.astimezone(local_tz)
    return local.strftime("%H:%M")


def format_class_time(cls, local_tz: ZoneInfo) -> str:
    """Human readable class time: Tehran time + local equivalent."""
    if cls["start_hour"] is None:
        return cls["time_text"] or "—"
    tehran = f"{cls['start_hour']:02d}:{cls['start_minute'] or 0:02d}"
    local = to_local(cls["start_hour"], cls["start_minute"] or 0, local_tz)
    base = f"{tehran} (تهران) - {local} (محلی)"
    if cls["end_hour"] is not None:
        base += f" تا {cls['end_hour']:02d} تهران"
    return base


def _group_target() -> int | None:
    """Where class alerts go: the configured group (if any)."""
    return ALLOWED_GROUP_ID


async def send_class_alert(bot: Bot, cls, local_tz: ZoneInfo) -> bool:
    chat_id = _group_target()
    if chat_id is None:
        logger.info("Class alert skipped - no ALLOWED_GROUP_ID configured")
        return False
    template = await models.get_setting("class_notify_text", DEFAULT_CLASS_TEXT)
    text = template.format(
        subject=cls["title"],
        time=format_class_time(cls, local_tz),
        local_time=to_local(cls["start_hour"], cls["start_minute"] or 0, local_tz)
        if cls["start_hour"] is not None else (cls["time_text"] or ""),
    )
    if cls["link"]:
        text += f"\n\n🔗 {cls['link']}"
    try:
        await bot.send_message(chat_id, text)
        logger.info(f"Class alert sent: #{cls['id']} {cls['title']}")
        return True
    except Exception as e:
        logger.warning(f"Class alert send failed for #{cls['id']}: {e}")
        return False


async def check_goodnight(bot: Bot, now_local: datetime) -> None:
    """Send the daily goodnight message if enabled and due."""
    enabled = await models.get_setting("goodnight_enabled", "0")
    if enabled != "1":
        return
    hhmm = await models.get_setting("goodnight_time", "22:00")
    try:
        target = dtime.fromisoformat(hhmm.strip())
    except Exception:
        target = dtime(22, 0)
    today = now_local.date().isoformat()
    last = await models.get_setting("goodnight_last_date", "")
    if last == today:
        return  # already sent today
    if now_local.time() < target:
        return
    chat_id = _group_target()
    if chat_id is None:
        return
    text = await models.get_setting("goodnight_text", DEFAULT_GOODNIGHT_TEXT)
    try:
        await bot.send_message(chat_id, text)
        await models.set_setting("goodnight_last_date", today,
                                 "last goodnight date sent")
        logger.info(f"Goodnight message sent to {chat_id}")
    except Exception as e:
        logger.warning(f"Goodnight send failed: {e}")


async def class_notify_loop(bot: Bot) -> None:
    """Main scheduling loop: class start alerts + goodnight message."""
    logger.info(f"Class notify loop started (interval {CHECK_INTERVAL_SECONDS}s)")
    while True:
        try:
            global_enabled = (
                (await models.get_setting("class_notify_enabled", "1")) == "1")
            local_tz = await get_tz()
            now_local = datetime.now(local_tz)
            now_tehran = now_local.astimezone(TEHRAN_TZ)
            today_key = now_tehran.date().isoformat()

            if global_enabled and _group_target() is not None:
                day = tehran_day_index(now_tehran)
                classes = await models.get_online_classes(day)
                for cls in classes:
                    if not cls["notify_enabled"] or cls["start_hour"] is None:
                        continue
                    start = now_tehran.replace(
                        hour=cls["start_hour"],
                        minute=cls["start_minute"] or 0,
                        second=0, microsecond=0)
                    minutes_late = (now_tehran - start).total_seconds() / 60
                    if minutes_late < 0 or minutes_late > STALE_ALERT_WINDOW_MINUTES:
                        continue
                    if await models.class_alert_already_sent(cls["id"], today_key):
                        continue
                    if await send_class_alert(bot, cls, local_tz):
                        await models.class_alert_mark_sent(cls["id"], today_key)

            await check_goodnight(bot, now_local)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Class notify loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_class_notifier(bot: Bot) -> asyncio.Task:
    """Create and return the class notification background task."""
    return asyncio.create_task(class_notify_loop(bot))
