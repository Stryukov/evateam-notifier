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

# Плановые даты («мягкий» срок) живут НЕ на CmfTask, а в связанном CmfGanttTask:
# CmfTask.op_gantt_task -> sched_start_date / sched_finish_date. Именно их показывает
# интерфейс как «Плановая дата начала/окончания».
# ВНИМАНИЕ: собственные plan_start_date/plan_end_date у CmfTask — ДРУГАЯ пара полей.
# Интерфейс их не показывает и не обновляет, но там остаются устаревшие значения,
# поэтому мы их намеренно НЕ запрашиваем и НЕ используем как фолбэк (см. dto.plan_dates).
# `deadline` на CmfTask — «Крайний срок», жёсткий дедлайн.
GANTT_START_FIELD = "op_gantt_task.sched_start_date"
GANTT_END_FIELD = "op_gantt_task.sched_finish_date"

# «Порядок выполнения» — пользовательское поле (CmfCustField, тип CmfInt на CmfTask).
# Заполняется вручную (1, 2, 3…) для эпиков с одинаковым приоритетом.
# ВНИМАНИЕ: в дамп `fields: ["**"]` пользовательские поля не попадают — запрашивать явно.
CUSTOM_ORDER_FIELD = "cf_poryadok_v"

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
    # Плановые сроки и код статуса нужны вечернему напоминанию, чтобы отличать
    # сорванный крайний срок от отставания от плана. Дайджест их не выводит.
    "status.code",
    "status.name",
    GANTT_START_FIELD,
    GANTT_END_FIELD,
]

# `telegram` и `rg_member_of` НЕ приходят в fields:["**"] — как и пользовательские поля.
# Запрашиваем явно. `telegram` хранится ссылкой: "https://t.me/strk0v" либо
# "https://t.me/212737863" (числовой id) — EvaTeam сама дописывает схему.
PERSON_FIELDS = [
    "id",
    "name",
    "login",
    "email",
    "code",
    "telegram",
    "rg_member_of.code",
]

#: Код группы EvaTeam, дающей доступ к управленческой сводке.
DEFAULT_ADMIN_GROUP = "Admins"

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
    "deadline",
    "priority",
    CUSTOM_ORDER_FIELD,
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


def normalize_telegram(value: Any) -> str | None:
    """Привести Telegram-идентификатор к «хвосту» для сравнения.

    EvaTeam хранит поле ссылкой и сама дописывает схему, поэтому в карточке лежит
    `https://t.me/strk0v` или `https://t.me/212737863`. Сводим к одному виду обе
    стороны сравнения:

        https://t.me/Strk0v  ->  strk0v
        t.me/strk0v          ->  strk0v
        @strk0v              ->  strk0v
        212737863            ->  212737863

    Пустое значение даёт None — иначе сотрудник с незаполненным полем совпал бы
    с отправителем без username.
    """
    if value is None:
        return None
    text = str(value).strip()
    for prefix in ("https://", "http://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    # Хост отбрасываем вместе с ним самим: у «https://t.me/» хвоста нет вовсе,
    # и вернуть «t.me» было бы мусорным идентификатором.
    for host in ("t.me", "telegram.me"):
        if text.lower() == host or text.lower().startswith(host + "/"):
            text = text[len(host):].lstrip("/")
            break
    text = text.lstrip("@").split("?", 1)[0].split("/", 1)[0].strip()
    return text.lower() or None


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

    async def find_person_by_telegram(
        self, username: str | None, user_id: str | None = None
    ) -> Person | None:
        """Сотрудник, чей Telegram указан в карточке EvaTeam. None — доступа нет.

        Сверяем на клиенте: серверный `LIKE "%имя%"` дал бы ложные совпадения
        («ivan» внутри «ivanov», «212» внутри «2127378»). Людей меньше сотни,
        одного запроса достаточно.
        """
        wanted = {normalize_telegram(value) for value in (username, user_id)}
        wanted.discard(None)
        if not wanted:
            return None

        result = await self._client.call(
            METHOD_PERSON_LIST, kwargs={"fields": PERSON_FIELDS}
        )
        for item in _extract_items(result):
            if normalize_telegram(item.get("telegram")) in wanted:
                return parse_person(item)
        return None

    async def is_admin(self, person_id: str, group_code: str = DEFAULT_ADMIN_GROUP) -> bool:
        """Состоит ли сотрудник в группе EvaTeam (по умолчанию Admins).

        Проверяется в момент вызова, а не при привязке: иначе исключение из группы
        не подействовало бы до перепривязки.
        """
        result = await self._client.call(
            METHOD_PERSON_LIST,
            kwargs={
                "filter": [
                    ["id", "==", person_id],
                    ["rg_member_of.code", "==", group_code],
                ],
                "fields": ["id"],
            },
        )
        return bool(_extract_items(result))

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
