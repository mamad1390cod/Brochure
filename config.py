"""
Configuration module for Bot-File-School.
Loads environment variables and provides validated config values.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Project root directory
BASE_DIR = Path(__file__).parent.resolve()


def _get_env(key: str, default: str = "", required: bool = False) -> str:
    """Get an environment variable with optional default and required check."""
    value = os.getenv(key, default)
    if required and not value:
        raise ValueError(f"Required environment variable {key} is not set.")
    return value


def _get_env_int(key: str, default: int = 0, required: bool = False) -> int:
    """Get an integer environment variable."""
    value = os.getenv(key)
    if value is None:
        if required:
            raise ValueError(f"Required environment variable {key} is not set.")
        return default
    return int(value)


def _get_env_bool(key: str, default: bool = False) -> bool:
    """Get a boolean environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def _get_env_list(key: str) -> list:
    """Get a comma-separated list from environment variable."""
    value = os.getenv(key, "")
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# ─── Bot Settings ─────────────────────────────────────────────────────────────

BOT_TOKEN: str = _get_env("BOT_TOKEN", required=True)
BOT_USERNAME: str = _get_env("BOT_USERNAME", default="BotFileSchoolBot")

# ─── Admin Settings ───────────────────────────────────────────────────────────

MAIN_ADMIN_ID: int = _get_env_int("MAIN_ADMIN_ID", required=True)
ADMIN_PASSWORD: str = _get_env("ADMIN_PASSWORD", required=True)

# ─── Group Settings ───────────────────────────────────────────────────────────

ALLOWED_GROUP_ID: int | None = None
_group_id = _get_env("ALLOWED_GROUP_ID", "")
if _group_id:
    ALLOWED_GROUP_ID = int(_group_id)

# ─── Database ─────────────────────────────────────────────────────────────────

DATABASE_PATH: Path = BASE_DIR / _get_env("DATABASE_PATH", default="data/school_notes.db")

# ─── Security ─────────────────────────────────────────────────────────────────

MAX_LOGIN_ATTEMPTS: int = _get_env_int("MAX_LOGIN_ATTEMPTS", default=5)
LOGIN_LOCKOUT_MINUTES: int = _get_env_int("LOGIN_LOCKOUT_MINUTES", default=15)

# ─── Inline Search ────────────────────────────────────────────────────────────

ENABLE_INLINE_SEARCH: bool = _get_env_bool("ENABLE_INLINE_SEARCH", default=True)
INLINE_SEARCH_ALLOWED_USERS: list[str] = _get_env_list("INLINE_SEARCH_ALLOWED_USERS")

# ─── Logging ──────────────────────────────────────────────────────────────────

LOG_LEVEL: str = _get_env("LOG_LEVEL", default="INFO").upper()

# ─── PDF Bot (bot1cc.py) ─────────────────────────────────────────────────────
# Optional standalone PDF bot launched as a separate process alongside the
# main bot. Path is configurable (never hard-coded) - e.g.:
#   PDF_BOT_PATH=I:\python\botha\BOT1\bot1cc.py
# If unset or the file does not exist, the main bot runs fine without it and
# the in-app PDF tools remain fully functional.

PDF_BOT_PATH: Path | None = None
_pdf_bot_raw = _get_env("PDF_BOT_PATH", "")
if _pdf_bot_raw:
    PDF_BOT_PATH = Path(_pdf_bot_raw)
PDF_BOT_ENABLED: bool = PDF_BOT_PATH is not None and PDF_BOT_PATH.exists()
# Public username (without @) of the standalone PDF bot, used for the
# handoff link in the "📄 ساخت PDF" menu. Leave empty if not needed.
PDF_BOT_USERNAME: str = _get_env("PDF_BOT_USERNAME", "")
