"""
Test harness for Bot-File-School.

Runs the REAL production wiring (main.main()) against a temporary SQLite
database and a fake Telegram session, so handlers, middlewares, filters and
callback-data routing are all exercised exactly as they run in production.

Nothing here talks to the network.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="bfs_tests_"))
_DB_PATH = _TMP_ROOT / "school_notes.db"

os.environ.update(
    {
        "BOT_TOKEN": "123456:TEST-TOKEN-NOT-REAL",
        "MAIN_ADMIN_ID": "100001",
        "ADMIN_PASSWORD": "OwnerSecret1",
        "DATABASE_PATH": str(_DB_PATH),
        "LOG_LEVEL": "ERROR",
        "ALLOWED_GROUP_ID": "",
        "BOT_USERNAME": "TestSchoolBot",
        "ENABLE_INLINE_SEARCH": "true",
        "MAX_LOGIN_ATTEMPTS": "5",
        "LOGIN_LOCKOUT_MINUTES": "15",
        "PDF_BOT_PATH": "",
    }
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery,
    Chat,
    Message,
    Update,
    User,
)

TEST_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["MAIN_ADMIN_ID"])

# ─── Fake Telegram session ───────────────────────────────────────────────────


class FakeSession(BaseSession):
    """Records every outgoing API call and returns plausible results.

    File transfers are served from a local directory so bot.download() works
    without a network: the test sets `upload_name` and puts that file into
    `serve_dir`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []
        self.responses: list[tuple[object, object]] = []
        self._next_message_id = 100
        self.serve_dir: pathlib.Path | None = None
        self.upload_name: str = "payload.jpg"

    async def close(self) -> None:  # pragma: no cover - nothing to close
        return None

    async def stream_content(  # used by bot.download()
        self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True
    ):
        path = (self.serve_dir or pathlib.Path(".")) / self.upload_name
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    return
                yield chunk

    async def make_request(self, bot: Bot, method, timeout=None):
        self.calls.append(method)
        result = self._result(bot, method)
        self.responses.append((method, result))
        return result

    # -- helpers ------------------------------------------------------------
    def _result(self, bot: Bot, method):
        name = type(method).__name__
        if name == "GetMe":
            return User(id=bot.id, is_bot=True, first_name="TestBot", username="TestSchoolBot")
        if name == "GetFile":
            from aiogram.types import File

            return File(
                file_id="fake-file",
                file_unique_id="fake-unique",
                file_size=1000,
                file_path=self.upload_name,
            )
        if name in {
            "SendMessage",
            "SendPhoto",
            "SendDocument",
            "SendVideo",
            "SendVoice",
            "SendAudio",
            "EditMessageText",
            "EditMessageCaption",
            "EditMessageReplyMarkup",
            "EditMessageMedia",
        }:
            message_id = getattr(method, "message_id", None)
            if not message_id:
                message_id = self._next_message_id
                self._next_message_id += 1
            return _reply_message(bot, method, message_id)
        return True

    # -- query helpers ------------------------------------------------------
    def of(self, name: str) -> list:
        return [c for c in self.calls if type(c).__name__ == name]

    def last(self, name: str):
        found = self.of(name)
        return found[-1] if found else None

    def texts(self) -> list[str]:
        """Text the user actually sees: messages, edits and popup alerts."""
        out = []
        for c in self.calls:
            name = type(c).__name__
            if name in ("SendMessage", "EditMessageText"):
                out.append(c.text or "")
            elif name == "AnswerCallbackQuery" and c.text:
                out.append(c.text)
        return out

    def alerts(self) -> list[str]:
        return [c.text for c in self.of("AnswerCallbackQuery") if c.text]

    def button_labels(self) -> list[str]:
        """Text of every button on the messages sent so far."""
        out: list[str] = []
        for c in self.calls:
            if type(c).__name__ not in ("SendMessage", "EditMessageText"):
                continue
            markup = getattr(c, "reply_markup", None)
            for row in getattr(markup, "inline_keyboard", None) or []:
                for button in row:
                    out.append(button.text)
        return out

    def callbacks(self) -> list[str]:
        """Every callback_data on the buttons of the messages sent so far."""
        out: list[str] = []
        for c in self.calls:
            if type(c).__name__ not in ("SendMessage", "EditMessageText"):
                continue
            markup = getattr(c, "reply_markup", None)
            for row in getattr(markup, "inline_keyboard", None) or []:
                for button in row:
                    if button.callback_data:
                        out.append(button.callback_data)
        return out

    def message_for_button(self, chat_id: int, callback_data: str) -> Message | None:
        seen_messages: set[tuple[int, int]] = set()
        for method, response in reversed(self.responses):
            if not isinstance(response, Message) or response.chat.id != chat_id:
                continue
            message_key = (response.chat.id, response.message_id)
            if message_key in seen_messages:
                continue
            seen_messages.add(message_key)
            markup = getattr(method, "reply_markup", None)
            if any(
                button.callback_data == callback_data
                for row in getattr(markup, "inline_keyboard", []) or []
                for button in row
            ):
                return response
        return None

    def clear(self) -> None:
        self.calls.clear()
        self.responses.clear()

    def file_payloads(self, directory: pathlib.Path) -> None:
        """Create the files bot.download() can serve, then point the session at
        their directory. `upload_name` selects which one is returned."""
        from PIL import Image

        directory.mkdir(parents=True, exist_ok=True)
        self.upload_name = "payload.jpg"
        Image.new("RGB", (80, 60), (20, 120, 200)).save(directory / "payload.jpg")
        Image.new("RGB", (80, 60), (200, 60, 20)).save(directory / "payload.png")

        import fitz

        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "School Notes E2E")
        pdf.save(str(directory / "payload.pdf"))
        pdf.close()

        from docx import Document as _Doc

        doc = _Doc()
        doc.add_paragraph("School Notes E2E")
        doc.save(str(directory / "payload.docx"))

        self.serve_dir = directory


