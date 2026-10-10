"""
Group inactivity nudge for Bot-File-School.

If nobody has used the bot in a group for N days (default 4), the bot
sends a friendly - slightly funny - message to encourage people to come
back. Messages are picked randomly and never repeat back-to-back.
"""

import asyncio
import random

from aiogram import Bot

import models
from logger import logger

NUDGE_DAYS = 4
CHECK_INTERVAL_SECONDS = 30 * 60  # check every 30 minutes

# 50+ friendly, slightly funny Persian nudge messages.
# {bot} is replaced with the bot's mention so users can tap it.
NUDGE_MESSAGES = [
    "چی شد اینجا؟ 🤔 یه هفته شد کسی سر نزد! دوباره بهم سر بزن {bot} 😅",
    "بچه‌ها جزوه‌ها دارن خاک می‌گیرن! 📚 dusting_off()… بزن بریم {bot} 😂",
    "ربات: منو فراموش کردید؟ 🥺 ما هم شما رو… آره هنوز یادمونه! {bot}",
    "سلام! داداش یه جزوه بده دیگه 😁 اینجا خبری از شما نیست {bot}",
    "۴ روزه سکوته… یا پام بریده یا شما رفتید! 😱 برگردید {bot}",
    "این ربات به جای چت با گپ‌زن‌ها با عنکبوت‌ها حرف می‌زد 🕷️ برگردید {bot}",
    "خطرناکه! جزوه‌ها دارن فرار می‌کنن 🏃📄 بگیرشون {bot} 😂",
    "دلم براتون تنگ شده… و خودمم خیلی خنگم که جزوه یادتون نده! 😜 {bot}",
    "اینجا که پارتی نیست، جزوه‌ست! 📚 بیا ببین {bot}",
    "ربات کم‌کاری می‌کنه؟ نه بابا، شما سر نمی‌زنید! 😤 {bot}",
    "جمع جزوه‌ها امتحان داره، تو چی؟ 📝 بیا با هم بخونیم {bot} 😎",
    "باور کن دلم تنگ شده… ولی چاییم سرد شد منتظرتون ☕ {bot}",
    "جیمز اینجا بود؟ ❌ پس چرا کسی نمیاد؟! برگردید {bot}",
    "به به! اگه امتحان بود، الان رسوب شده بودید 📉 بیاید بخونیم {bot} 😂",
    "جزوه‌ها با هم قایم‌موشک بازی می‌کنن، هنوز پیدا‌شون نکردی؟ 🙈 {bot}",
    "برنامه هفتگی نگاه کردی اصلاً؟ 📅 یا فقط می‌شی پیام‌ها رو؟ {bot} 😜",
    "چرا هیشکی نیست؟! 🦗 ملخ‌ها هم خسته شدن از این سکوت! {bot}",
    "یادتونه قرار بود درس بخونید؟ 🤭 ربات یادشه! {bot}",
    "این سکوت مشکوکه… 🕵️ کسی نیست یه جزوه بزنه؟ {bot}",
    "سلام دوباره! 🌞 جزوه‌های تازه رسیدن، بیا ببین {bot}",
    "راستی جزوه ریاضی رو دیدی؟ 🤓 نه؟ پس بیا! {bot}",
    "برای تنبلیت دلیلی نیست، برای خوندن جزوه بهانه بیار! 😤 {bot}",
    "یک جزوه بخون، عمرت برمی‌گرده 🧬 (تقریباً) {bot} 😂",
    "هی! یه سلام بکن دیگه 👋 ربات از دل‌تنگی داره زنگ می‌زنه {bot}",
    "پیام به همه: ربات خسته نباشد 🫡 ولی شما کجا هستید؟! {bot}",
    "این ربات از تنهایی آواز خوندن یاد گرفته 🎤 بیاید جمعش کنید! {bot}",
    "خودم با خودم حرف زدم، خسته شدم 😅 بیا یه جزوه بزن {bot}",
    "جزوه‌ها منتظرن… مثل شتری که آب خورده 🐪 بیا {bot} 😂",
    "آفرین به کسایی که سر زدن… آهان، یعنی هیچکس! 💀 برگردید {bot}",
    "این سکوت یعنی امتحان تموم شد؟ 🎉 یا هنوز شروع نشده؟ 🙃 {bot}",
    "برگرد ببین چه خبر! 📰 روزنامه جزوه‌ها اومده {bot}",
    "یه جزوه بخون، یه استکان چای بزن ☕ چه حالی می‌ده! {bot}",
    "ربات: خسته شدم منتظرتون 🥱 بیاید یه بار هم شده زودتر از من برسید {bot}",
    "جدی بگم؟ جزوه‌ها از فرط بی‌استفاده‌ای رنگ‌پریده شدن 😵 {bot}",
    "هوی! 📢 اجتماع در پنجمین روز غیبت برگزار می‌شود! {bot} 😂",
    "بیا ببین، اینجا دیگه وقت‌تلف‌کردنی نیست… فقط یه کم 😜 {bot}",
    "جزوه‌ها گفته بودن اگه یادمون رفتن بگیم: یادمون رفت! 🤷 بیا {bot}",
    "دلم هوای جزوه‌هایت را کرده 🌹 (ربات شاعر شد، ببین چطوره!) {bot}",
    "یه خبر فوری: 🚨 هیچ خبر فوری‌ای نیست، فقط برگردید {bot}",
    "اگه جزوه‌ها تکلیف داشتن، الان ده‌ها صفحه می‌خوندن! 📚 {bot} 😂",
    "من اینجا تنها یه پیام نوشتم، تو فقط یه دکمه بزن 🤝 {bot}",
    "سلام! 🤗 حال شما مهم نیست، حال جزوه‌ها مهمه! بیا ببینشون {bot}",
    "چرا ساکتید؟ 🤫 یا درس‌تون خیلی خوبه یا خیلی بد! بگو کدومه {bot}",
    "فقط یه نگاه… 🥹 قول می‌دم جزوه‌ها قشنگ باشن {bot}",
    "یه جزوه در روز، دکتر رو از سرتون می‌ندازه 💊 (تقریباً علمیه) {bot} 😂",
    "کجایید دوستان؟ 🗺️ نقشه گنج جزوه‌ها اینجاست {bot}",
    "اومدم یادآوری کنم… یادم رفته چی 😅 خب بیا خودت ببین {bot}",
    "ببخشید اسپم می‌کنم، ولی جزوه‌ها اصرار داشتن! 📚 {bot} 🙏",
    "شبا خوب خوابیدید؟ 😴 پس صبح یه جزوه بخونید تا بیدار شید {bot}",
    "نه بابا، من ناراحت نیستم… فقط یه ماهه بی‌خبرید 🥲 {bot}",
    "جزوه‌ها گفتن دوستت دارن ❤️ (من فقط پیام‌رسانم) {bot}",
    "برگردید! 🎬 قسمت دوم: «جزوه‌ها انتقام می‌گیرند» هنوز نمایش داده نشده {bot} 😂",
]


