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
    url: str | None = None
    is_active: bool = True

    def is_overdue(self, now: datetime) -> bool:
        if self.deadline is None:
            return False
        if self.status_category is StatusCategory.DONE:
            return False
        return self.deadline < now


@dataclass
class Digest:
    """«План дня» сотрудника: задачи в работе и ожидающие."""

    in_progress: list[Task] = field(default_factory=list)
    waiting: list[Task] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.in_progress and not self.waiting

    @property
    def total(self) -> int:
        return len(self.in_progress) + len(self.waiting)