def _reply_message(bot: Bot, method, message_id: int):
    chat_id = getattr(method, "chat_id", None)
    if chat_id is None and getattr(method, "message_id", None) is not None:
        chat = getattr(getattr(method, "chat", None), "id", 0) or 0
    else:
        chat = chat_id or 0
    text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
    return Message(
        message_id=message_id,
        date=datetime.now(),
        chat=Chat(
            id=int(chat),
            type="supergroup" if int(chat) < 0 else "private",
            title="Test Group" if int(chat) < 0 else None,
        ),
        text=text,
        entities=getattr(method, "entities", None),
        reply_markup=getattr(method, "reply_markup", None),
    ).as_(bot)


# ─── Update factories ────────────────────────────────────────────────────────

_seq = {"n": 0}


def next_update_id() -> int:
    _seq["n"] += 1
    return _seq["n"]


def make_user(uid: int, username: str = "user", first: str = "Test", last: str = "User") -> User:
    return User(id=uid, is_bot=False, first_name=first, last_name=last, username=username)


def make_bot_user(uid: int) -> User:
    return User(id=uid, is_bot=True, first_name="TestSchoolBot", username="TestSchoolBot")


def make_chat(cid: int, ctype: str = "private", title: str | None = None) -> Chat:
    return Chat(id=cid, type=ctype, title=title)


def make_message(
    chat: Chat,
    user: User,
    text: str | None = None,
    message_id: int = 1,
    **extra,
) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(),
        chat=chat,
        from_user=user,
        text=text,
        **extra,
    )


def message_update(message: Message, update_id: int | None = None) -> Update:
    return Update(update_id=update_id or next_update_id(), message=message)


def make_callback(
    user: User,
    chat: Chat,
    data: str,
    message: Message | None = None,
    callback_id: str = "cb-1",
) -> CallbackQuery:
    if message is None:
        message = make_message(chat, make_bot_user(TEST_BOT_ID), text="placeholder")
    return CallbackQuery(
        id=callback_id,
        from_user=user,
        chat_instance="chat-instance",
        data=data,
        message=message,
    )


def callback_update(callback: CallbackQuery, update_id: int | None = None) -> Update:
    return Update(update_id=update_id or next_update_id(), callback_query=callback)


TEST_BOT_ID = int(TEST_TOKEN.split(":")[0])


# ─── Fixtures ────────────────────────────────────────────────────────────────


