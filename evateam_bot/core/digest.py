"""Сборка «плана дня» из списка задач. Чистая логика."""

from __future__ import annotations

from datetime import datetime

from .models import Digest, StatusCategory, Task


def _sort_key(task: Task) -> tuple:
    """Приоритетные и с ближайшим дедлайном — выше.

    Меньший `priority` в EvaTeam обычно = выше приоритет; None уходит в конец.
    """
    priority = task.priority if task.priority is not None else 10_000
    has_deadline = 0 if task.deadline is not None else 1
    deadline = task.deadline or datetime.max
    return (priority, has_deadline, deadline)


def build_digest(tasks: list[Task]) -> Digest:
    """Разложить активные задачи по категориям «в работе» и «ожидают»."""
    in_progress: list[Task] = []
    waiting: list[Task] = []

    for task in tasks:
        if not task.is_active:
            continue
        if task.status_category is StatusCategory.DONE:
            continue
        if task.status_category is StatusCategory.WAITING:
            waiting.append(task)
        elif task.status_category is StatusCategory.IN_PROGRESS:
            in_progress.append(task)
        # OPEN / UNKNOWN пока не попадают в «план дня» (только в работе и ожидают).

    in_progress.sort(key=_sort_key)
    waiting.sort(key=_sort_key)
    return Digest(in_progress=in_progress, waiting=waiting)
