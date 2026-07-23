"""Рендер доменных объектов в нейтральные сообщения (OutgoingMessage).

Текст — лёгкий HTML-подмножество (`<b>`, `<a href>`): его понимает Telegram
(parse_mode=HTML), а будущий MAX-адаптер при необходимости сконвертирует.
Динамические данные (имена, названия задач) обязательно экранируются.
"""

from __future__ import annotations

import html
from datetime import datetime

from .messages import Button, OutgoingMessage
from .models import Digest, Person, Task

# action-константы для кнопок онбординга
ACTION_CONFIRM_PREFIX = "confirm_link:"  # + person_id
ACTION_REJECT = "reject_link"

# эмодзи
EMOJI_OVERDUE = "🔴"  # срок нарушен
EMOJI_DEADLINE = "⏳"  # срок ещё не наступил

# Иконки приоритета — по значениям EvaTeam (0=Обычный), в стиле таск-трекера.
PRIORITY_ICONS = {
    3: "⛔",  # Блокирующий
    2: "🔥",  # Критичный
    1: "🔺",  # Высокий
    0: "🟰",  # Обычный
    -1: "🔽",  # Низкий
    -2: "⏬",  # Минимальный
}


def _priority_icon(priority: int | None) -> str:
    return PRIORITY_ICONS.get(priority if priority is not None else 0, "🟰")


def _esc(text: str) -> str:
    return html.escape(text or "")


def welcome_message() -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            "👋 Привет! Я напоминаю о задачах из EvaTeam.\n\n"
            "Чтобы начать, отправьте мне свой <b>email</b> или <b>логин</b> в EvaTeam — "
            "я найду вашу учётную запись."
        )
    )


def confirm_person_message(person: Person) -> OutgoingMessage:
    ident = person.email or person.login or ""
    tail = f" ({_esc(ident)})" if ident else ""
    return OutgoingMessage(
        text=f"Нашёл: <b>{_esc(person.name)}</b>{tail}\nЭто вы?",
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
            f"Не нашёл пользователя по «{_esc(query)}». "
            "Проверьте email/логин и попробуйте ещё раз."
        )
    )


def linked_message(person: Person) -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            f"Готово! Вы привязаны как <b>{_esc(person.name)}</b>.\n"
            "Каждое утро я буду присылать план дня и напоминать о просроченных задачах. ✨"
        )
    )


def rejected_message() -> OutgoingMessage:
    return OutgoingMessage(
        text="Хорошо. Отправьте другой email или логин, чтобы найти нужную учётную запись."
    )


def _fmt_deadline(deadline: datetime) -> str:
    return deadline.strftime("%d.%m %H:%M")


def _code_html(task: Task) -> str:
    """Код задачи как ссылка на таск-трекер (если известен URL)."""
    if not task.code:
        return ""
    if task.url:
        return f'<a href="{_esc(task.url)}">{_esc(task.code)}</a> '
    return f"{_esc(task.code)} "


def _fmt_task_line(task: Task, now: datetime) -> str:
    board = f"[{_esc(task.project_name)}] " if task.project_name else ""
    line = f"• {_priority_icon(task.priority)} {_code_html(task)}{board}{_esc(task.title)}"
    if task.deadline is not None:
        overdue = task.is_overdue(now)
        emoji = EMOJI_OVERDUE if overdue else EMOJI_DEADLINE
        stamp = _fmt_deadline(task.deadline)
        stamp = f"<b>{stamp}</b>" if overdue else stamp
        line += f" — {emoji} {stamp}"
    return line


def _section(title: str, tasks: list[Task], now: datetime) -> list[str]:
    if not tasks:
        return []
    lines = ["", f"{title} ({len(tasks)}):"]
    lines.extend(_fmt_task_line(t, now) for t in tasks)
    return lines


def digest_message(person: Person, digest: Digest, now: datetime | None = None) -> OutgoingMessage:
    now = now or datetime.now()
    if digest.is_empty:
        return OutgoingMessage(text="🌅 Доброе утро! Активных задач на сегодня нет 🎉")

    parts = ["🌅 Доброе утро! Ваш план дня:"]
    parts += _section("🔧 В работе", digest.in_progress, now)
    parts += _section("⏳ Ждут подтверждения", digest.waiting, now)
    # «Не начаты» показываем только числом, без списка.
    if digest.not_started:
        parts += ["", f"🆕 Не начатых задач: {len(digest.not_started)}"]
    return OutgoingMessage(text="\n".join(parts))


def overdue_message(person: Person, overdue: list[Task], now: datetime | None = None) -> OutgoingMessage:
    now = now or datetime.now()
    parts = [f"{EMOJI_OVERDUE} Просроченные задачи ({len(overdue)}):", ""]
    parts.extend(_fmt_task_line(t, now) for t in overdue)
    return OutgoingMessage(text="\n".join(parts))
