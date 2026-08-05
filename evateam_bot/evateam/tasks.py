"""Запросы к EvaTeam: поиск людей и задач сотрудника.

Протокол подтверждён на живом инстансе (см. CLAUDE.md и evateam/client.py):
метод `<Model>.list` с `kwargs={"filter":[...],"fields":[...],"order_by":[...]}`.
"""

from __future__ import annotations

from typing import Any

from ..core.models import Person, Task
from .client import EvaTeamClient
from .dto import _rel_field, parse_person, parse_task

METHOD_PERSON_LIST = "CmfPerson.list"
METHOD_TASK_LIST = "CmfTask.list"
METHOD_KANBAN_LIST = "CmfKanbanBoard.list"
METHOD_PROJECT_LIST = "CmfProject.list"
METHOD_STATUS_LIST = "CmfStatus.list"

# Поля задачи, которые запрашиваем (nested-поля тоже поддерживаются, напр. "responsible.name").
TASK_FIELDS = [
    "id",
    "code",
    "name",
    "cache_status_type",
    "deadline",
    "priority",
    "activity",
    "main_list.code",
    "project.name",
]

PERSON_FIELDS = ["id", "name", "login", "email", "code"]

# Статусы, которые считаем «закрытыми» и не показываем в напоминаниях.
CLOSED_STATUS_TYPE = "CLOSED"

# --- Портфель: эпики, проекты, статусы (сводка по проектам) ---------------------
#
# Эпик в EvaTeam — это НЕ отдельная модель, а CmfTask с этим logic_prefix
# (подтверждено на живом инстансе: модели CmfEpic не существует).
EPIC_LOGIC_PREFIX = "task.epic"

# Типы статусов, которые считаем «идёт работа» для дочерних задач эпика:
# IN_PROGRESS — в работе, IN_REVIEW — ждут подтверждения закрытия.
ACTIVE_STATUS_TYPES = ("IN_PROGRESS", "IN_REVIEW")

# Плановые даты («мягкий» срок) живут НЕ на CmfTask, а в связанном CmfGanttTask:
# CmfTask.op_gantt_task -> sched_start_date / sched_finish_date. Именно их показывает
# интерфейс как «Плановая дата начала/окончания».
# ВНИМАНИЕ: у CmfTask есть собственные plan_start_date/plan_end_date — это ДРУГАЯ пара
# полей, интерфейс её не заполняет (всегда null). Оставлены только как запасной источник.
# `deadline` на CmfTask — «Крайний срок», жёсткий дедлайн.
GANTT_START_FIELD = "op_gantt_task.sched_start_date"
GANTT_END_FIELD = "op_gantt_task.sched_finish_date"

# Важно: различать статусы надо по `status.code`, а не по `cache_status_type` —
# у кода `pause` («Пауза», «Приостановлен») тип как раз OPEN, и по типу его не отделить.
EPIC_FIELDS = [
    "id",
    "code",
    "name",
    "logic_prefix",
    "activity",
    "cache_status_type",
    "status.code",
    "status.name",
    GANTT_START_FIELD,
    GANTT_END_FIELD,
    "plan_start_date",
    "plan_end_date",
    "deadline",
    "priority",
    "responsible.name",
    "parent_id",
    "parent.name",
    "project_id",
    "project.name",
    "main_list.code",
]

# Дочерние задачи эпика: базовый набор + исполнитель, плановые даты, код статуса.
# `project_id` указываем явно — на него опирается kanban_by_project().
EPIC_TASK_FIELDS = TASK_FIELDS + [
    "project_id",
    "status.code",
    "status.name",
    GANTT_START_FIELD,
    GANTT_END_FIELD,
    "plan_start_date",
    "plan_end_date",
    "responsible.name",
    "executors.name",
    "epic_id",
    "parent_id",
    "parent.name",
    "logic_prefix",
]

PROJECT_FIELDS = [
    "id",
    "code",
    "name",
    "cache_status_type",
    "status.code",
    "status.name",
    "responsible.name",
    "cmf_archived",
]

STATUS_FIELDS = ["id", "code", "name", "status_type"]


