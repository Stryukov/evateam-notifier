from datetime import datetime

from evateam_bot.core.models import Epic, Portfolio, StatusCategory, Task
from evateam_bot.core.summary import SummaryOptions, build_summary
from evateam_bot.core.summary_text import empty_summary_message, summary_message

NOW = datetime(2026, 8, 5, 12, 0)


def _epic(id_, *, title="Эпик", end=None, hard=None, project="Проект", url=None):
    return Epic(
        id=id_,
        code=id_.upper(),
        title=title,
        status_code="in_progress",
        status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        project_id="p1",
        project_name=project,
        plan_end=end,
        deadline=hard,
        url=url,
    )


def _task(id_, *, end=None, hard=None, assignee="Иванов", title="Задача"):
    return Task(
        id=id_,
        code=id_.upper(),
        title=title,
        status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        plan_end=end,
        deadline=hard,
        assignee=assignee,
        epic_id="e1",
    )


def _summary(epics, tasks_by_epic=None, **kwargs):
    portfolio = Portfolio(
        epics=epics, tasks_by_epic=tasks_by_epic or {}, project_names={"p1": "Проект"}
    )
    return build_summary(portfolio, now=NOW, **kwargs)


def test_verdict_is_first_meaningful_line():
    summary = _summary([_epic("e1", hard=datetime(2026, 1, 1))])
    text = summary_message(summary).text
    lines = [line for line in text.split("\n") if line.strip()]
    assert "Сводка по проектам" in lines[0]
    assert "сорван крайний срок у эпиков: 1" in lines[1]


def test_verdict_green_when_all_on_track():
    summary = _summary([_epic("e1", end=datetime(2027, 1, 1))])
    assert "Всё по плану" in summary_message(summary).text


def test_verdict_flags_total_absence_of_dates():
    summary = _summary([_epic("e1"), _epic("e2")])
    assert "Сроков нет ни у одного эпика" in summary_message(summary).text


def test_late_epics_listed_and_healthy_collapsed_to_count():
    epics = [
        _epic("late", title="Просроченный", end=datetime(2026, 1, 1)),
        _epic("ok1", title="Здоровый один", end=datetime(2027, 1, 1)),
        _epic("ok2", title="Здоровый два", end=datetime(2027, 2, 1)),
    ]
    text = summary_message(_summary(epics)).text
    assert "Просроченный" in text
    assert "🟢 По плану: 2" in text
    # Зелёные эпики не перечисляются поимённо.
    assert "Здоровый один" not in text


def test_epic_note_distinguishes_hard_and_soft_overdue():
    """Руководителю важно, какой именно срок нарушен."""
    hard = _summary([_epic("e1", hard=datetime(2026, 8, 1))])
    assert "просрочен крайний срок на 4 дн." in summary_message(hard).text

    soft = _summary([_epic("e2", end=datetime(2026, 8, 1))])
    assert "отстаёт от плана на 4 дн." in summary_message(soft).text


def test_hard_deadline_section_names_assignee_and_date():
    summary = _summary(
        [_epic("e1")],
        {"e1": [_task("t1", hard=datetime(2026, 7, 30), assignee="Петров", title="Сломано")]},
    )
    text = summary_message(summary).text
    assert "Сорван крайний срок" in text
    assert "Сломано" in text and "Петров" in text and "30.07" in text


def test_behind_plan_section_is_separate_from_blockers():
    summary = _summary(
        [_epic("e1")],
        {"e1": [_task("t1", end=datetime(2026, 7, 30), title="Отстаёт")]},
    )
    text = summary_message(summary).text
    assert "Отстают от плана" in text
    assert "Сорван крайний срок" not in text


def test_gaps_section_reports_planning_holes():
    summary = _summary([_epic("e1")], {"e1": [_task("t1", assignee=None)]})
    text = summary_message(summary).text
    assert "Пробелы в планировании" in text
    assert "задач без плановой даты: 1" in text
    assert "задач без исполнителя: 1" in text


def test_open_ended_epic_is_noted():
    from evateam_bot.core.models import Epic as _E

    epic = _E(
        id="e1", code="SPT-5", title="Договорная работа",
        status_code="in_progress", status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        project_id="p1", project_name="Проект",
        plan_start=datetime(2026, 7, 20),
    )
    # Статус такому эпику не определить, поэтому он идёт в блок пробелов.
    assert "эпиков без планового окончания: 1" in summary_message(_summary([epic])).text


def test_idle_epic_marked():
    assert "нет задач в работе" in summary_message(
        _summary([_epic("e1", end=datetime(2026, 1, 1))])
    ).text


def test_epic_code_rendered_as_link():
    summary = _summary([_epic("e1", end=datetime(2026, 1, 1), url="https://eva.example.ru/x")])
    assert '<a href="https://eva.example.ru/x">E1</a>' in summary_message(summary).text


def test_html_is_escaped():
    summary = _summary([_epic("e1", title="A < B & C", end=datetime(2026, 1, 1))])
    assert "A &lt; B &amp; C" in summary_message(summary).text


def test_long_list_is_truncated_by_max_items():
    epics = [_epic(f"e{i}", title=f"Эпик {i}", end=datetime(2026, 1, 1)) for i in range(9)]
    text = summary_message(_summary(epics), max_items=3).text
    assert "…и ещё 6" in text


def test_message_fits_telegram_limit():
    epics = [
        _epic(f"e{i}", title=f"Очень длинное название эпика номер {i} " * 4,
              end=datetime(2026, 1, 1))
        for i in range(60)
    ]
    tasks = {
        f"e{i}": [_task(f"t{i}", end=datetime(2026, 1, 1), title="Задача " * 10)]
        for i in range(60)
    }
    text = summary_message(_summary(epics, tasks)).text
    assert len(text) <= 4096


def test_empty_summary_explains_how_to_fix():
    portfolio = Portfolio(
        epics=[_epic_with_status("e1", "open"), _epic_with_status("e2", None)],
        project_names={},
    )
    summary = build_summary(
        portfolio, now=NOW, options=SummaryOptions(status_codes=("in_progress", "pause"))
    )
    text = summary_message(summary).text

    assert summary.is_empty
    assert "in_progress" in text and "pause" in text
    assert "Просмотрено эпиков: 2" in text
    assert "Без распознанного статуса: 1" in text
    assert "SUMMARY_EPIC_STATUS_CODES" in text
    assert "open" in text


def test_empty_summary_message_used_directly():
    summary = build_summary(Portfolio(), now=NOW)
    assert "Эпиков с такими статусами не найдено" in empty_summary_message(summary).text


def _epic_with_status(id_, status):
    return Epic(
        id=id_,
        code=id_,
        title="Эпик",
        status_code=status,
        status_name=status or "",
        status_category=StatusCategory.OPEN,
        project_id="p1",
        project_name="Проект",
    )
