"""Логика поиска просроченных задач. Чистая логика."""

from __future__ import annotations

from datetime import datetime

from .models import Task


def find_overdue(tasks: list[Task], now: datetime) -> list[Task]:
    """Активные незакрытые задачи с истёкшим `deadline`, по возрастанию дедлайна."""
    overdue = [t for t in tasks if t.is_active and t.is_overdue(now)]
    overdue.sort(key=lambda t: t.deadline or datetime.max)
    return overdue
