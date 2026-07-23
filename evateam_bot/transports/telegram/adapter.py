"""Реализация BotTransport поверх aiogram v3.

Рендерит нейтральные OutgoingMessage/Button в сообщения и inline-клавиатуру Telegram
и прокидывает входящие события в UpdateHandler.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ...core.messages import OutgoingMessage
from ..base import BotTransport


class TelegramTransport(BotTransport):
    name = "telegram"

    def __init__(self, token: str, proxy: str | None = None) -> None:
        super().__init__()
        # В корп-сети выход к api.telegram.org только через прокси; aiohttp
        # (в отличие от httpx) сам прокси из окружения не берёт — задаём явно.
        session = AiohttpSession(proxy=proxy) if proxy else None
        self._bot = Bot(token=token, session=session)
        self._dp = Dispatcher()
        self._polling_task: asyncio.Task | None = None
        self._register_routes()

    # --- отправка ---

    async def send_message(self, chat_id: str, message: OutgoingMessage) -> None:
        markup = _to_markup(message)
        await self._bot.send_message(int(chat_id), message.text, reply_markup=markup)

    # --- приём ---

    def _register_routes(self) -> None:
        @self._dp.message(CommandStart())
        async def _on_start(msg: Message) -> None:
            await self.handler.on_start(self.name, str(msg.chat.id))

        @self._dp.message(F.text)
        async def _on_text(msg: Message) -> None:
            await self.handler.on_text(self.name, str(msg.chat.id), msg.text or "")

        @self._dp.callback_query(F.data)
        async def _on_callback(cb: CallbackQuery) -> None:
            chat_id = str(cb.message.chat.id) if cb.message else str(cb.from_user.id)
            await self.handler.on_action(self.name, chat_id, cb.data or "")
            await cb.answer()

    async def start(self) -> None:
        self._polling_task = asyncio.create_task(
            self._dp.start_polling(self._bot, handle_signals=False)
        )

    async def stop(self) -> None:
        await self._dp.stop_polling()
        if self._polling_task:
            await asyncio.gather(self._polling_task, return_exceptions=True)
        await self._bot.session.close()


def _to_markup(message: OutgoingMessage) -> InlineKeyboardMarkup | None:
    if not message.buttons:
        return None
    rows = [
        [InlineKeyboardButton(text=btn.text, callback_data=btn.action) for btn in row]
        for row in message.buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
