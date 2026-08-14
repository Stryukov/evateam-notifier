"""Абстракция транспорта (мессенджера) — фасад над Telegram/MAX/…

Ядро и оркестратор работают только с этими типами, не зная про конкретный SDK.
Добавление нового мессенджера = новый класс-наследник BotTransport.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from ..core.messages import OutgoingDocument, OutgoingMessage

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

    async def on_command(
        self, transport: TransportName, chat_id: str, command: str, args: str
    ) -> None:
        """Команда вида `/summary`. `command` — нормализован: без слэша, в нижнем
        регистре, без `@botname`."""
        ...


class BotTransport(ABC):
    """Базовый транспорт. Наследники: TelegramTransport, (в будущем) MaxTransport."""

    #: уникальное имя транспорта, напр. "telegram"
    name: TransportName

    #: умеет ли транспорт отправлять файлы. Сервис проверяет флаг ДО отправки и
    #: деградирует в «текст + путь к файлу», а не ловит исключение.
    supports_documents: bool = False

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

    async def send_document(self, chat_id: str, document: OutgoingDocument) -> None:
        """Отправить файл. Не абстрактный: новый транспорт не обязан это уметь сразу."""
        raise NotImplementedError(f"Transport {self.name!r} не умеет отправлять файлы")

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

    async def aclose(self) -> None:
        """Освободить сетевые ресурсы без остановки поллинга (для one-off задач)."""
