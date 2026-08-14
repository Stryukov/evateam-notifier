"""Реализация BotTransport поверх aiogram v3.

Рендерит нейтральные OutgoingMessage/Button в сообщения и inline-клавиатуру Telegram
и прокидывает входящие события в UpdateHandler.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ...core.messages import OutgoingDocument, OutgoingMessage, Sender
from ..base import BotTransport

logger = logging.getLogger(__name__)

#: Лимит подписи к файлу в Telegram (у текста сообщения — 4096).
CAPTION_LIMIT = 1024

#: Команды в меню Telegram.
BOT_COMMANDS = [
    BotCommand(command="summary", description="Сводка по проектам и эпикам"),
    BotCommand(command="start", description="Привязать учётную запись EvaTeam"),
]


class TelegramTransport(BotTransport):
    name = "telegram"
    supports_documents = True

    def __init__(self, token: str, proxy: str | None = None) -> None:
        super().__init__()
        # В корп-сети выход к api.telegram.org только через прокси; aiohttp
        # (в отличие от httpx) сам прокси из окружения не берёт — задаём явно.
        session = AiohttpSession(proxy=proxy) if proxy else None
        self._bot = Bot(
            token=token,
            session=session,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True,
            ),
        )
        self._dp = Dispatcher()
        self._polling_task: asyncio.Task | None = None
        self._register_routes()

    # --- отправка ---

    async def send_message(self, chat_id: str, message: OutgoingMessage) -> None:
        markup = _to_markup(message)
        await self._bot.send_message(int(chat_id), message.text, reply_markup=markup)

    async def send_document(self, chat_id: str, document: OutgoingDocument) -> None:
        file = BufferedInputFile(document.content, filename=document.filename)
        await self._bot.send_document(
            int(chat_id), file, caption=_clip_caption(document.caption)
        )

    # --- приём ---

    def _register_routes(self) -> None:
        # ВАЖНО: aiogram проверяет хендлеры в порядке регистрации. Роут команд обязан
        # стоять между CommandStart и F.text — иначе «/summary» уедет в on_text и
        # будет истолкован как поиск сотрудника по логину.
        @self._dp.message(CommandStart())
        async def _on_start(msg: Message) -> None:
            await self.handler.on_start(self.name, _sender(msg))

        @self._dp.message(F.text.startswith("/"))
        async def _on_command(msg: Message) -> None:
            command, args = _parse_command(msg.text or "")
            await self.handler.on_command(self.name, _sender(msg), command, args)

        @self._dp.message(F.text)
        async def _on_text(msg: Message) -> None:
            await self.handler.on_text(self.name, _sender(msg), msg.text or "")

        @self._dp.callback_query(F.data)
        async def _on_callback(cb: CallbackQuery) -> None:
            chat_id = str(cb.message.chat.id) if cb.message else str(cb.from_user.id)
            sender = Sender(
                chat_id=chat_id,
                user_id=str(cb.from_user.id) if cb.from_user else None,
                username=cb.from_user.username if cb.from_user else None,
            )
            await self.handler.on_action(self.name, sender, cb.data or "")
            await cb.answer()

    async def start(self) -> None:
        try:
            await self._bot.set_my_commands(BOT_COMMANDS)
        except Exception:  # noqa: BLE001 — меню команд не стоит падения бота
            logger.warning("Не удалось установить меню команд", exc_info=True)
        self._polling_task = asyncio.create_task(
            self._dp.start_polling(self._bot, handle_signals=False)
        )

    async def stop(self) -> None:
        if self._polling_task is not None:
            await self._dp.stop_polling()
            await asyncio.gather(self._polling_task, return_exceptions=True)
        await self.aclose()

    async def aclose(self) -> None:
        await self._bot.session.close()


def _sender(msg: Message) -> Sender:
    """Отправитель события: чат для ответа + личность для проверки доступа."""
    user = msg.from_user
    return Sender(
        chat_id=str(msg.chat.id),
        user_id=str(user.id) if user else None,
        username=user.username if user else None,
    )


def _parse_command(text: str) -> tuple[str, str]:
    """«/summary@my_bot аргумент» -> ("summary", "аргумент")."""
    command, _, args = text[1:].partition(" ")
    return command.split("@", 1)[0].strip().lower(), args.strip()


def _clip_caption(caption: str) -> str:
    if len(caption) <= CAPTION_LIMIT:
        return caption
    return caption[: CAPTION_LIMIT - 1] + "…"


def _to_markup(message: OutgoingMessage) -> InlineKeyboardMarkup | None:
    if not message.buttons:
        return None
    rows = [
        [InlineKeyboardButton(text=btn.text, callback_data=btn.action) for btn in row]
        for row in message.buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
