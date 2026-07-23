"""Рендер доменных объектов в нейтральные сообщения (OutgoingMessage)."""

from __future__ import annotations

from datetime import datetime

from .messages import Button, OutgoingMessage
from .models import Digest, Person, Task

# action-константы для кнопок онбординга
ACTION_CONFIRM_PREFIX = "confirm_link:"  # + person_id
ACTION_REJECT = "reject_link"


def welcome_message() -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            "👋 Привет! Я напоминаю о задачах из EvaTeam.\n\n"
            "Чтобы начать, отправьте мне свой **email** или **логин** в EvaTeam — "
            "я найду вашу учётную запись."
        )
    )


def confirm_person_message(person: Person) -> OutgoingMessage:
    ident = person.email or person.login or ""
    tail = f" ({ident})" if ident else ""
    return OutgoingMessage(
        text=f"Нашёл: **{person.name}**{tail}\nЭто вы?",
        buttons=[
            [
                Button(text="✅ Это я", action=f"{ACTION_CONFIRM_PREFIX}{person.id}"),
                Button(text="❌ Нет", action=ACTION_REJECT),
            ]
        ],
    )


def person_not_found_message(query: str) -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            f"Не нашёл пользователя по «{query}». "
            "Проверьте email/логин и попробуйте ещё раз."
        )
    )


def linked_message(person: Person) -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            f"Готово! Вы привязаны как **{person.name}**.\n"
            "Каждое утро я буду присылать план дня и напоминать о просроченных задачах. ✨"
        )
    )


def rejected_message() -> OutgoingMessage:
    return OutgoingMessage(
        text="Хорошо. Отправьте другой email или логин, чтобы найти нужную учётную запись."
    )


def _fmt_deadline(deadline: datetime | None) -> str:
    if deadline is None:
        return ""
    return deadline.strftime("%d.%m %H:%M")


def _fmt_task_line(task: Task, *, show_deadline: bool = True) -> str:
    code = f"[{task.code}] " if task.code else ""
    line = f"• {code}{task.title}"
    if show_deadline and task.deadline is not None:
        line += f" — ⏳ {_fmt_deadline(task.deadline)}"
    return line


def digest_message(person: Person, digest: Digest) -> OutgoingMessage:
    if digest.is_empty:
        return OutgoingMessage(text="🌅 Доброе утро! Активных задач на сегодня нет 🎉")

    parts: list[str] = ["🌅 Доброе утро! Ваш план дня:"]
    if digest.in_progress:
        parts.append("")
        parts.append(f"🔧 В работе ({len(digest.in_progress)}):")
        parts.extend(_fmt_task_line(t) for t in digest.in_progress)
    if digest.waiting:
        parts.append("")
        parts.append(f"⏸ Ожидают ({len(digest.waiting)}):")
        parts.extend(_fmt_task_line(t) for t in digest.waiting)
    return OutgoingMessage(text="\n".join(parts))


def overdue_message(person: Person, overdue: list[Task]) -> OutgoingMessage:
    parts: list[str] = [f"⏰ Просроченные задачи ({len(overdue)}):", ""]
    parts.extend(_fmt_task_line(t) for t in overdue)
    return OutgoingMessage(text="\n".join(parts))