class Harness:
    """Thin driver around the production dispatcher."""

    def __init__(self, bot: Bot, dp: Dispatcher, session: FakeSession):
        self.bot = bot
        self.dp = dp
        self.session = session

    async def feed(self, update: Update):
        return await self.dp.feed_update(self.bot, update)

    async def send(self, chat: Chat, user: User, text: str, message_id: int = 1):
        return await self.feed(
            message_update(make_message(chat, user, text, message_id=message_id))
        )

    async def click(self, chat: Chat, user: User, data: str, message: Message | None = None):
        if message is None:
            message = self.session.message_for_button(chat.id, data)
        if message is None:
            import models

            message = make_message(
                chat,
                make_bot_user(TEST_BOT_ID),
                text="synthetic test keyboard",
                message_id=900_000_000 + next_update_id(),
            )
            await models.register_inline_keyboard(
                chat.id,
                message.message_id,
                user.id,
                [data.split(":", 1)[0]],
                [data],
            )
        return await self.feed(
            callback_update(make_callback(user, chat, data, message=message))
        )

    async def refresh_message(self, chat: Chat, user: User, message_id: int):
        """The 'edited' message the user is now looking at."""
        return make_message(chat, make_bot_user(TEST_BOT_ID), text="", message_id=message_id)

    def texts(self) -> list[str]:
        return self.session.texts()

    def last_text(self) -> str:
        t = self.texts()
        return t[-1] if t else ""

    def all_text(self) -> str:
        return "\n---\n".join(self.texts())

    def clear(self) -> None:
        self.session.clear()


@dataclass
class _Runtime:
    harness: Harness
    mp: pytest.MonkeyPatch


@pytest_asyncio.fixture(scope="session")
async def _runtime():
    """Boot the production wiring exactly once (routers are module singletons)."""
    mp = pytest.MonkeyPatch()
    import main as main_mod
    from aiogram import Bot as _Bot

    bot = _Bot(
        token=TEST_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    session = FakeSession()
    await bot.session.close()
    bot.session = session

    mp.setattr(main_mod, "Bot", lambda **kw: bot)
    mp.setattr(main_mod, "start_scheduler", lambda: None)
    mp.setattr(main_mod, "start_backup_scheduler", lambda b: None)

    async def _stop_backup_scheduler():
        return None

    mp.setattr(main_mod, "stop_backup_scheduler", _stop_backup_scheduler)
    mp.setattr(main_mod, "start_nudge_scheduler", lambda b: None)
    mp.setattr(main_mod, "start_class_notifier", lambda b: None)

    async def _no_polling(self, *args, **kwargs):  # stand-in for start_polling
        return None

    mp.setattr(Dispatcher, "start_polling", _no_polling)

    await main_mod.main()
    await main_mod.on_startup(bot)  # runs init_database + set_my_commands

    yield _Runtime(Harness(bot, main_mod.dp, session), mp)
    await bot.session.close()
    mp.undo()


async def _wipe_db() -> None:
    """Truncate every table (deleting the file is unreliable on Windows)."""
    from database import get_db

    db = await get_db()
    try:
        # FK enforcement off: tables are truncated in arbitrary order
        await db.execute("PRAGMA foreign_keys=OFF")
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        for (name,) in await cur.fetchall():
            await db.execute(f'DELETE FROM "{name}"')
        try:
            await db.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
        await db.commit()
    finally:
        await db.close()


@pytest_asyncio.fixture
async def app(_runtime):
    """A pristine database and clean in-memory state for every test."""
    await _wipe_db()

    import security

    security.rate_limiter._attempts.clear()
    security.admin_sessions._authenticated.clear()

    from middleware import UsageMiddleware  # noqa: F401  (import check)
    from navigation import reset_navigation_state

    reset_navigation_state()

    storage = _runtime.harness.dp.storage
    for bucket in ("state", "data", "lock"):
        store = getattr(storage, bucket, None)
        if isinstance(store, dict):
            store.clear()

    _runtime.harness.session.clear()
    _seq["n"] = 0
    yield _runtime.harness
    _runtime.harness.session.clear()


@pytest.fixture
def owner():
    return make_user(OWNER_ID, username="owner", first="Owner")


@pytest.fixture
def private_chat():
    return make_chat(900001, "private")


@pytest.fixture
def group_chat():
    return make_chat(-100500, "supergroup", title="Test Group")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
