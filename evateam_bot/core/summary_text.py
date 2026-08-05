"""Сводка по проектам для мессенджера — коротко и по исключениям.

Принцип BLUF: вердикт первой строкой, дальше только то, что требует решения.
Зелёные эпики схлопываются в число — руководителю важно, что сломано, а не полный
перечень. Подробности живут в HTML-отчёте, который прикладывается файлом.
"""

from __future__ import annotations

from datetime import datetime

from .formatting import _esc
from .messages import OutgoingMessage
from .models import EpicSummary, Health, HealthReason, Summary

#: Эмодзи светофора. Единственный доступный «цвет» в Telegram.
HEALTH_EMOJI: dict[Health, str] = {
    Health.LATE: "🔴",
    Health.RISK: "🟡",
    Health.OK: "🟢",
    Health.NO_DATE: "⚪",
}

HEALTH_LABEL: dict[Health, str] = {
    Health.LATE: "срыв срока",
    Health.RISK: "под угрозой",
    Health.OK: "по плану",
    Health.NO_DATE: "без срока",
}

#: Лимит Telegram — 4096 символов; оставляем запас на хвост.
TEXT_LIMIT = 3900


def building_message() -> OutgoingMessage:
    return OutgoingMessage(text="⏳ Собираю сводку по проектам…")


def summary_error_message(reason: str) -> OutgoingMessage:
    return OutgoingMessage(
        text=f"⚠️ Не удалось собрать сводку: {_esc(reason)}\n\nПопробуйте позже."
    )


def empty_summary_message(summary: Summary) -> OutgoingMessage:
    """Отчёт пуст — объясняем почему и что поменять, а не показываем пустую страницу."""
    codes = ", ".join(f"<code>{_esc(c)}</code>" for c in summary.status_codes) or "—"
    lines = [
        "📊 <b>Сводка по проектам</b>",
        "",
        f"Эпиков с такими статусами не найдено: {codes}.",
        f"Просмотрено эпиков: {summary.epics_total_scanned}.",
    ]
    if summary.epics_unknown_status:
        lines.append(f"Без распознанного статуса: {summary.epics_unknown_status}.")
    lines += [
        "",
        "Либо переведите эпики в нужный статус в EvaTeam, либо расширьте список "
        "в <code>SUMMARY_EPIC_STATUS_CODES</code> (файл <code>.env</code>) — "
        "например, добавьте <code>open</code>.",
    ]
    return OutgoingMessage(text="\n".join(lines))


def summary_message(
    summary: Summary, *, now: datetime | None = None, max_items: int = 5
) -> OutgoingMessage:
    if summary.is_empty:
        return empty_summary_message(summary)

    now = now or summary.generated_at
    kpi = summary.kpi
    lines = [
        f"📊 <b>Сводка по проектам</b> — {now.strftime('%d.%m.%Y')}",
        "",
        _verdict(summary),
        "",
        f"Проектов: {kpi.projects} · эпиков: {kpi.epics} · задач в работе: {kpi.tasks}",
        f"Задач с плановой датой: {kpi.date_coverage_pct}%",
    ]

    lines += _epic_section("🔴 Требуют решения", _by_health(summary, Health.LATE), max_items)
    lines += _epic_section(
        f"🟡 Под угрозой (≤ {summary.risk_days} дн.)", _by_health(summary, Health.RISK), max_items
    )
    lines += _blockers_section(summary, max_items)
    lines += _gaps_section(summary)

    healthy = len(_by_health(summary, Health.OK))
    if healthy:
        lines += ["", f"🟢 По плану: {healthy}"]

    lines += ["", "Подробности — в приложенном HTML-отчёте."]
    return OutgoingMessage(text=_clip(lines))


# --- секции --------------------------------------------------------------------


def _verdict(summary: Summary) -> str:
    """Одна строка, ради которой всё и затевалось."""
    kpi = summary.kpi
    parts = []
    if kpi.epics_late:
        parts.append(f"🔴 сорван крайний срок у эпиков: {kpi.epics_late}")
    if kpi.epics_risk:
        parts.append(f"🟡 под угрозой: {kpi.epics_risk}")
    if parts:
        return "<b>" + ", ".join(parts) + "</b>"
    if kpi.epics_no_date == kpi.epics and kpi.epics:
        return "<b>⚪ Сроков нет ни у одного эпика — статус не определить</b>"
    return "<b>🟢 Всё по плану</b>"


