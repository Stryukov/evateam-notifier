from datetime import datetime

from evateam_bot.core.models import StatusCategory
from evateam_bot.evateam import dto


def test_status_category_mapping():
    assert dto.status_category_from_type("IN_PROGRESS") is StatusCategory.IN_PROGRESS
    assert dto.status_category_from_type("in_review") is StatusCategory.WAITING
    assert dto.status_category_from_type("OPEN") is StatusCategory.OPEN
    assert dto.status_category_from_type("CLOSED") is StatusCategory.DONE
    assert dto.status_category_from_type("weird") is StatusCategory.UNKNOWN
    assert dto.status_category_from_type(None) is StatusCategory.UNKNOWN


def test_rel_key_does_not_fall_back_to_id():
    """Ключевая защита: id не должен подменять собой отсутствующий код статуса.

    `_rel_field` в таком случае вернул бы "CmfStatus:s1", фильтр по кодам статусов
    молча не совпал бы ни с чем, и сводка была бы всегда пустой.
    """
    status = {"id": "CmfStatus:s1", "name": "TO DO"}
    assert dto._rel_field(status, "code") == "CmfStatus:s1"  # старое, «мягкое» поведение
    assert dto._rel_key(status, "code") is None  # новое, строгое
    assert dto._rel_key({"code": "pause"}, "code") == "pause"
    assert dto._rel_key([{"code": "in_review"}], "code") == "in_review"
    assert dto._rel_key("CmfStatus:s1", "code") is None  # голая id-строка — не код
    assert dto._rel_key(None, "code") is None


def test_parse_task_reads_summary_fields():
    task = dto.parse_task(
        {
            "id": "CmfTask:1",
            "code": "BLT-1",
            "name": "Задача",
            "cache_status_type": "IN_PROGRESS",
            "status": {"code": "in_progress", "name": "В работе"},
            "plan_start_date": "2026-08-01",
            "plan_end_date": "2026-08-31",
            "epic_id": "CmfTask:e1",
            "parent_id": "CmfProject:p1",
            "responsible": {"id": "CmfPerson:u1", "name": "Иванов"},
        }
    )
    assert task.status_code == "in_progress"
    assert task.plan_start == datetime(2026, 8, 1)
    assert task.soft_end == datetime(2026, 8, 31)
    assert task.epic_id == "CmfTask:e1"
    assert task.project_id == "CmfProject:p1"
    assert task.assignee == "Иванов"


def test_plan_dates_come_from_gantt_object():
    """Интерфейс пишет плановые даты в CmfGanttTask, а не в поля самой задачи.

    Реальный случай BLT-33: plan_*_date на CmfTask пустые, даты — в op_gantt_task.
    """
    task = dto.parse_task(
        {
            "id": "CmfTask:1",
            "code": "BLT-33",
            "name": "Подготовка MVP workflow n8n",
            "plan_start_date": None,
            "plan_end_date": None,
            "deadline": "2026-08-11T08:00:00",
            "op_gantt_task": {
                "id": "CmfGanttTask:g1",
                "sched_start_date": "2026-07-23T18:00:00",
                "sched_finish_date": "2026-08-07T03:00:00",
            },
        }
    )
    assert task.plan_start == datetime(2026, 7, 23, 18, 0)  # мягкий
    assert task.plan_end == datetime(2026, 8, 7, 3, 0)  # мягкий
    assert task.deadline == datetime(2026, 8, 11, 8, 0)  # жёсткий
    assert task.soft_end != task.hard_end  # два разных срока, не склеены


def test_gantt_dates_fall_back_to_task_fields():
    task = dto.parse_task(
        {"id": "1", "name": "x", "plan_start_date": "2026-08-01", "plan_end_date": "2026-08-31"}
    )
    assert task.plan_start == datetime(2026, 8, 1)
    assert task.plan_end == datetime(2026, 8, 31)