def _pick_message(last_index: int | None = None) -> tuple[str, int]:
    """Random message, never the same as the previous one."""
    idx = random.randrange(len(NUDGE_MESSAGES))
    if last_index is not None and idx == last_index and len(NUDGE_MESSAGES) > 1:
        idx = (idx + random.randrange(1, len(NUDGE_MESSAGES))) % len(NUDGE_MESSAGES)
    return NUDGE_MESSAGES[idx], idx


# In-memory "last message index" per chat so consecutive nudges differ.
_last_nudge_index: dict[int, int] = {}


async def _nudge_text(bot: Bot) -> str:
    me = await bot.get_me()
    return "@" + me.username


async def nudge_loop(bot: Bot) -> None:
    """Every CHECK_INTERVAL, nudge groups that have been silent for N days."""
    logger.info(
        f"Nudge loop started - checking every {CHECK_INTERVAL_SECONDS // 60} min, "
        f"threshold {NUDGE_DAYS} days, {len(NUDGE_MESSAGES)} messages."
    )
    while True:
        try:
            enabled = await models.get_setting("nudge_enabled", "1")
            if enabled == "1":
                bot_username = await _nudge_text(bot)
                for group in await models.get_stale_groups(NUDGE_DAYS):
                    chat_id = group["chat_id"]
                    msg, idx = _pick_message(_last_nudge_index.get(chat_id))
                    _last_nudge_index[chat_id] = idx
                    text = msg.format(bot=bot_username)
                    try:
                        await bot.send_message(chat_id, text)
                        await models.mark_group_nudged(chat_id)
                        logger.info(f"Nudge sent to group {chat_id}")
                    except Exception as send_err:
                        logger.warning(
                            f"Could not nudge group {chat_id}: {send_err}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Nudge loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_nudge_scheduler(bot: Bot) -> asyncio.Task:
    """Create and return the nudge background task."""
    return asyncio.create_task(nudge_loop(bot))
