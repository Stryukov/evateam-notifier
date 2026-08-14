"""Нейтральные сообщения бота — не зависят от конкретного мессенджера.

Транспорты (Telegram, MAX) рендерят эти объекты в свою разметку/клавиатуры.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Button:
    """Инлайн-кнопка. `action` — идентификатор действия, который вернётся в on_action."""

    text: str
    action: str


@dataclass(frozen=True)
class OutgoingMessage:
    """Исходящее сообщение: текст + опциональные ряды кнопок.

    `text` — обычный текст (с эмодзи), портируемый между мессенджерами.
    """

    text: str
    buttons: list[list[Button]] = field(default_factory=list)


@dataclass(frozen=True)
class OutgoingDocument:
    """Файл-вложение.

    Содержимое передаём байтами, а не путём: транспорт может работать на другой
    машине, и файловая система у него своя.
    """

    filename: str
    content: bytes
    caption: str = ""
    mime_type: str = "application/octet-stream"
