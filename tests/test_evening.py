from datetime import datetime

from evateam_bot.core import formatting
from evateam_bot.core.digest import build_digest
from evateam_bot.core.models import Person, StatusCategory, Task

NOW = datetime(2026, 8, 5, 16, 0)
PERSON = Person(id="p1", name="Пётр")


def _task(id_, *, category=StatusCategory.IN_PROGRESS, soft=None, hard=None,
          title="Задача", priority=None):
    return Task(
        id=id_,
        code=id_.upper(),
        title=title,
        status_name="В работе",
        status_category=category,
        status_code="in_progress",
        plan_end=soft,
        deadline=hard,
        priority=priority,
    )


def _message(tasks):
    return formatting.evening_message(PERSON, build_digest(tasks), NOW).text


def test_calls_to_action_are_present():
    text = _message([_task("t1")])
    assert "Итоги дня" in text
    assert "завершили" in text
    assert "сроки" in text


def test_both_groups_are_listed():
    tasks = [
        _task("work", title="В работе сейчас"),
        _task("review", category=StatusCategory.WAITING, title="Ждёт подтверждения"),
    ]
    text = _message(tasks)
    assert "🔧 В работе (1)" in text
    assert "⏳ Ждут подтверждения (1)" in text
    assert "В работе сейчас" in text and "Ждёт подтверждения" in text


def test_not_started_tasks_are_not_shown():
    """Закрывать и двигать нечего у того, что ещё не начато."""
    text = _message([_task("work"), _task("todo", category=StatusCategory.OPEN,
                                          title="Ещё не начата")])
    assert "Ещё не начата" not in text


def test_broken_hard_deadline_is_red():
    text = _message([_task("t1", hard=datetime(2026, 8, 1))])
    assert formatting.EMOJI_OVERDUE in text
    assert "крайний срок 01.08" in text


def test_behind_plan_is_amber_not_red():
    text = _message([_task("t1", soft=datetime(2026, 8, 1))])
    assert formatting.EMOJI_RISK in text
    assert formatting.EMOJI_OVERDUE not in text
    assert "отстаёт от плана" in text


def test_upcoming_deadline_is_amber():
    text = _message([_task("t1", hard=datetime(2026, 8, 6))])
    assert formatting.EMOJI_RISK in text
    assert "срок 06.08" in text


def test_task_without_dates_has_no_mark():
    text = _message([_task("t1", title="Без сроков")])
    assert formatting.EMOJI_OVERDUE not in text
    assert formatting.EMOJI_RISK not in text
    assert "Без сроков" in text


def test_far_deadline_is_not_marked():
    text = _message([_task("t1", hard=datetime(2027, 1, 1))])
    assert formatting.EMOJI_RISK not in text
    assert formatting.EMOJI_OVERDUE not in text


def test_priority_icon_shown():
    text = _message([_task("t1", priority=2)])
    assert formatting.PRIORITY_ICONS[2] in text


def test_html_escaped():
    text = _message([_task("t1", title="A < B & C")])
    assert "A &lt; B &amp; C" in text
