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
    HealthReason,
    Portfolio,
    ProjectSummary,
    StatusCategory,
    Summary,
    SummaryKpi,
    Task,
    epic_sort_key,
)

#: Коды статусов (CmfStatus.code), которые считаем «идёт работа».
#: Отбирать по ним, а не по cache_status_type: у `pause` тип OPEN, и по типу
#: приостановленное неотличимо от «TO DO».
DEFAULT_EPIC_STATUS_CODES: tuple[str, ...] = ("in_progress", "in_review", "pause")
DEFAULT_TASK_STATUS_CODES: tuple[str, ...] = ("in_progress", "in_review", "pause")

NO_PROJECT_NAME = "(без проекта)"


@dataclass(frozen=True)
class SummaryOptions:
    status_codes: tuple[str, ...] = DEFAULT_EPIC_STATUS_CODES
    # Отдельный список для задач: расширяя фильтр эпиков (например, добавив `open`,
    # чтобы увидеть всю картину), не хочется затягивать в отчёт весь бэклог задач.
    task_status_codes: tuple[str, ...] = DEFAULT_TASK_STATUS_CODES
    risk_days: int = 7
    include_orphan_tasks: bool = False


def combined_health(
    soft_end: datetime | None,
    hard_end: datetime | None,
    now: datetime,
    risk_days: int,
) -> tuple[Health, HealthReason]:
    """Светофор по двум срокам. Сравниваем по датам, а не по времени.

    Жёсткий строже мягкого: красный — только сорванный Крайний срок. Отставание от
    плановой даты окончания — жёлтое: план сдвинулся, но обязательство ещё не нарушено.
    """
    today = now.date()
    if hard_end is not None and hard_end.date() < today:
        return Health.LATE, HealthReason.LATE_HARD
    if soft_end is not None and soft_end.date() < today:
        return Health.RISK, HealthReason.BEHIND_PLAN
    if any(
        end is not None and 0 <= (end.date() - today).days <= risk_days
        for end in (soft_end, hard_end)
    ):
        return Health.RISK, HealthReason.DUE_SOON
    if soft_end is not None or hard_end is not None:
        return Health.OK, HealthReason.ON_TRACK
    return Health.NO_DATE, HealthReason.NO_DATE


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
        _build_epic_summary(
            epic,
            _select_tasks(portfolio.tasks_by_epic.get(epic.id, []), options),
            now,
            options,
        )
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
        orphan_tasks=(
            _select_tasks(portfolio.orphan_tasks, options)
            if options.include_orphan_tasks
            else []
        ),
    )


def _select_tasks(tasks: list[Task], options: SummaryOptions) -> list[Task]:
    """Задачи с подходящим кодом статуса. Пустой список кодов — берём все."""
    if not options.task_status_codes:
        return list(tasks)
    return [
        task
        for task in tasks
        if task.status_code and task.status_code.lower() in options.task_status_codes
    ]


def _build_epic_summary(
    epic: Epic, tasks: list[Task], now: datetime, options: SummaryOptions
) -> EpicSummary:
    task_state = {
        task.id: combined_health(task.soft_end, task.hard_end, now, options.risk_days)
        for task in tasks
    }
    ordered = sorted(tasks, key=lambda t: _task_sort_key(t, task_state[t.id][0]))

    start, end, derived = _epic_plan_dates(epic, tasks)
    hard_end = _epic_hard_end(epic, tasks)
    own_health, own_reason = combined_health(end, hard_end, now, options.risk_days)
    health = worst([own_health, *(state[0] for state in task_state.values())])
    reason = _pick_reason(health, own_reason, [state[1] for state in task_state.values()])

    return EpicSummary(
        epic=epic,
        tasks=ordered,
        health=health,
        reason=reason,
        start_date=start,
        end_date=end,
        hard_end=hard_end,
        days_left=(end.date() - now.date()).days if end else None,
        days_left_hard=(hard_end.date() - now.date()).days if hard_end else None,
        in_progress=sum(1 for t in tasks if t.status_category is StatusCategory.IN_PROGRESS),
        in_review=sum(1 for t in tasks if t.status_category is StatusCategory.WAITING),
        tasks_without_date=sum(1 for t in tasks if t.soft_end is None),
        tasks_without_assignee=sum(1 for t in tasks if not t.assignee),
        blockers=[t for t in ordered if task_state[t.id][1] is HealthReason.LATE_HARD],
        behind_plan=[t for t in ordered if task_state[t.id][1] is HealthReason.BEHIND_PLAN],
        is_idle=not tasks,
        dates_are_derived=derived,
        open_ended=start is not None and end is None,
    )


