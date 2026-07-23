"""Запросы к EvaTeam: поиск людей и задач сотрудника.

Протокол подтверждён на живом инстансе (см. CLAUDE.md и evateam/client.py):
метод `<Model>.list` с `kwargs={"filter":[...],"fields":[...],"order_by":[...]}`.
"""

from __future__ import annotations

from typing import Any

from ..core.models import Person, Task
from .client import EvaTeamClient
from .dto import parse_person, parse_task

METHOD_PERSON_LIST = "CmfPerson.list"
METHOD_TASK_LIST = "CmfTask.list"

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
]

PERSON_FIELDS = ["id", "name", "login", "email", "code"]

# Статусы, которые считаем «закрытыми» и не показываем в напоминаниях.
CLOSED_STATUS_TYPE = "CLOSED"


def _extract_items(result: Any) -> list[dict[str, Any]]:
    """`.list` возвращает список объектов; `.get` — один объект."""
    if result is None:
        return []
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        return [result]
    return []


class EvaTeamTasks:
    """Высокоуровневые операции над задачами/людьми поверх JSON-RPC клиента."""

    def __init__(
        self,
        client: EvaTeamClient,
        base_url: str | None = None,
        url_template: str = "{base}/task/{code}",
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._url_template = url_template

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

        return [
            parse_task(item, base_url=self._base_url, url_template=self._url_template)
            for item in by_id.values()
        ]