def test_gantt_as_bare_id_string_yields_no_dates():
    """Регресс на _rel_key: id гант-объекта не должен притвориться датой."""
    task = dto.parse_task({"id": "1", "name": "x", "op_gantt_task": "CmfGanttTask:g1"})
    assert task.plan_start is None
    assert task.plan_end is None


def test_epic_reads_gantt_plan_dates():
    epic = dto.parse_epic(
        {
            "id": "CmfTask:e1",
            "code": "ZAT-17",
            "name": "Epic ЛК ЮЛ",
            "op_gantt_task": {
                "sched_start_date": "2028-03-20T18:00:00",
                "sched_finish_date": "2028-07-11T10:00:00",
            },
        }
    )
    assert epic.plan_start == datetime(2028, 3, 20, 18, 0)
    assert epic.soft_end == datetime(2028, 7, 11, 10, 0)
    assert epic.hard_end is None


def test_nearest_end_picks_earliest_of_two():
    task = dto.parse_task(
        {"id": "1", "name": "x", "deadline": "2026-08-11",
         "op_gantt_task": {"sched_finish_date": "2026-08-07"}}
    )
    assert task.nearest_end == datetime(2026, 8, 7)


def test_parse_epic_prefers_parent_as_project():
    epic = dto.parse_epic(
        {
            "id": "CmfTask:e1",
            "code": "MW-2",
            "name": "Epic Концепция",
            "cache_status_type": "OPEN",
            "status": {"code": "pause", "name": "PAUSE"},
            "parent": {"id": "CmfProject:p9", "name": "Мониторинг воды"},
            "project": {"id": "CmfProject:zzz", "name": "Не тот проект"},
        }
    )
    assert epic.status_code == "pause"
    assert epic.project_id == "CmfProject:p9"
    assert epic.project_name == "Мониторинг воды"


def test_parse_epic_without_name_does_not_leak_id():
    epic = dto.parse_epic(
        {"id": "CmfTask:e1", "name": "Epic", "parent": {"id": "CmfProject:p9"}}
    )
    assert epic.project_name is None  # лучше «—», чем "CmfProject:p9"


def test_parse_datetime_variants():
    assert dto.parse_datetime("2026-07-23T09:30:00") == datetime(2026, 7, 23, 9, 30)
    assert dto.parse_datetime("2026-07-23 09:30:00") == datetime(2026, 7, 23, 9, 30)
    assert dto.parse_datetime("2026-07-23") == datetime(2026, 7, 23)
    assert dto.parse_datetime("") is None
    assert dto.parse_datetime(None) is None


def test_parse_task_with_nested_objects():
    raw = {
        "id": "CmfTask:1",
        "code": "PRJ-7",
        "name": "Сделать отчёт",
        "cache_status_type": "IN_PROGRESS",
        "status": {"code": "in_progress", "name": "В работе"},
        "activity": "active",
        "deadline": "2026-07-20T18:00:00",
        "priority": {"orderno": 2, "name": "Высокий"},
    }
    url = "https://eva.example.ru/project/List/LBRD-1?obj=Task:PRJ-7"
    task = dto.parse_task(raw, url=url)
    assert task.code == "PRJ-7"
    assert task.title == "Сделать отчёт"
    assert task.status_category is StatusCategory.IN_PROGRESS
    assert task.status_name == "В работе"
    assert task.deadline == datetime(2026, 7, 20, 18, 0)
    assert task.priority == 2
    assert task.is_active is True
    assert task.url == url


def test_parse_task_uses_cache_status_type_when_no_status_object():
    task = dto.parse_task({"id": "CmfTask:9", "cache_status_type": "OPEN"})
    assert task.status_category is StatusCategory.OPEN
    assert task.status_name == "OPEN"


def test_parse_task_archived_and_missing_fields():
    task = dto.parse_task({"id": "CmfTask:2", "activity": "archive"})
    assert task.is_active is False
    assert task.title == "(без названия)"
    assert task.status_category is StatusCategory.UNKNOWN
    assert task.deadline is None
