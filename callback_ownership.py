"""Persistent ownership checks for bot messages with inline callbacks."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.methods import DeleteMessage, EditMessageReplyMarkup, TelegramMethod
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import models
from logger import logger
from navigation import remember_outgoing_screen

active_user_id: ContextVar[int | None] = ContextVar("active_user_id", default=None)
active_chat_id: ContextVar[int | None] = ContextVar("active_chat_id", default=None)


class InlineKeyboardOwnershipMiddleware(BaseMiddleware):
    """Fail closed unless the callback matches its persisted owner and button."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        token: Token[int | None] = active_user_id.set(user.id if user else None)
        chat = getattr(event, "chat", None)
        if chat is None and isinstance(event, CallbackQuery) and isinstance(event.message, Message):
            chat = event.message.chat
        chat_token: Token[int | None] = active_chat_id.set(
            chat.id if chat is not None else None
        )
        try:
            if isinstance(event, CallbackQuery):
                if not isinstance(event.message, Message):
                    await event.answer(
                        "این دکمه به پیام تعاملی معتبری متصل نیست.",
                        show_alert=True,
                    )
                    return None

                message = event.message
                try:
                    ownership = await models.get_inline_keyboard_ownership(
                        message.chat.id, message.message_id
                    )
                except Exception as exc:
                    logger.error(
                        "Inline callback ownership lookup failed for "
                        f"chat={message.chat.id}, message={message.message_id}: {exc}"
                    )
                    await event.answer(
                        "بررسی دسترسی موقتاً ممکن نیست؛ دوباره تلاش کنید.",
                        show_alert=True,
                    )
                    raise

                if ownership is None:
                    await event.answer(
                        "این دکمه قدیمی یا نامعتبر است؛ منو را دوباره باز کنید.",
                        show_alert=True,
                    )
                    return None

                if ownership["owner_user_id"] != event.from_user.id:
                    await event.answer(
                        "این دکمه متعلق به شما نیست.",
                        show_alert=True,
                    )
                    return None

                if event.data not in ownership["callback_data"]:
                    await event.answer(
                        "این دکمه دیگر فعال نیست؛ منو را دوباره باز کنید.",
                        show_alert=True,
                    )
                    return None

            return await handler(event, data)
        finally:
            active_chat_id.reset(chat_token)
            active_user_id.reset(token)


class InlineKeyboardOwnershipSessionMiddleware:
    """Register outgoing inline keyboards after Telegram assigns message IDs."""

    async def __call__(
        self,
        make_request: Callable[..., Awaitable[Any]],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Any:
        chat_id = getattr(method, "chat_id", None)
        message_id = getattr(method, "message_id", None)

        try:
            numeric_chat_id = int(chat_id) if chat_id is not None else None
        except (TypeError, ValueError):
            numeric_chat_id = None

        if (
            numeric_chat_id is not None
            and numeric_chat_id < 0
            and isinstance(getattr(method, "reply_markup", None), InlineKeyboardMarkup)
            and active_user_id.get() is None
        ):
            raise RuntimeError(
                "Cannot send an interactive group message without an initiating user."
            )

        result = await make_request(bot, method)

        markup = getattr(method, "reply_markup", None)
        if (
            isinstance(result, Message)
            and numeric_chat_id is not None
            and active_chat_id.get() == numeric_chat_id
        ):
            text = getattr(method, "text", None)
            kind = "text"
            entities = getattr(method, "entities", None) or result.entities
            if text is None:
                text = getattr(method, "caption", None)
                entities = getattr(method, "caption_entities", None) or result.caption_entities
                kind = "caption"
            remember_outgoing_screen(
                numeric_chat_id,
                active_user_id.get(),
                result,
                text=text,
                entities=entities,
                reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
                kind=kind,
                parse_mode=getattr(method, "parse_mode", None),
            )

        if isinstance(method, DeleteMessage):
            if chat_id is not None and message_id is not None:
                await models.remove_inline_keyboard_ownership(chat_id, message_id)
            return result

        if isinstance(method, EditMessageReplyMarkup) and method.reply_markup is None:
            if chat_id is not None and message_id is not None:
                await models.remove_inline_keyboard_ownership(chat_id, message_id)
            return result

        if not isinstance(markup, InlineKeyboardMarkup):
            return result

        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        if not callback_data:
            if chat_id is not None and message_id is not None:
                await models.remove_inline_keyboard_ownership(chat_id, message_id)
            return result

        if isinstance(result, Message):
            chat_id = result.chat.id
            message_id = result.message_id
        if chat_id is None or message_id is None:
            return result

        try:
            normalized_chat_id = int(chat_id)
        except (TypeError, ValueError):
            logger.warning(
                f"Cannot register inline keyboard for non-numeric chat {chat_id!r}"
            )
            return result

        actor_id = active_user_id.get()
        source_chat_id = active_chat_id.get()
        if source_chat_id == normalized_chat_id and actor_id is not None:
            owner_user_id = actor_id
        elif normalized_chat_id > 0:
            owner_user_id = normalized_chat_id
        else:
            owner_user_id = actor_id
        if owner_user_id is None:
            raise RuntimeError(
                "Cannot send an interactive group message without an initiating user."
            )

        operation_types = sorted({value.split(":", 1)[0] for value in callback_data})
        await models.register_inline_keyboard(
            normalized_chat_id,
            int(message_id),
            int(owner_user_id),
            operation_types,
            callback_data,
        )
        return result
