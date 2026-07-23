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
