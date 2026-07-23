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
