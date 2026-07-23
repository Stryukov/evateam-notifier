from datetime import datetime

from evateam_bot.core import formatting
from evateam_bot.core.digest import build_digest
from evateam_bot.core.models import Person, StatusCategory, Task

NOW = datetime(2026, 7, 23, 12, 0)
PERSON = Person(id="p1", name="Пётр")


def _task(id_, cat, deadline=None, url=None, code=None, title="Задача", priority=None,
          project_name=None):
    return Task(
        id=id_,
        code=code or id_,
        title=title,
        status_name=cat.value,
        status_category=cat,
        deadline=deadline,
        priority=priority,
        project_name=project_name,
        url=url,
    )


def test_project_name_shown_in_brackets():
    t = _task("t", StatusCategory.IN_PROGRESS, code="BLT-29",
              title="Работа с должниками ВВК", project_name="Биллинг (задачи)")
    msg = formatting.digest_message(PERSON, build_digest([t]), NOW)
    assert "[Биллинг (задачи)] Работа с должниками ВВК" in msg.text


def test_task_code_rendered_as_link():
    t = _task("t1", StatusCategory.IN_PROGRESS, code="HLP-1",
              url="https://evateam.example.ru/task/HLP-1")
    msg = formatting.digest_message(PERSON, build_digest([t]), NOW)
    assert '<a href="https://evateam.example.ru/task/HLP-1">HLP-1</a>' in msg.text


def test_overdue_uses_red_emoji_and_future_uses_hourglass():
    overdue = _task("o", StatusCategory.IN_PROGRESS, deadline=datetime(2026, 5, 22, 8, 0))
    future = _task("f", StatusCategory.IN_PROGRESS, deadline=datetime(2026, 7, 24, 8, 0))
    msg = formatting.digest_message(PERSON, build_digest([overdue, future]), NOW)
    assert formatting.EMOJI_OVERDUE in msg.text  # 🔴 для просроченной
    assert formatting.EMOJI_DEADLINE in msg.text  # ⏳ для будущей


def test_not_started_shown_as_count_only():
    tasks = [
        _task("a", StatusCategory.IN_PROGRESS),
        _task("todo1", StatusCategory.OPEN, title="Секретная задача TODO"),
        _task("todo2", StatusCategory.OPEN),
        _task("c", StatusCategory.WAITING),
    ]
    msg = formatting.digest_message(PERSON, build_digest(tasks), NOW)
    assert "В работе" in msg.text
    assert "Ждут подтверждения" in msg.text
    # «Не начаты» — только счётчиком, без перечисления задач
    assert "Не начатых задач: 2" in msg.text
    assert "Секретная задача TODO" not in msg.text


def test_priority_icon_shown():
    t = _task("p", StatusCategory.IN_PROGRESS, priority=2)  # Критичный -> 🔥
    msg = formatting.digest_message(PERSON, build_digest([t]), NOW)
    assert formatting.PRIORITY_ICONS[2] in msg.text


def test_html_escaping_of_title():
    t = _task("x", StatusCategory.IN_PROGRESS, title="A < B & C")
    msg = formatting.digest_message(PERSON, build_digest([t]), NOW)
    assert "A &lt; B &amp; C" in msg.text


def test_empty_digest_message():
    msg = formatting.digest_message(PERSON, build_digest([]), NOW)
    assert "нет" in msg.text.lower()
