"""
Background scheduler for Bot-File-School.
Resets the weekly per-user task statuses every Saturday at 00:00 local time
(start of the new Iranian school week). Previous week records are removed
from task_status (the sheet/history stays in convert_jobs + logs if needed).
"""

import asyncio
from datetime import datetime

import backup
import models
from logger import logger

TASK_EXPIRATION_INTERVAL_SECONDS = 60
_background_tasks: set[asyncio.Task] = set()
_backup_task: asyncio.Task | None = None


def _seconds_until_next_saturday_midnight() -> int:
    """Seconds until the coming Saturday 00:00 local time."""
    now = datetime.now()
    # Python weekday(): Monday=0 ... Saturday=5, Sunday=6
    days_ahead = (5 - now.weekday()) % 7
    next_sat = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if days_ahead == 0 and now.hour > 0:
        # Already inside Saturday, roll to the next one
        days_ahead = 7
    next_sat = datetime.fromtimestamp(next_sat.timestamp() + days_ahead * 86400)
    delta = (next_sat - now).total_seconds()
    return max(60, int(delta))


async def weekly_reset_loop():
    """Sleep until Saturday 00:00, then wipe last week task statuses."""
    while True:
        try:
            wait = _seconds_until_next_saturday_midnight()
            logger.info(f"Weekly task reset scheduled in {wait // 3600}h{(wait % 3600) // 60}m")
            await asyncio.sleep(wait)
            cleared = await models.reset_week_tasks()
            logger.info(f"Weekly task reset done - {cleared} old record(s) cleared.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Weekly reset failed, will retry in 10 minutes: {e}")
            await asyncio.sleep(600)


async def task_expiration_loop():
    """Deactivate expired homework promptly, including after bot restarts."""
    while True:
        try:
            expired = await models.expire_due_tasks()
            if expired:
                logger.info(f"Expired {expired} homework task(s).")
            await asyncio.sleep(TASK_EXPIRATION_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Task expiration check failed; retrying in 60 seconds: {e}")
            await asyncio.sleep(TASK_EXPIRATION_INTERVAL_SECONDS)


def start_scheduler() -> asyncio.Task:
    """Start weekly reset and homework-expiry loops."""
    weekly_task = asyncio.create_task(weekly_reset_loop())
    expiration_task = asyncio.create_task(task_expiration_loop())
    _background_tasks.update((weekly_task, expiration_task))
    weekly_task.add_done_callback(_background_tasks.discard)
    expiration_task.add_done_callback(_background_tasks.discard)
    return weekly_task


async def automatic_backup_loop(bot):
    """Create and deliver a verified backup every four hours."""
    loop = asyncio.get_running_loop()
    next_run = loop.time() + backup.BACKUP_INTERVAL_SECONDS
    while True:
        try:
            await asyncio.sleep(max(0, next_run - loop.time()))
            await backup.run_backup_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic backup cycle failed; it will retry later.")
        next_run += backup.BACKUP_INTERVAL_SECONDS
        if next_run <= loop.time():
            next_run = loop.time() + backup.BACKUP_INTERVAL_SECONDS


def start_backup_scheduler(bot) -> asyncio.Task:
    """Start at most one automatic backup loop in the current process."""
    global _backup_task
    if _backup_task is not None and not _backup_task.done():
        return _backup_task
    _backup_task = asyncio.create_task(automatic_backup_loop(bot))
    _background_tasks.add(_backup_task)
    _backup_task.add_done_callback(_background_tasks.discard)
    return _backup_task


async def stop_backup_scheduler() -> None:
    """Stop the automatic backup loop during a clean bot shutdown."""
    global _backup_task
    task = _backup_task
    _backup_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
