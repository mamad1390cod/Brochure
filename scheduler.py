"""
Background scheduler for Bot-File-School.
Resets the weekly per-user task statuses every Saturday at 00:00 local time
(start of the new Iranian school week). Previous week records are removed
from task_status (the sheet/history stays in convert_jobs + logs if needed).
"""

import asyncio
from datetime import datetime

import models
from logger import logger


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


def start_scheduler() -> asyncio.Task:
    """Create and return the background scheduler task."""
    return asyncio.create_task(weekly_reset_loop())
