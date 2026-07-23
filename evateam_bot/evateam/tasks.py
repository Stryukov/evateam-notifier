"""Запросы к EvaTeam: поиск людей и задач сотрудника.

⚠️  OPEN ITEMS — уточнить на живом инстансе (через evateam/smoke.py):
    Имена методов и синтаксис фильтра (UBQL/BQL) вынесены в константы ниже.
    Если запросы не отрабатывают — правьте ТОЛЬКО этот файл, остальной код не зависит
    от конкретных методов EvaTeam.
"""

from __future__ import annotations

from typing import Any

from ..core.models import Person, Task
from .client import EvaTeamClient
from .dto import parse_person, parse_task

# --- OPEN ITEMS: методы EvaTeam (предположительные, подтвердить smoke-скриптом) ---
METHOD_PERSON_LIST = "CmfPerson.api_list"
METHOD_TASK_LIST = "CmfTask.api_list"

# Поля, которые запрашиваем у задачи.
TASK_FIELDS = [
    "id",
    "code",
    "name",
    "status",
    "activity",
    "deadline",
    "priority",
    "executors",
    "responsible",
    "waiting_for",
]

PERSON_FIELDS = ["id", "name", "login", "email", "email1"]


def _extract_items(result: Any) -> list[dict[str, Any]]:
    """Достать список записей из разных возможных форм ответа EvaTeam."""
    if result is None:
        return []
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        for key in ("items", "rows", "data", "objects", "result", "list"):
            value = result.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        # Одиночный объект.
        if result.get("id"):
            return [result]
    return []


class EvaTeamTasks:
    """Высокоуровневые операции над задачами/людьми поверх JSON-RPC клиента."""

    def __init__(self, client: EvaTeamClient, base_url: str | None = None) -> None:
        self._client = client
        self._base_url = base_url

    async def find_person(self, query: str) -> list[Person]:
        """Найти пользователя(-ей) по email или логину."""
        query = query.strip()
        # OPEN ITEM: синтаксис фильтра. Пробуем совпадение по login или email.
        params = {
            "filter": {
                "or": [
                    {"login": query},
                    {"email": query},
                    {"email1": query},
                ]
            },
            "fields": PERSON_FIELDS,
            "limit": 10,
        }
        result = await self._client.call(METHOD_PERSON_LIST, params)
        return [parse_person(item) for item in _extract_items(result)]

    async def get_tasks_for_person(self, person_id: str) -> list[Task]:
        """Активные задачи, где сотрудник — исполнитель или ответственный."""
        # OPEN ITEM: синтаксис фильтра по исполнителю/ответственному и активности.
        params = {
            "filter": {
                "and": [
                    {
                        "or": [
                            {"executors": person_id},
                            {"responsible": person_id},
                        ]
                    },
                    {"activity": "active"},
                ]
            },
            "fields": TASK_FIELDS,
            "limit": 500,
        }
        result = await self._client.call(METHOD_TASK_LIST, params)
        return [parse_task(item, base_url=self._base_url) for item in _extract_items(result)]
