from datetime import datetime

from evateam_bot.core.digest import build_digest
from evateam_bot.core.models import StatusCategory, Task


def _task(id_, cat, priority=None, deadline=None, active=True):
    return Task(
        id=id_,
        code=id_,
        title=f"T{id_}",
        status_name=cat.value,
        status_category=cat,
        deadline=deadline,
        priority=priority,
        is_active=active,
    )


def test_build_digest_groups_and_filters():
    tasks = [
        _task("1", StatusCategory.IN_PROGRESS),  # -> в работе
        _task("2", StatusCategory.WAITING),  # IN_REVIEW -> ждут подтверждения
        _task("3", StatusCategory.DONE),  # исключается
        _task("4", StatusCategory.OPEN),  # -> не начаты
        _task("5", StatusCategory.IN_PROGRESS, active=False),  # архив
        _task("6", StatusCategory.UNKNOWN),  # не входит в план дня
    ]
    digest = build_digest(tasks)
    assert [t.id for t in digest.in_progress] == ["1"]
    assert [t.id for t in digest.not_started] == ["4"]
    assert [t.id for t in digest.waiting] == ["2"]
    assert digest.total == 3
    assert digest.is_empty is False


def test_digest_sorted_by_priority_then_deadline():
    tasks = [
        _task("a", StatusCategory.IN_PROGRESS, priority=5),
        _task("b", StatusCategory.IN_PROGRESS, priority=1),
        _task("c", StatusCategory.IN_PROGRESS, priority=1, deadline=datetime(2026, 1, 1)),
    ]
    digest = build_digest(tasks)
    # priority=1 выше; среди равных — с дедлайном раньше
    assert [t.id for t in digest.in_progress] == ["c", "b", "a"]


def test_empty_digest():
    assert build_digest([]).is_empty is True