def _extract_items(result: Any) -> list[dict[str, Any]]:
    """`.list` возвращает список объектов; `.get` — один объект."""
    if result is None:
        return []
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        return [result]
    return []


async def kanban_by_project(
    client: EvaTeamClient, items: list[dict[str, Any]]
) -> dict[str, str]:
    """Код Kanban-доски по проекту — для объектов, которые не лежат на списке (main_list)."""
    project_ids = {
        item.get("project_id")
        for item in items
        if not _rel_field(item.get("main_list"), "code") and item.get("project_id")
    }
    boards: dict[str, str] = {}
    for project_id in project_ids:
        result = await client.call(
            METHOD_KANBAN_LIST,
            kwargs={"filter": [["parent_id", "==", project_id]], "fields": ["code"]},
        )
        found = _extract_items(result)
        if found and found[0].get("code"):
            boards[project_id] = found[0]["code"]
    return boards


def task_url(base_url: str, raw: dict[str, Any], kanban: dict[str, str]) -> str | None:
    """Ссылка на задачу или эпик: доска-список (List) или Kanban-доска проекта.

    Эпик — это тоже CmfTask, поэтому ссылка для него строится ровно так же.
    """
    code = raw.get("code")
    if not (base_url and code):
        return None
    list_code = _rel_field(raw.get("main_list"), "code")
    if list_code:
        return f"{base_url}/project/List/{list_code}?obj=Task:{code}"
    board_code = kanban.get(raw.get("project_id"))
    if board_code:
        return f"{base_url}/project/Kanban/{board_code}?obj=Task:{code}"
    return None


class EvaTeamTasks:
    """Высокоуровневые операции над задачами/людьми поверх JSON-RPC клиента."""

    def __init__(self, client: EvaTeamClient, base_url: str | None = None) -> None:
        self._client = client
        self._base_url = (base_url or "").rstrip("/")

    async def find_person(self, query: str) -> list[Person]:
        """Найти пользователя(-ей) по email или логину (у реальных сотрудников login=email).

        Точное совпадение по login → по email → мягкий поиск по имени (LIKE).
        """
        query = query.strip()
        if not query:
            return []

        for field in ("login", "email"):
            people = await self._list_people([[field, "==", query]])
            if people:
                return people

        # Фолбэк: поиск по имени (например, "Иванов").
        return await self._list_people([["name", "LIKE", f"%{query}%"]])

    async def _list_people(self, filt: list[list]) -> list[Person]:
        result = await self._client.call(
            METHOD_PERSON_LIST, kwargs={"filter": filt, "fields": PERSON_FIELDS}
        )
        return [parse_person(item) for item in _extract_items(result)]

    async def get_tasks_for_person(self, person_id: str) -> list[Task]:
        """Активные (не закрытые) задачи, где сотрудник — исполнитель или ответственный.

        Фильтры EvaTeam соединяются по И, поэтому «исполнитель ИЛИ ответственный»
        выполняется двумя запросами с объединением по id.
        """
        not_closed = ["cache_status_type", "!=", CLOSED_STATUS_TYPE]
        relations = [
            ["executors.id", "==", person_id],
            ["responsible.id", "==", person_id],
        ]

        by_id: dict[str, dict[str, Any]] = {}
        for relation in relations:
            result = await self._client.call(
                METHOD_TASK_LIST,
                kwargs={
                    "filter": [relation, not_closed],
                    "fields": TASK_FIELDS,
                    "order_by": ["deadline"],
                },
            )
            for item in _extract_items(result):
                task_id = item.get("id")
                if task_id:
                    by_id[task_id] = item

        items = list(by_id.values())
        kanban = await self._kanban_by_project(items)
        return [parse_task(item, url=self._task_url(item, kanban)) for item in items]

    async def _kanban_by_project(self, items: list[dict[str, Any]]) -> dict[str, str]:
        return await kanban_by_project(self._client, items)

    def _task_url(self, raw: dict[str, Any], kanban: dict[str, str]) -> str | None:
        return task_url(self._base_url, raw, kanban)