def _by_health(summary: Summary, health: Health) -> list[EpicSummary]:
    return [e for e in summary.all_epics if e.health is health]


def _epic_section(title: str, epics: list[EpicSummary], max_items: int) -> list[str]:
    if not epics:
        return []
    lines = ["", f"<b>{title}</b>"]
    for item in epics[:max_items]:
        lines.append(f"• {_epic_line(item)}")
    if len(epics) > max_items:
        lines.append(f"  …и ещё {len(epics) - max_items}")
    return lines


def _epic_line(item: EpicSummary) -> str:
    epic = item.epic
    project = f"[{_esc(epic.project_name)}] " if epic.project_name else ""
    code = _link(epic.code, epic.url)
    tail = [note for note in (_deadline_note(item),) if note]
    if item.is_idle:
        tail.append("нет задач в работе")
    elif item.total:
        tail.append(f"задач: {item.total}")
    suffix = f" — {', '.join(tail)}" if tail else ""
    return f"{code}{project}{_esc(epic.title)}{suffix}"


def _deadline_note(item: EpicSummary) -> str:
    """Назвать нарушенный срок: крайний и плановый — разные вещи."""
    if item.reason is HealthReason.LATE_HARD and item.days_left_hard is not None:
        return f"просрочен крайний срок на {abs(item.days_left_hard)} дн."
    if item.reason is HealthReason.BEHIND_PLAN and item.days_left is not None:
        return f"отстаёт от плана на {abs(item.days_left)} дн."
    if item.reason is HealthReason.DUE_SOON:
        if item.days_left_hard is not None and item.days_left_hard >= 0:
            return f"крайний срок через {item.days_left_hard} дн."
        if item.days_left is not None and item.days_left >= 0:
            return f"плановый срок через {item.days_left} дн."
    if item.open_ended:
        return "окончание не задано"
    return ""


def _blockers_section(summary: Summary, max_items: int) -> list[str]:
    lines: list[str] = []
    lines += _task_section(
        "⛔ Сорван крайний срок", summary.blockers, max_items, hard=True
    )
    lines += _task_section(
        "🟡 Отстают от плана", summary.behind_plan, max_items, hard=False
    )
    return lines


def _task_section(
    title: str, rows: list[tuple[EpicSummary, "object"]], max_items: int, *, hard: bool
) -> list[str]:
    if not rows:
        return []
    lines = ["", f"<b>{title}</b>"]
    for _, task in rows[:max_items]:
        who = _esc(task.assignee) if task.assignee else "без исполнителя"
        end = task.hard_end if hard else task.soft_end
        when = end.strftime("%d.%m") if end else "—"
        label = "крайний" if hard else "план"
        lines.append(
            f"• {_link(task.code, task.url)}{_esc(task.title)} — {who}, {label} {when}"
        )
    if len(rows) > max_items:
        lines.append(f"  …и ещё {len(rows) - max_items}")
    return lines


def _gaps_section(summary: Summary) -> list[str]:
    """Пробелы в планировании — самостоятельный управленческий сигнал."""
    kpi = summary.kpi
    gaps = []
    if kpi.epics_no_date:
        gaps.append(f"эпиков без сроков: {kpi.epics_no_date}")
    if kpi.epics_open_ended:
        gaps.append(f"эпиков без планового окончания: {kpi.epics_open_ended}")
    if kpi.tasks_without_date:
        gaps.append(f"задач без плановой даты: {kpi.tasks_without_date}")
    if kpi.tasks_without_assignee:
        gaps.append(f"задач без исполнителя: {kpi.tasks_without_assignee}")
    if kpi.epics_idle:
        gaps.append(f"эпиков без задач в работе: {kpi.epics_idle}")
    if not gaps:
        return []
    return ["", "<b>⚪ Пробелы в планировании</b>", "• " + "\n• ".join(gaps)]


# --- утилиты -------------------------------------------------------------------


def _link(code: str | None, url: str | None) -> str:
    if not code:
        return ""
    if url:
        return f'<a href="{_esc(url)}">{_esc(code)}</a> '
    return f"{_esc(code)} "


def _clip(lines: list[str], limit: int = TEXT_LIMIT) -> str:
    """Обрезать по строкам, чтобы не упереться в лимит Telegram."""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    kept: list[str] = []
    length = 0
    for line in lines:
        if length + len(line) + 1 > limit - 20:
            break
        kept.append(line)
        length += len(line) + 1
    kept.append("…")
    return "\n".join(kept)
