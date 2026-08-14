"""Рендер доменных объектов в нейтральные сообщения (OutgoingMessage).

Текст — лёгкий HTML-подмножество (`<b>`, `<a href>`): его понимает Telegram
(parse_mode=HTML), а будущий MAX-адаптер при необходимости сконвертирует.
Динамические данные (имена, названия задач) обязательно экранируются.
"""

from __future__ import annotations

import html
from datetime import datetime

from .messages import Button, OutgoingMessage
from .models import Digest, Health, HealthReason, Person, Task

# action-константы для кнопок онбординга
ACTION_CONFIRM_PREFIX = "confirm_link:"  # + person_id
ACTION_REJECT = "reject_link"

# эмодзи
EMOJI_OVERDUE = "🔴"  # срок нарушен
EMOJI_DEADLINE = "⏳"  # срок ещё не наступил
EMOJI_RISK = "🟡"  # под угрозой: отстаём от плана или срок на подходе

#: Горизонт «под угрозой» для вечернего напоминания, дней.
EVENING_RISK_DAYS = 3

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


def priority_badge(priority: int | None) -> str:
    """Значок приоритета — только если он отличается от «Обычного».

    Обычный приоритет стоит у подавляющего большинства задач; показывать его значок
    везде — значит обесценить сам сигнал. Пусто, если приоритет 0 или не задан.
    """
    if not priority:
        return ""
    return PRIORITY_ICONS.get(priority, "")


def _esc(text: str) -> str:
    return html.escape(text or "")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение при числительном: 1 эпик, 2 эпика, 5 эпиков."""
    tens = abs(count) % 100
    if 11 <= tens <= 14:
        return many
    match abs(count) % 10:
        case 1:
            return one
        case 2 | 3 | 4:
            return few
        case _:
            return many


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


def unknown_command_message(command: str) -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            f"Не знаю команду /{_esc(command)}.\n\n"
            "Доступно:\n"
            "/summary — сводка по проектам и эпикам\n"
            "/start — привязать учётную запись EvaTeam"
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


def _evening_task_line(task: Task, now: datetime) -> str:
    """Строка задачи с пометкой, какой именно срок под угрозой.

    Правило светофора берём из core.summary — одно на весь проект, чтобы отчёт
    руководителю и напоминание исполнителю не расходились.
    """
    from .summary import combined_health  # ниже по слою: summary импортирует formatting

    health, reason = combined_health(task.soft_end, task.hard_end, now, EVENING_RISK_DAYS)
    mark = {Health.LATE: EMOJI_OVERDUE, Health.RISK: EMOJI_RISK}.get(health, "")
    prefix = f"{mark} " if mark else ""

    line = f"• {prefix}{_priority_icon(task.priority)} {_code_html(task)}{_esc(task.title)}"
    if reason is HealthReason.LATE_HARD and task.hard_end:
        line += f" — <b>крайний срок {_fmt_date(task.hard_end)}</b>"
    elif reason is HealthReason.BEHIND_PLAN and task.soft_end:
        line += f" — отстаёт от плана ({_fmt_date(task.soft_end)})"
    elif reason is HealthReason.DUE_SOON:
        nearest = task.nearest_end
        if nearest:
            line += f" — срок {_fmt_date(nearest)}"
    return line


def _fmt_date(value: datetime) -> str:
    return value.strftime("%d.%m")


def evening_message(
    person: Person, digest: Digest, now: datetime | None = None
) -> OutgoingMessage:
    """Напоминание в конце дня: закрыть сделанное и подвинуть съехавшие сроки."""
    now = now or datetime.now()
    parts = [
        "🕔 <b>Итоги дня</b>",
        "",
        "Отметьте задачи, которые сегодня завершили, и подвиньте сроки, "
        "если планы изменились — так они не превратятся в просрочку.",
    ]

    if digest.in_progress:
        parts += ["", f"🔧 В работе ({len(digest.in_progress)}):"]
        parts += [_evening_task_line(t, now) for t in digest.in_progress]
    if digest.waiting:
        parts += ["", f"⏳ Ждут подтверждения ({len(digest.waiting)}):"]
        parts += [_evening_task_line(t, now) for t in digest.waiting]
    return OutgoingMessage(text="\n".join(parts))


def overdue_message(person: Person, overdue: list[Task], now: datetime | None = None) -> OutgoingMessage:
    now = now or datetime.now()
    parts = [f"{EMOJI_OVERDUE} Просроченные задачи ({len(overdue)}):", ""]
    parts.extend(_fmt_task_line(t, now) for t in overdue)
    return OutgoingMessage(text="\n".join(parts))
