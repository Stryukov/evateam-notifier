"""Парсинг сырых ответов EvaTeam в доменные модели (`core.models`).

Терпимо относится к разным формам полей — EvaTeam может отдавать связанные объекты
как строку-id, как {"id","name"} или как список таких объектов.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.models import Epic, Person, StatusCategory, Task

# Маппинг типа статуса EvaTeam (поле `cache_status_type`) -> обобщённая категория.
# Значения EvaTeam: OPEN, IN_PROGRESS, IN_REVIEW, CLOSED.
_STATUS_CATEGORY_BY_TYPE: dict[str, StatusCategory] = {
    "IN_PROGRESS": StatusCategory.IN_PROGRESS,
    "IN_REVIEW": StatusCategory.WAITING,  # на проверке/ожидании
    "OPEN": StatusCategory.OPEN,
    "CLOSED": StatusCategory.DONE,
}


def status_category_from_type(status_type: str | None) -> StatusCategory:
    if not status_type:
        return StatusCategory.UNKNOWN
    return _STATUS_CATEGORY_BY_TYPE.get(status_type.strip().upper(), StatusCategory.UNKNOWN)


def _rel_field(value: Any, key: str = "name") -> str | None:
    """Достать читаемое значение из связанного поля (id-строка / объект / список)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get(key) or value.get("id")
    if isinstance(value, list) and value:
        return _rel_field(value[0], key)
    return str(value)


def _rel_key(value: Any, key: str) -> str | None:
    """Строго достать поле `key` из связанного объекта — БЕЗ фолбэка на id.

    В отличие от `_rel_field`, ничего не подставляет: если поля нет, вернёт None.
    Это принципиально для `status.code` — иначе при отсутствии `code` вернулся бы
    id вида "CmfStatus:...", фильтр по кодам статусов молча не совпал бы ни с чем,
    и сводка всегда была бы пустой.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        found = value.get(key)
        return found if isinstance(found, str) else None
    if isinstance(value, list) and value:
        return _rel_key(value[0], key)
    return None


def _rel_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id")
    if isinstance(value, list) and value:
        return _rel_id(value[0])
    return None


def _to_naive_local(dt: datetime) -> datetime:
    """Привести tz-aware дату к наивной в локальной зоне (для однородных сравнений)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _to_naive_local(value)
    text = str(value).strip()
    # EvaTeam обычно ISO 8601; "Z" -> смещение.
    text = text.replace("Z", "+00:00")
    try:
        return _to_naive_local(datetime.fromisoformat(text))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def parse_person(raw: dict[str, Any]) -> Person:
    return Person(
        id=str(raw.get("id") or raw.get("person_id") or ""),
        name=(raw.get("name") or raw.get("full_name") or raw.get("login") or "").strip(),
        login=raw.get("login"),
        email=raw.get("email") or raw.get("email1"),
    )


def parse_task(raw: dict[str, Any], *, url: str | None = None) -> Task:
    status_type = raw.get("cache_status_type")
    status_name = _rel_field(raw.get("status")) or (status_type or "")
    task_id = str(raw.get("id") or "")
    code = raw.get("code")

    activity = raw.get("activity")
    is_active = True
    if isinstance(activity, str):
        is_active = activity.strip().lower() not in {"archive", "archived", "inactive"}
    elif isinstance(activity, bool):
        is_active = activity

    priority_raw = raw.get("priority")
    priority = None
    if isinstance(priority_raw, (int, float)):
        priority = int(priority_raw)
    elif isinstance(priority_raw, dict):
        maybe = priority_raw.get("orderno") or priority_raw.get("weight")
        priority = int(maybe) if isinstance(maybe, (int, float)) else None

    return Task(
        id=task_id,
        code=code,
        title=(raw.get("name") or raw.get("title") or "").strip() or "(без названия)",
        status_name=status_name,
        status_category=status_category_from_type(status_type),
        deadline=parse_datetime(raw.get("deadline")),
        priority=priority,
        priority_name=_rel_field(priority_raw),
        project_name=_rel_field(raw.get("project")),
        url=url,
        is_active=is_active,
        status_code=_rel_key(raw.get("status"), "code"),
        plan_start=parse_datetime(raw.get("plan_start_date")),
        plan_end=parse_datetime(raw.get("plan_end_date")),
        assignee=_assignee(raw),
        epic_id=_rel_id(raw.get("epic")) or raw.get("epic_id"),
        project_id=_rel_id(raw.get("parent")) or raw.get("parent_id") or raw.get("project_id"),
    )


def _assignee(raw: dict[str, Any]) -> str | None:
    """Исполнитель: сначала `responsible`, затем первый из `executors`.

    На живом инстансе `executors` не заполняют — исполнитель живёт в `responsible`,
    но фолбэк оставляем, чтобы не потерять данные там, где практика другая.

    Строгий `_rel_key`: лучше «— без исполнителя», чем «CmfPerson:2b3...» в отчёте.
    """
    return _rel_key(raw.get("responsible"), "name") or _rel_key(raw.get("executors"), "name")


def parse_epic(raw: dict[str, Any], *, url: str | None = None) -> Epic:
    """Эпик — это CmfTask с logic_prefix=task.epic (отдельной модели в EvaTeam нет)."""
    status_type = raw.get("cache_status_type")
    activity = raw.get("activity")
    is_active = True
    if isinstance(activity, str):
        is_active = activity.strip().lower() not in {"archive", "archived", "inactive"}
    elif isinstance(activity, bool):
        is_active = activity

    return Epic(
        id=str(raw.get("id") or ""),
        code=raw.get("code"),
        title=(raw.get("name") or "").strip() or "(без названия)",
        status_code=_rel_key(raw.get("status"), "code"),
        status_name=_rel_key(raw.get("status"), "name") or (status_type or ""),
        status_category=status_category_from_type(status_type),
        # У эпика родитель — CmfProject; `project` оставляем как запасной источник.
        project_id=_rel_id(raw.get("parent")) or raw.get("parent_id") or raw.get("project_id"),
        project_name=_rel_key(raw.get("parent"), "name") or _rel_key(raw.get("project"), "name"),
        responsible=_rel_key(raw.get("responsible"), "name"),
        plan_start=parse_datetime(raw.get("plan_start_date")),
        plan_end=parse_datetime(raw.get("plan_end_date")),
        deadline=parse_datetime(raw.get("deadline")),
        url=url,
        is_active=is_active,
    )
