"""Сборка «плана дня» из списка задач. Чистая логика."""

from __future__ import annotations

from datetime import datetime

from .models import Digest, StatusCategory, Task


def _sort_key(task: Task) -> tuple:
    """Сортировка: выше приоритет и ближе дедлайн — раньше.

    В EvaTeam `priority` — целое (0=Обычный), большее значение = выше приоритет.
    """
    priority = task.priority if task.priority is not None else 0
    has_deadline = 0 if task.deadline is not None else 1
    deadline = task.deadline or datetime.max
    return (-priority, has_deadline, deadline)


def build_digest(tasks: list[Task]) -> Digest:
    """Разложить активные задачи по трём группам: в работе / не начаты / ждут подтверждения."""
    in_progress: list[Task] = []
    not_started: list[Task] = []
    waiting: list[Task] = []

    for task in tasks:
        if not task.is_active:
            continue
        if task.status_category is StatusCategory.IN_PROGRESS:
            in_progress.append(task)
        elif task.status_category is StatusCategory.OPEN:
            not_started.append(task)  # ещё не начаты (TODO)
        elif task.status_category is StatusCategory.WAITING:
            waiting.append(task)  # IN_REVIEW — ждут подтверждения
        # DONE / UNKNOWN не попадают в «план дня».

    for group in (in_progress, not_started, waiting):
        group.sort(key=_sort_key)
    return Digest(in_progress=in_progress, not_started=not_started, waiting=waiting)
