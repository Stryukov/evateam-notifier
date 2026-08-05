"""Срез портфеля EvaTeam: эпики, их активные задачи и проекты.

В отличие от `tasks.py` (задачи одного сотрудника — дайджест и просрочки), здесь
собирается управленческая картина по всем проектам сразу.

Ключевые факты о схеме EvaTeam (подтверждены на живом инстансе):
- эпик — это `CmfTask` с `logic_prefix = "task.epic"`, отдельной модели нет;
- задача ссылается на эпик через `epic_id`, на проект — через `parent_id`;
- различать статусы надо по `status.code`: у кода `pause` тип как раз `OPEN`,
  и по `cache_status_type` его от `TO DO` не отличить.

Все имена методов и полей — в `tasks.py` (правило CLAUDE.md).
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.models import Portfolio, Task
from .client import EvaTeamClient, EvaTeamError
from .dto import parse_epic, parse_task
from .tasks import (
    ACTIVE_STATUS_TYPES,
    CLOSED_STATUS_TYPE,
    EPIC_FIELDS,
    EPIC_LOGIC_PREFIX,
    EPIC_TASK_FIELDS,
    METHOD_PROJECT_LIST,
    METHOD_STATUS_LIST,
    METHOD_TASK_LIST,
    PROJECT_FIELDS,
    STATUS_FIELDS,
    _extract_items,
    kanban_by_project,
    task_url,
)

logger = logging.getLogger(__name__)


class EvaTeamPortfolio:
    """Сбор портфеля одним вызовом `get_portfolio()` (4 запроса к EvaTeam)."""

    def __init__(self, client: EvaTeamClient, base_url: str | None = None) -> None:
        self._client = client
        self._base_url = (base_url or "").rstrip("/")
        self._status_index: dict[str, tuple[str | None, str | None]] | None = None

    async def get_portfolio(self) -> Portfolio:
        epics_raw = await self._fetch_epics()
        tasks_raw = await self._fetch_active_tasks()
        projects = await self._fetch_projects()

        # Ссылки строим одним проходом: и эпики, и задачи — это CmfTask.
        kanban = await kanban_by_project(self._client, epics_raw + tasks_raw)
        await self._fill_status_codes(epics_raw + tasks_raw)

        epics = [parse_epic(raw, url=task_url(self._base_url, raw, kanban)) for raw in epics_raw]
        tasks = [parse_task(raw, url=task_url(self._base_url, raw, kanban)) for raw in tasks_raw]

        # Названия проектов: из справочника, дополняя тем, что пришло в самих эпиках.
        project_names = dict(projects)
        for epic in epics:
            if epic.project_id and epic.project_name:
                project_names.setdefault(epic.project_id, epic.project_name)

        known_epic_ids = {epic.id for epic in epics}
        tasks_by_epic: dict[str, list[Task]] = {}
        orphan_tasks: list[Task] = []
        for task in tasks:
            if task.epic_id and task.epic_id in known_epic_ids:
                tasks_by_epic.setdefault(task.epic_id, []).append(task)
            else:
                orphan_tasks.append(task)

        return Portfolio(
            epics=epics,
            tasks_by_epic=tasks_by_epic,
            orphan_tasks=orphan_tasks,
            project_names=project_names,
        )

    async def _fetch_epics(self) -> list[dict[str, Any]]:
        """Все незакрытые эпики (1 запрос).

        Фильтр по списку кодов статусов делается НЕ здесь, а в `core/summary.py`:
        условия EvaTeam соединяются только по И, OR-списка нет, а эпиков десятки —
        отобрать их на клиенте дешевле, чем слать запрос на каждый код.
        """
        not_closed = ["cache_status_type", "!=", CLOSED_STATUS_TYPE]
        try:
            result = await self._client.call(
                METHOD_TASK_LIST,
                kwargs={
                    "filter": [["logic_prefix", "==", EPIC_LOGIC_PREFIX], not_closed],
                    "fields": EPIC_FIELDS,
                    "order_by": ["name"],
                },
            )
        except EvaTeamError:
            # Фолбэк на случай, если logic_prefix не фильтруется на сервере.
            logger.warning("Фильтр по logic_prefix не сработал, отбираю эпики на клиенте")
            result = await self._client.call(
                METHOD_TASK_LIST,
                kwargs={"filter": [not_closed], "fields": EPIC_FIELDS, "order_by": ["name"]},
            )
        return [item for item in _extract_items(result) if _is_epic(item)]

    async def _fetch_active_tasks(self) -> list[dict[str, Any]]:
        """Задачи в работе и ждущие подтверждения закрытия.

        Два запроса со слиянием по id — тот же приём, что в `get_tasks_for_person`:
        «IN_PROGRESS ИЛИ IN_REVIEW» одним фильтром не выразить.
        """
        by_id: dict[str, dict[str, Any]] = {}
        for status_type in ACTIVE_STATUS_TYPES:
            result = await self._client.call(
                METHOD_TASK_LIST,
                kwargs={
                    "filter": [["cache_status_type", "==", status_type]],
                    "fields": EPIC_TASK_FIELDS,
                    "order_by": ["deadline"],
                },
            )
            for item in _extract_items(result):
                if item.get("id"):
                    by_id[item["id"]] = item
        # Сам эпик может быть в работе — но он не задача внутри себя.
        return [item for item in by_id.values() if not _is_epic(item)]

    async def _fetch_projects(self) -> dict[str, str]:
        """project_id -> название. Мягко: без проектов отчёт всё равно собирается."""
        try:
            result = await self._client.call(
                METHOD_PROJECT_LIST, kwargs={"fields": PROJECT_FIELDS}
            )
        except EvaTeamError:
            logger.warning("Не удалось получить список проектов", exc_info=True)
            return {}
        return {
            item["id"]: name
            for item in _extract_items(result)
            if item.get("id") and (name := (item.get("name") or "").strip())
        }

    async def _fill_status_codes(self, items: list[dict[str, Any]]) -> None:
        """Дозаполнить `status` кодом/именем, если инстанс отдал его id-строкой.

        Основной путь — вложенное поле `status.code`. Запасной нужен на случай,
        когда EvaTeam возвращает связь строкой: тогда один раз тянем справочник
        статусов и разрешаем id -> (code, name) прямо в сырых словарях.
        """
        pending = [item for item in items if isinstance(item.get("status"), str)]
        if not pending:
            return
        index = await self._load_status_index()
        if not index:
            return
        for item in pending:
            code, name = index.get(item["status"], (None, None))
            if code or name:
                item["status"] = {"id": item["status"], "code": code, "name": name}

    async def _load_status_index(self) -> dict[str, tuple[str | None, str | None]]:
        if self._status_index is not None:
            return self._status_index
        try:
            result = await self._client.call(
                METHOD_STATUS_LIST, kwargs={"fields": STATUS_FIELDS}
            )
        except EvaTeamError:
            logger.warning("Не удалось загрузить справочник статусов", exc_info=True)
            self._status_index = {}
            return self._status_index
        self._status_index = {
            item["id"]: (item.get("code"), item.get("name"))
            for item in _extract_items(result)
            if item.get("id")
        }
        return self._status_index


def _is_epic(raw: dict[str, Any]) -> bool:
    return raw.get("logic_prefix") == EPIC_LOGIC_PREFIX
