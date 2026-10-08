"""
PDF Bot process manager for Bot-File-School.

Launches the user's existing standalone PDF bot (bot1cc.py) as a SEPARATE
process alongside the main bot:

    Main Application
           |
           |- Main Bot        (this process)
           |- PDF Bot Process (bot1cc.py, separate interpreter)

Design rules (per requirements):
- Path comes from PDF_BOT_PATH env var - never hard-coded.
- No duplicate launches: a singleton lock prevents two PDF bots.
- Status can be checked at any time (is_running / get_info).
- Errors are logged with the [PDF BOT] prefix.
- Graceful shutdown when the main bot exits (terminate -> wait -> kill).
- A crash of the PDF bot NEVER stops the main bot (restart with backoff).
- Optional auto-restart keeps it alive if it dies unexpectedly.
"""

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from config import PDF_BOT_PATH, PDF_BOT_ENABLED
from logger import logger

TAG = "[PDF BOT]"

# Path of the lock file used to prevent duplicate processes
_LOCK_FILE = Path(__file__).parent / "data" / "pdf_bot.lock"


class PdfBotProcessManager:
    """Manage the standalone PDF bot subprocess (singleton)."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._restarts: int = 0
        self._last_error: str = ""
        self._stopping: bool = False
        self._watchdog: asyncio.Task | None = None
        self._lock_acquired: bool = False

    # ── singleton lock ──────────────────────────────────────────────────
    def _acquire_lock(self) -> bool:
        """Create a lock file; refuse if another manager already owns it."""
        try:
            _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            if _LOCK_FILE.exists():
                # Stale lock from a crashed previous run? Check the PID inside.
                try:
                    old_pid = int(_LOCK_FILE.read_text().strip())
                    if sys.platform == "win32":
                        # On Windows just check process existence via tasklist
                        check = subprocess.run(
                            ["tasklist", "/FI", f"PID eq {old_pid}"],
                            capture_output=True, text=True, timeout=10)
                        alive = str(old_pid) in (check.stdout or "")
                    else:
                        alive = Path(f"/proc/{old_pid}").exists()
                    if alive:
                        logger.warning(
                            f"{TAG} Another PDF bot (PID {old_pid}) appears "
                            "to be running - not starting a duplicate.")
                        return False
                except Exception:
                    pass  # unreadable lock -> assume stale
                _LOCK_FILE.unlink(missing_ok=True)
            _LOCK_FILE.write_text(str(os.getpid()))
            self._lock_acquired = True
            return True
        except Exception as e:
            logger.warning(f"{TAG} Could not create lock file: {e}")
            return False  # be safe: do not allow duplicates

    def _release_lock(self):
        try:
            if self._lock_acquired:
                _LOCK_FILE.unlink(missing_ok=True)
                self._lock_acquired = False
        except Exception:
            pass

    # ── lifecycle ───────────────────────────────────────────────────────
    def start(self) -> bool:
        """Start the PDF bot subprocess. Returns True on success."""
        if self._process and self._process.poll() is None:
            logger.info(f"{TAG} Already running (PID {self._process.pid})")
            return True

        if not PDF_BOT_ENABLED or PDF_BOT_PATH is None:
            logger.info(
                f"{TAG} Disabled (PDF_BOT_PATH not set or file missing) - "
                "in-app PDF tools remain available.")
            return False

        if not self._acquire_lock():
            return False

        try:
            logger.info(f"{TAG} Starting... ({PDF_BOT_PATH})")
            # Run inside the same interpreter the main bot uses so all
            # dependencies resolve the same way; unbuffered output so
            # logs arrive in real time.
            self._process = subprocess.Popen(
                [sys.executable, "-u", str(PDF_BOT_PATH)],
                cwd=str(PDF_BOT_PATH.parent),
                stdout=subprocess.DEVNULL,   # bot logs to its own console/log
                stderr=subprocess.PIPE,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                ),
            )
            self._started_at = time.time()
            self._stopping = False
            logger.info(f"{TAG} Started successfully - Process ID: {self._process.pid}")
            try:
                loop = asyncio.get_running_loop()
                self._watchdog = loop.create_task(self._watchdog_loop())
            except RuntimeError:
                # No event loop running (e.g. tests) - process still started
                self._watchdog = None
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"{TAG} Error starting: {e}")
            self._release_lock()
            return False

    async def _watchdog_loop(self):
        """Auto-restart with backoff if the PDF bot crashes unexpectedly."""
        delays = [5, 15, 60, 300]
        while not self._stopping:
            await asyncio.sleep(2)
            if not self._process:
                break
            code = self._process.poll()
            if code is None:
                continue  # still running
            if self._stopping:
                break
            self._last_error = f"exited with code {code}"
            logger.warning(
                f"{TAG} Process exited (code {code}) - restarting in "
                f"{delays[min(self._restarts, len(delays) - 1)]}s ...")
            await asyncio.sleep(delays[min(self._restarts, len(delays) - 1)])
            if self._stopping:
                break
            self._restarts += 1
            try:
                logger.info(f"{TAG} Restarting... (attempt {self._restarts})")
                self._process = subprocess.Popen(
                    [sys.executable, "-u", str(PDF_BOT_PATH)],
                    cwd=str(PDF_BOT_PATH.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        if sys.platform == "win32" else 0
                    ),
                )
                self._started_at = time.time()
                logger.info(f"{TAG} Started successfully - Process ID: {self._process.pid}")
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"{TAG} Error during restart: {e}")

    def is_running(self) -> bool:
        return bool(self._process and self._process.poll() is None)

    def get_info(self) -> dict:
        """Status snapshot for admin display."""
        if self.is_running():
            uptime = int(time.time() - (self._started_at or 0))
            return {
                "running": True,
                "pid": self._process.pid,
                "uptime_sec": uptime,
                "restarts": self._restarts,
                "path": str(PDF_BOT_PATH) if PDF_BOT_PATH else "",
            }
        return {
            "running": False,
            "restarts": self._restarts,
            "last_error": self._last_error,
            "path": str(PDF_BOT_PATH) if PDF_BOT_PATH else "",
        }

    def stop(self, timeout: int = 10):
        """Graceful shutdown: terminate -> wait -> kill."""
        self._stopping = True
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        if not self._process or self._process.poll() is not None:
            self._release_lock()
            return
        logger.info(f"{TAG} Stopping (PID {self._process.pid})...")
        try:
            if sys.platform == "win32":
                # CTRL_BREAK to the process group lets aiogram shut down cleanly
                self._process.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
            else:
                self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(f"{TAG} Did not exit in {timeout}s - killing.")
                self._process.kill()
                self._process.wait(timeout=5)
            logger.info(f"{TAG} Stopped")
        except Exception as e:
            logger.error(f"{TAG} Error during stop: {e}")
        finally:
            self._release_lock()


# Global manager instance (singleton)
pdf_bot_manager = PdfBotProcessManager()
