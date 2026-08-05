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
    assert task.effective_end == datetime(2026, 8, 31)
    assert task.epic_id == "CmfTask:e1"
    assert task.project_id == "CmfProject:p1"
    assert task.assignee == "Иванов"


def test_parse_task_effective_end_falls_back_to_deadline():
    task = dto.parse_task({"id": "1", "name": "x", "deadline": "2026-08-10"})
    assert task.plan_end is None
    assert task.effective_end == datetime(2026, 8, 10)


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
