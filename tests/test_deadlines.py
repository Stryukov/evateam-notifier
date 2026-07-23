from datetime import datetime

from evateam_bot.core.deadlines import find_overdue
from evateam_bot.core.models import StatusCategory, Task


def _task(id_, deadline, cat=StatusCategory.IN_PROGRESS, active=True):
    return Task(
        id=id_,
        code=id_,
        title=f"T{id_}",
        status_name=cat.value,
        status_category=cat,
        deadline=deadline,
        is_active=active,
    )


def test_find_overdue():
    now = datetime(2026, 7, 23, 12, 0)
    tasks = [
        _task("late1", datetime(2026, 7, 20)),
        _task("late2", datetime(2026, 7, 22)),
        _task("future", datetime(2026, 7, 30)),
        _task("nodeadline", None),
        _task("done", datetime(2026, 7, 1), cat=StatusCategory.DONE),
        _task("archived", datetime(2026, 7, 1), active=False),
    ]
    overdue = find_overdue(tasks, now)
    # только просроченные активные незакрытые, отсортированы по дедлайну
    assert [t.id for t in overdue] == ["late1", "late2"]


def test_is_overdue_edge_cases():
    now = datetime(2026, 7, 23, 12, 0)
    assert _task("x", None).is_overdue(now) is False
    assert _task("x", datetime(2026, 7, 23, 13, 0)).is_overdue(now) is False
    assert _task("x", datetime(2026, 7, 23, 11, 0)).is_overdue(now) is True
