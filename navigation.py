"""Per-user navigation history and the global /cl back command support."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, MessageEntity


MAX_BACK_STEPS = 30


@dataclass
class Screen:
    message: Message
    text: str
    entities: list[MessageEntity] | None
    reply_markup: InlineKeyboardMarkup | None
    kind: str
    parse_mode: str | None


@dataclass
class BackStep:
    state: str | None
    data: dict[str, Any]
    screen: Screen | None


_history: dict[tuple[int, int], list[BackStep]] = {}
_last_screen: dict[tuple[int, int], Screen] = {}


def _key(chat_id: int, user_id: int) -> tuple[int, int]:
    return chat_id, user_id


def _screen_from_message(message: Message) -> Screen | None:
    if message.text is not None:
        return Screen(
            message=message,
            text=message.text,
            entities=message.entities,
            reply_markup=message.reply_markup,
            kind="text",
            parse_mode=None,
        )
    if message.caption is not None:
        return Screen(
            message=message,
            text=message.caption,
            entities=message.caption_entities,
            reply_markup=message.reply_markup,
            kind="caption",
            parse_mode=None,
        )
    return None


def remember_outgoing_screen(
    chat_id: int,
    user_id: int | None,
    message: Message,
    *,
    text: str | None,
    entities: list[MessageEntity] | None,
    reply_markup: InlineKeyboardMarkup | None,
    kind: str,
    parse_mode: str | None,
) -> None:
    if user_id is None or text is None:
        return
    _last_screen[_key(chat_id, user_id)] = Screen(
        message=message,
        text=text,
        entities=entities,
        reply_markup=reply_markup,
        kind=kind,
        parse_mode=parse_mode,
    )


def clear_back_history(chat_id: int, user_id: int) -> None:
    _history.pop(_key(chat_id, user_id), None)


def reset_navigation_state() -> None:
    """Clear in-memory state between isolated workflow tests."""
    _history.clear()
    _last_screen.clear()


def pop_previous_step(chat_id: int, user_id: int) -> BackStep | None:
    steps = _history.get(_key(chat_id, user_id))
    if not steps:
        return None
    step = steps.pop()
    if not steps:
        _history.pop(_key(chat_id, user_id), None)
    return step


def _signature(screen: Screen | None) -> tuple[Any, ...] | None:
    if screen is None:
        return None
    return (
        screen.text,
        repr(screen.entities),
        repr(screen.reply_markup),
        screen.kind,
        screen.parse_mode,
        screen.message.message_id,
    )


class BackNavigationMiddleware(BaseMiddleware):
    """Remember the prior FSM data and screen when an interaction advances."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        message = (
            event.message if isinstance(event, CallbackQuery)
            else event if isinstance(event, Message)
            else None
        )
        state: FSMContext | None = data.get("state")
        if user is None or message is None or state is None:
            return await handler(event, data)

        key = _key(message.chat.id, user.id)
        command = (
            message.text.split(maxsplit=1)[0].split("@", 1)[0].casefold()
            if isinstance(event, Message) and message.text
            else ""
        )
        if command == "/cl":
            return await handler(event, data)
        if command in {"/start", "/help", "/راهنما"}:
            clear_back_history(*key)
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "noop":
            return await handler(event, data)

        previous_state = await state.get_state()
        previous_data = deepcopy(await state.get_data())
        previous_screen = _last_screen.get(key)
        if isinstance(event, CallbackQuery):
            event_screen = _screen_from_message(message)
            if (
                event_screen is not None
                and previous_screen is not None
                and event_screen.message.message_id == previous_screen.message.message_id
            ):
                event_screen.entities = event_screen.entities or previous_screen.entities
                event_screen.reply_markup = (
                    event_screen.reply_markup or previous_screen.reply_markup
                )
                event_screen.parse_mode = (
                    event_screen.parse_mode or previous_screen.parse_mode
                )
            previous_screen = event_screen or previous_screen
        previous_screen_signature = _signature(previous_screen)

        result = await handler(event, data)

        current_state = await state.get_state()
        current_data = await state.get_data()
        current_screen = _last_screen.get(key)
        changed = (
            current_state != previous_state
            or current_data != previous_data
            or _signature(current_screen) != previous_screen_signature
        )
        if changed:
            steps = _history.setdefault(key, [])
            steps.append(BackStep(previous_state, previous_data, previous_screen))
            del steps[:-MAX_BACK_STEPS]
        return result


async def restore_previous_screen(message: Message, screen: Screen) -> bool:
    """Replace the latest bot screen with the prior text and inline keyboard."""
    from utils import safe_edit_text

    latest = _last_screen.get(_key(message.chat.id, message.from_user.id))
    if latest is None:
        return False
    if latest.kind == "caption":
        await message.answer(
            screen.text,
            entities=screen.entities or None,
            parse_mode=None if screen.entities else screen.parse_mode,
            reply_markup=screen.reply_markup,
        )
        return True

    await safe_edit_text(
        latest.message,
        screen.text,
        entities=screen.entities or None,
        parse_mode=None if screen.entities else screen.parse_mode,
        reply_markup=screen.reply_markup,
    )
    return True
