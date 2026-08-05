"""Сборка управленческой сводки по проектам и эпикам.

Чистая логика: ни сети, ни БД, ни файлов — на вход `Portfolio`, на выход `Summary`.

Принципы отчёта для руководителя:
- статус («светофор») считается из плановых дат автоматически, вручную не ставится;
- «худший ребёнок»: проблема дочерней задачи поднимается до эпика и проекта;
- пропуски в планировании (нет срока, нет исполнителя, эпик без задач) — это
  самостоятельный сигнал, а не повод показать зелёный.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import (
    HEALTH_SEVERITY,
    Epic,
    EpicSummary,
    Health,
    Portfolio,
    ProjectSummary,
    StatusCategory,
    Summary,
    SummaryKpi,
    Task,
)

#: Коды статусов эпиков по умолчанию (CmfStatus.code).
DEFAULT_EPIC_STATUS_CODES: tuple[str, ...] = ("in_progress", "in_review", "pause")

NO_PROJECT_NAME = "(без проекта)"


@dataclass(frozen=True)
class SummaryOptions:
    status_codes: tuple[str, ...] = DEFAULT_EPIC_STATUS_CODES
    risk_days: int = 7
    include_orphan_tasks: bool = False


def date_health(end: datetime | None, now: datetime, risk_days: int) -> Health:
    """Светофор по плановому концу. Сравниваем по датам, а не по времени."""
    if end is None:
        return Health.NO_DATE
    days = (end.date() - now.date()).days
    if days < 0:
        return Health.LATE
    if days <= risk_days:
        return Health.RISK
    return Health.OK


def worst(healths: Iterable[Health]) -> Health:
    """Роллап «худший ребёнок». Пустая коллекция -> NO_DATE."""
    items = list(healths)
    if not items:
        return Health.NO_DATE
    return max(items, key=lambda h: HEALTH_SEVERITY[h])


def build_summary(
    portfolio: Portfolio,
    *,
    now: datetime | None = None,
    options: SummaryOptions | None = None,
) -> Summary:
    now = now or datetime.now()
    options = options or SummaryOptions()

    selected: list[Epic] = []
    unknown_status = 0
    for epic in portfolio.epics:
        if not epic.status_code:
            unknown_status += 1
            continue
        # Пустой список кодов — аварийный клапан: берём все эпики.
        if options.status_codes and epic.status_code.lower() not in options.status_codes:
            continue
        selected.append(epic)

    epic_summaries = [
        _build_epic_summary(epic, portfolio.tasks_by_epic.get(epic.id, []), now, options)
        for epic in selected
    ]
    projects = _group_by_project(epic_summaries, portfolio.project_names)

    return Summary(
        generated_at=now,
        projects=projects,
        kpi=_build_kpi(projects),
        status_codes=tuple(options.status_codes),
        risk_days=options.risk_days,
        epics_total_scanned=len(portfolio.epics),
        epics_unknown_status=unknown_status,
        orphan_tasks=list(portfolio.orphan_tasks) if options.include_orphan_tasks else [],
    )


def _build_epic_summary(
    epic: Epic, tasks: list[Task], now: datetime, options: SummaryOptions
) -> EpicSummary:
    task_health = {task.id: date_health(task.effective_end, now, options.risk_days) for task in tasks}
    ordered = sorted(tasks, key=lambda t: _task_sort_key(t, task_health[t.id]))

    start, end, derived = _epic_dates(epic, tasks)
    health = worst(
        [date_health(end, now, options.risk_days), *(task_health[t.id] for t in tasks)]
    )
    days_left = (end.date() - now.date()).days if end else None

    return EpicSummary(
        epic=epic,
        tasks=ordered,
        health=health,
        start_date=start,
        end_date=end,
        days_left=days_left,
        in_progress=sum(1 for t in tasks if t.status_category is StatusCategory.IN_PROGRESS),
        in_review=sum(1 for t in tasks if t.status_category is StatusCategory.WAITING),
        tasks_without_date=sum(1 for t in tasks if t.effective_end is None),
        tasks_without_assignee=sum(1 for t in tasks if not t.assignee),
        blockers=[t for t in ordered if task_health[t.id] is Health.LATE],
        is_idle=not tasks,
        dates_are_derived=derived,
    )


def _epic_dates(epic: Epic, tasks: list[Task]) -> tuple[datetime | None, datetime | None, bool]:
    """Плановые даты эпика; при их отсутствии выводим из задач."""
    start, end = epic.plan_start, epic.effective_end
    derived = False

    if start is None:
        starts = [t.plan_start for t in tasks if t.plan_start]
        if starts:
            start, derived = min(starts), True
    if end is None:
        ends = [t.effective_end for t in tasks if t.effective_end]
        if ends:
            end, derived = max(ends), True
    return start, end, derived


def _group_by_project(
    epics: list[EpicSummary], project_names: dict[str, str]
) -> list[ProjectSummary]:
    grouped: dict[str | None, list[EpicSummary]] = {}
    for item in epics:
        grouped.setdefault(item.epic.project_id, []).append(item)

    projects = [
        ProjectSummary(
            project_id=project_id,
            name=(
                project_names.get(project_id or "")
                or next((e.epic.project_name for e in items if e.epic.project_name), None)
                or NO_PROJECT_NAME
            ),
            epics=sorted(items, key=_epic_sort_key),
            health=worst(e.health for e in items),
        )
        for project_id, items in grouped.items()
    ]
    return sorted(projects, key=_project_sort_key)


def _build_kpi(projects: list[ProjectSummary]) -> SummaryKpi:
    epics = [e for p in projects for e in p.epics]
    tasks_total = sum(e.total for e in epics)
    without_date = sum(e.tasks_without_date for e in epics)
    coverage = round((tasks_total - without_date) / tasks_total * 100) if tasks_total else 0

    return SummaryKpi(
        projects=len(projects),
        epics=len(epics),
        tasks=tasks_total,
        epics_late=sum(1 for e in epics if e.health is Health.LATE),
        epics_risk=sum(1 for e in epics if e.health is Health.RISK),
        epics_no_date=sum(1 for e in epics if e.end_date is None),
        epics_idle=sum(1 for e in epics if e.is_idle),
        tasks_without_date=without_date,
        tasks_without_assignee=sum(e.tasks_without_assignee for e in epics),
        date_coverage_pct=coverage,
    )


# --- Сортировки: проблемное всегда сверху (manage by exception) -----------------

_FAR_FUTURE = datetime.max


def _task_sort_key(task: Task, health: Health) -> tuple:
    return (
        -HEALTH_SEVERITY[health],
        task.effective_end or _FAR_FUTURE,
        -(task.priority or 0),
        task.title,
    )


def _epic_sort_key(item: EpicSummary) -> tuple:
    return (-HEALTH_SEVERITY[item.health], item.end_date or _FAR_FUTURE, item.epic.title)


def _project_sort_key(item: ProjectSummary) -> tuple:
    return (-HEALTH_SEVERITY[item.health], -item.late_epics, item.name)


# --- Данные для таймлайна ------------------------------------------------------


def timeline_bounds(summary: Summary) -> tuple[date, date]:
    """Границы дорожной карты, расширенные до краёв месяца.

    Если дат нет вообще (типичная ситуация, пока планы не заполнены) — показываем
    ближайший квартал, чтобы шкала не выглядела сломанной.
    """
    starts = [e.start_date.date() for e in summary.all_epics if e.start_date]
    ends = [e.end_date.date() for e in summary.all_epics if e.end_date]
    today = summary.generated_at.date()

    if not starts and not ends:
        return _month_start(today), _month_end(today + timedelta(days=90))

    first = min(starts + ends)
    last = max(ends + starts)
    # «Сегодня» должно попадать на шкалу, иначе маркер уедет за край.
    return _month_start(min(first, today)), _month_end(max(last, today))


def month_ticks(start: date, end: date) -> list[tuple[str, float]]:
    """Подписи месяцев и их позиция на шкале в процентах."""
    span = (end - start).days or 1
    ticks: list[tuple[str, float]] = []
    cursor = _month_start(start)
    while cursor <= end:
        offset = (cursor - start).days / span * 100
        if 0 <= offset <= 100:
            ticks.append((f"{_MONTHS_SHORT[cursor.month - 1]} {cursor.year % 100:02d}", offset))
        cursor = _next_month(cursor)
    return ticks


def position_percent(moment: date, start: date, end: date) -> float:
    """Позиция даты на шкале в процентах, обрезанная до 0..100."""
    span = (end - start).days or 1
    return max(0.0, min(100.0, (moment - start).days / span * 100))


_MONTHS_SHORT = (
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _month_end(value: date) -> date:
    return _next_month(value) - timedelta(days=1)
