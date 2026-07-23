"""Абстракция транспорта (мессенджера) — фасад над Telegram/MAX/…

Ядро и оркестратор работают только с этими типами, не зная про конкретный SDK.
Добавление нового мессенджера = новый класс-наследник BotTransport.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from ..core.messages import OutgoingMessage

# Имя транспорта используется как ключ в БД (users.transport).
TransportName = str


@runtime_checkable
class UpdateHandler(Protocol):
    """Обработчик входящих событий. Реализуется в service.BotService."""

    async def on_start(self, transport: TransportName, chat_id: str) -> None: ...

    async def on_text(
        self, transport: TransportName, chat_id: str, text: str
    ) -> None: ...

    async def on_action(
        self, transport: TransportName, chat_id: str, action: str
    ) -> None: ...


class BotTransport(ABC):
    """Базовый транспорт. Наследники: TelegramTransport, (в будущем) MaxTransport."""

    #: уникальное имя транспорта, напр. "telegram"
    name: TransportName

    def __init__(self) -> None:
        self._handler: UpdateHandler | None = None
        #: фоновая задача приёма событий (устанавливается в start())
        self._polling_task: asyncio.Task | None = None

    def set_handler(self, handler: UpdateHandler) -> None:
        self._handler = handler

    @property
    def handler(self) -> UpdateHandler:
        if self._handler is None:
            raise RuntimeError(f"Transport {self.name!r}: handler is not set")
        return self._handler

    @abstractmethod
    async def send_message(self, chat_id: str, message: OutgoingMessage) -> None:
        """Отправить сообщение в чат."""

    @abstractmethod
    async def start(self) -> None:
        """Запустить приём событий (long polling / webhook)."""

    async def wait_closed(self) -> None:
        """Дождаться завершения приёма событий. Пробрасывает ошибку поллинга."""
        if self._polling_task is not None:
            await self._polling_task

    @abstractmethod
    async def stop(self) -> None:
        """Остановить приём и освободить ресурсы."""