def _pick_reason(
    health: Health, own: HealthReason, task_reasons: list[HealthReason]
) -> HealthReason:
    """Причина цвета эпика: если покраснел из-за задачи, назвать именно её причину."""
    if health is Health.LATE:
        return HealthReason.LATE_HARD
    if health is Health.RISK:
        if own in (HealthReason.BEHIND_PLAN, HealthReason.DUE_SOON):
            return own
        if HealthReason.BEHIND_PLAN in task_reasons:
            return HealthReason.BEHIND_PLAN
        return HealthReason.DUE_SOON
    return own


def _epic_plan_dates(
    epic: Epic, tasks: list[Task]
) -> tuple[datetime | None, datetime | None, bool]:
    """Плановые (мягкие) даты эпика; при их отсутствии выводим из задач."""
    start, end = epic.plan_start, epic.soft_end
    derived = False

    if start is None:
        starts = [t.plan_start for t in tasks if t.plan_start]
        if starts:
            start, derived = min(starts), True
    if end is None:
        ends = [t.soft_end for t in tasks if t.soft_end]
        if ends:
            end, derived = max(ends), True

    # Страховка на случай, если в Ганте окажется окончание раньше начала.
    # Не «чиним» молча перестановкой — это исказило бы план. Отбрасываем неверное
    # окончание, чтобы не рисовать полосу отрицательной длины и не отдавать в
    # Google Timeline строку, которую он отвергнет; факт попадёт в блок пробелов.
    if start and end and end < start:
        return start, None, derived
    return start, end, derived


def _epic_hard_end(epic: Epic, tasks: list[Task]) -> datetime | None:
    """Крайний срок эпика; иначе самый ранний крайний срок среди его задач.

    Именно ранний: первый сорванный дедлайн внутри эпика — уже проблема эпика.
    """
    if epic.hard_end:
        return epic.hard_end
    hard = [t.hard_end for t in tasks if t.hard_end]
    return min(hard) if hard else None


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
            epics=sorted(items, key=epic_sort_key),
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
        epics_no_date=sum(1 for e in epics if e.end_date is None and e.hard_end is None),
        epics_idle=sum(1 for e in epics if e.is_idle),
        epics_open_ended=sum(1 for e in epics if e.open_ended),
        tasks_without_date=without_date,
        tasks_without_assignee=sum(e.tasks_without_assignee for e in epics),
        date_coverage_pct=coverage,
        tasks_with_hard_deadline=sum(
            1 for e in epics for t in e.tasks if t.hard_end is not None
        ),
    )


# --- Сортировки: проблемное всегда сверху (manage by exception) -----------------

_FAR_FUTURE = datetime.max


def _task_sort_key(task: Task, health: Health) -> tuple:
    return (
        -HEALTH_SEVERITY[health],
        task.nearest_end or _FAR_FUTURE,
        -(task.priority or 0),
        task.title,
    )


# Ключ сортировки эпиков живёт в models.epic_sort_key — им же сортируется
# Summary.attention. Здесь только переиспользуем.


def _project_sort_key(item: ProjectSummary) -> tuple:
    return (-HEALTH_SEVERITY[item.health], -item.late_epics, item.name)


# --- Данные для таймлайна ------------------------------------------------------


def timeline_epics(summary: Summary) -> list[EpicSummary]:
    """Эпики, которые можно разместить на карте: нужна хотя бы плановая дата начала.

    Порядок — тот же, что в карточках: проекты по светофору, эпики по приоритету
    (`all_epics` уже отдаёт их отсортированными).
    Полоса без планового окончания рисуется открытой — см. `open_ended`.
    """
    return [e for e in summary.all_epics if e.start_date]


def timeline_bounds(summary: Summary) -> tuple[date, date]:
    """Границы дорожной карты по МЯГКИМ датам, расширенные до краёв месяца.

    Если дат нет вообще — показываем ближайший квартал, чтобы шкала не выглядела
    сломанной.
    """
    placed = timeline_epics(summary)
    starts = [e.start_date.date() for e in placed]
    ends = [e.end_date.date() for e in placed if e.end_date]
    today = summary.generated_at.date()

    if not starts:
        return _month_start(today), _month_end(today + timedelta(days=90))

    first = min(starts)
    # Открытые полосы тянутся до правого края, поэтому шкала обязана дойти минимум
    # до сегодня — иначе такую полосу негде нарисовать.
    last = max(ends + [today])
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
