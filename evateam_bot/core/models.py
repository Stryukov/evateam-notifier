"""Доменные модели. Независимы от EvaTeam-транспорта и мессенджеров."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class StatusCategory(str, Enum):
    """Обобщённая категория статуса задачи.

    EvaTeam-статусы (`CmfStatusCode`) маппятся на эти категории в `evateam/dto.py`.
    """

    IN_PROGRESS = "in_progress"  # в работе
    WAITING = "waiting"  # ожидает
    OPEN = "open"  # открыта / к выполнению
    DONE = "done"  # завершена
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Person:
    """Пользователь EvaTeam."""

    id: str
    name: str
    login: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Task:
    """Задача EvaTeam в терминах бота."""

    id: str
    code: str | None
    title: str
    status_name: str
    status_category: StatusCategory
    deadline: datetime | None = None
    priority: int | None = None
    priority_name: str | None = None
    project_name: str | None = None
    url: str | None = None
    is_active: bool = True
    # Поля для сводки по проектам. Дописаны в конец со значениями по умолчанию,
    # чтобы не ломать существующие конструкторы (дайджест, просрочки, тесты).
    status_code: str | None = None  # CmfStatus.code: in_progress / in_review / pause / ...
    plan_start: datetime | None = None
    plan_end: datetime | None = None
    assignee: str | None = None  # responsible.name, фолбэк executors[0].name
    epic_id: str | None = None
    project_id: str | None = None

    def is_overdue(self, now: datetime) -> bool:
        if self.deadline is None:
            return False
        if self.status_category is StatusCategory.DONE:
            return False
        return self.deadline < now

    @property
    def effective_end(self) -> datetime | None:
        """Плановый конец: приоритет у plan_end, иначе дедлайн."""
        return self.plan_end or self.deadline


@dataclass
class Digest:
    """«План дня» сотрудника, разбитый по статусам задач."""

    in_progress: list[Task] = field(default_factory=list)  # IN_PROGRESS — в работе
    not_started: list[Task] = field(default_factory=list)  # OPEN — не начаты (TODO)
    waiting: list[Task] = field(default_factory=list)  # IN_REVIEW — ждут подтверждения

    @property
    def groups(self) -> list[list[Task]]:
        return [self.in_progress, self.not_started, self.waiting]

    @property
    def is_empty(self) -> bool:
        return all(not group for group in self.groups)

    @property
    def total(self) -> int:
        return sum(len(group) for group in self.groups)


# --- Сводка по проектам и эпикам -----------------------------------------------


class Health(str, Enum):
    """Светофор по плановым датам. Считается автоматически, вручную не проставляется."""

    LATE = "late"  # 🔴 просрочено
    RISK = "risk"  # 🟡 под угрозой (срок близко)
    OK = "ok"  # 🟢 по плану
    NO_DATE = "no_date"  # ⚪ срок не задан


#: Вес для роллапа «худший ребёнок». NO_DATE — самый слабый: эпик без даты, но с
#: просроченной задачей должен быть красным, а не белым. При этом «всё без дат»
#: остаётся ⚪ — пробел в планировании виден, но не маскирует реальную просрочку.
HEALTH_SEVERITY: dict[Health, int] = {
    Health.NO_DATE: 0,
    Health.OK: 1,
    Health.RISK: 2,
    Health.LATE: 3,
}


@dataclass(frozen=True)
class Epic:
    """Эпик EvaTeam (CmfTask с logic_prefix=task.epic)."""

    id: str
    code: str | None
    title: str
    status_code: str | None
    status_name: str
    status_category: StatusCategory
    project_id: str | None = None
    project_name: str | None = None
    responsible: str | None = None
    plan_start: datetime | None = None
    plan_end: datetime | None = None
    deadline: datetime | None = None
    url: str | None = None
    is_active: bool = True

    @property
    def effective_end(self) -> datetime | None:
        return self.plan_end or self.deadline


@dataclass(frozen=True)
class Portfolio:
    """Сырой срез EvaTeam до анализа — то, что отдаёт evateam/portfolio.py."""

    epics: list[Epic] = field(default_factory=list)
    tasks_by_epic: dict[str, list[Task]] = field(default_factory=dict)
    orphan_tasks: list[Task] = field(default_factory=list)  # активные задачи без эпика
    project_names: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EpicSummary:
    """Эпик с посчитанными метриками и здоровьем."""

    epic: Epic
    tasks: list[Task]
    health: Health
    start_date: datetime | None = None
    end_date: datetime | None = None
    days_left: int | None = None  # < 0 — просрочка
    in_progress: int = 0
    in_review: int = 0
    tasks_without_date: int = 0
    tasks_without_assignee: int = 0
    blockers: list[Task] = field(default_factory=list)  # просроченные задачи эпика
    is_idle: bool = False  # нет ни одной активной задачи
    dates_are_derived: bool = False  # даты взяты из задач, своих у эпика нет

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def date_coverage(self) -> float:
        """Доля задач с плановой датой, 0.0..1.0."""
        if not self.tasks:
            return 0.0
        return (self.total - self.tasks_without_date) / self.total


@dataclass(frozen=True)
class ProjectSummary:
    """Проект с эпиками, отсортированными по убыванию проблемности."""

    project_id: str | None
    name: str
    epics: list[EpicSummary] = field(default_factory=list)
    health: Health = Health.NO_DATE

    @property
    def total_tasks(self) -> int:
        return sum(e.total for e in self.epics)

    @property
    def late_epics(self) -> int:
        return sum(1 for e in self.epics if e.health is Health.LATE)

    @property
    def risk_epics(self) -> int:
        return sum(1 for e in self.epics if e.health is Health.RISK)


@dataclass(frozen=True)
class SummaryKpi:
    """Верхняя строка отчёта: 5-7 чисел, не больше."""

    projects: int = 0
    epics: int = 0
    tasks: int = 0
    epics_late: int = 0
    epics_risk: int = 0
    epics_no_date: int = 0
    epics_idle: int = 0
    tasks_without_date: int = 0
    tasks_without_assignee: int = 0
    date_coverage_pct: int = 0


@dataclass(frozen=True)
class Summary:
    """Готовый управленческий срез. Рендерится в Telegram, HTML и CSV."""

    generated_at: datetime
    projects: list[ProjectSummary] = field(default_factory=list)
    kpi: SummaryKpi = field(default_factory=SummaryKpi)
    status_codes: tuple[str, ...] = ()  # какой фильтр применялся
    risk_days: int = 7
    epics_total_scanned: int = 0  # сколько эпиков вернул EvaTeam ДО фильтра
    epics_unknown_status: int = 0  # у скольких не удалось определить status.code
    orphan_tasks: list[Task] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.projects

    @property
    def all_epics(self) -> list[EpicSummary]:
        return [epic for project in self.projects for epic in project.epics]

    @property
    def attention(self) -> list[EpicSummary]:
        """Эпики, требующие внимания руководителя (manage by exception)."""
        return [e for e in self.all_epics if e.health in (Health.LATE, Health.RISK)]

    @property
    def blockers(self) -> list[tuple[EpicSummary, Task]]:
        return [(e, task) for e in self.all_epics for task in e.blockers]
