import json

import httpx
import respx

from evateam_bot.core.models import StatusCategory
from evateam_bot.evateam.client import EvaTeamClient
from evateam_bot.evateam.portfolio import EvaTeamPortfolio

BASE = "https://eva.example.ru"
URL = f"{BASE}/api/"

EPIC = {
    "id": "CmfTask:e1",
    "code": "BLT-30",
    "name": "Epic Работа с дебиторами",
    "logic_prefix": "task.epic",
    "cache_status_type": "IN_PROGRESS",
    "status": {"id": "CmfStatus:s1", "code": "in_progress", "name": "В работе"},
    "op_gantt_task": {
        "id": "CmfGanttTask:g1",
        "sched_start_date": "2026-08-01T00:00:00+03:00",
        "sched_finish_date": "2026-09-30T00:00:00+03:00",
    },
    "parent_id": "CmfProject:p1",
    "parent": {"id": "CmfProject:p1", "name": "Биллинг (задачи)"},
    "main_list.code": None,
    "main_list": {"code": "LBRD-1"},
}

TASK_IN_PROGRESS = {
    "id": "CmfTask:t1",
    "code": "BLT-31",
    "name": "Выгрузка реестра",
    "logic_prefix": "task.agile",
    "cache_status_type": "IN_PROGRESS",
    "status": {"code": "in_progress", "name": "В работе"},
    "epic_id": "CmfTask:e1",
    "parent_id": "CmfProject:p1",
    "responsible": {"id": "CmfPerson:u1", "name": "Иванов Иван"},
    "deadline": "2026-08-20T08:00:00+03:00",
    "main_list": {"code": "LBRD-1"},
}

TASK_IN_REVIEW = {
    "id": "CmfTask:t2",
    "code": "BLT-32",
    "name": "Проверка расчёта",
    "logic_prefix": "task.agile",
    "cache_status_type": "IN_REVIEW",
    "status": {"code": "in_review", "name": "Подтверждение закрытия"},
    "epic_id": "CmfTask:e1",
    "parent_id": "CmfProject:p1",
    "executors": [{"id": "CmfPerson:u2", "name": "Петров Пётр"}],
    "main_list": {"code": "LBRD-1"},
}

ORPHAN = {
    "id": "CmfTask:t3",
    "code": "HLP-1",
    "name": "Задача без эпика",
    "logic_prefix": "task.sd_service_request",
    "cache_status_type": "IN_PROGRESS",
    "status": {"code": "in_progress", "name": "В работе"},
    "parent_id": "CmfProject:p2",
    "main_list": {"code": "HBRD-1"},
}

PROJECT = {"id": "CmfProject:p1", "code": "billing-tasks", "name": "Биллинг (задачи)"}


def _bodies(route) -> list[dict]:
    return [json.loads(call.request.content) for call in route.calls]


def _responder(request: httpx.Request) -> httpx.Response:
    """Отвечает по методу из тела запроса — так видно, что и сколько раз спрашивали."""
    payload = json.loads(request.content)
    method = payload.get("method")
    filt = payload.get("kwargs", {}).get("filter") or []
    if method == "CmfProject.list":
        return httpx.Response(200, json={"result": [PROJECT]})
    if method == "CmfKanbanBoard.list":
        return httpx.Response(200, json={"result": []})
    if method == "CmfStatus.list":
        return httpx.Response(200, json={"result": []})
    if method == "CmfTask.list":
        conditions = {(c[0], str(c[2])) for c in filt if isinstance(c, list) and len(c) == 3}
        if ("logic_prefix", "task.epic") in conditions:
            return httpx.Response(200, json={"result": [EPIC]})
        if ("cache_status_type", "IN_PROGRESS") in conditions:
            return httpx.Response(200, json={"result": [TASK_IN_PROGRESS, ORPHAN, EPIC]})
        if ("cache_status_type", "IN_REVIEW") in conditions:
            return httpx.Response(200, json={"result": [TASK_IN_REVIEW]})
    return httpx.Response(200, json={"result": []})


async def _fetch():
    async with EvaTeamClient(BASE, "token", "bearer") as client:
        return await EvaTeamPortfolio(client, base_url=BASE).get_portfolio()


@respx.mock
async def test_epics_and_tasks_are_grouped():
    respx.post(URL).mock(side_effect=_responder)
    portfolio = await _fetch()

    assert [e.code for e in portfolio.epics] == ["BLT-30"]
    epic = portfolio.epics[0]
    assert epic.status_code == "in_progress"
    assert epic.project_name == "Биллинг (задачи)"
    assert epic.plan_start is not None and epic.plan_end is not None

    tasks = portfolio.tasks_by_epic["CmfTask:e1"]
    assert {t.code for t in tasks} == {"BLT-31", "BLT-32"}
    assert [t.code for t in portfolio.orphan_tasks] == ["HLP-1"]


@respx.mock
async def test_active_tasks_use_exactly_two_calls_and_drop_epics():
    route = respx.post(URL).mock(side_effect=_responder)
    portfolio = await _fetch()

    status_filters = [
        cond[2]
        for body in _bodies(route)
        if body.get("method") == "CmfTask.list"
        for cond in body.get("kwargs", {}).get("filter", [])
        if cond[0] == "cache_status_type" and cond[1] == "=="
    ]
    assert status_filters == ["IN_PROGRESS", "IN_REVIEW"]

    # Эпик пришёл в выдаче задач (он тоже IN_PROGRESS), но задачей не считается.
    all_task_ids = {t.id for tasks in portfolio.tasks_by_epic.values() for t in tasks}
    assert "CmfTask:e1" not in all_task_ids
    assert "CmfTask:e1" not in {t.id for t in portfolio.orphan_tasks}


@respx.mock
async def test_epic_query_asks_for_gantt_dates_and_status_code():
    route = respx.post(URL).mock(side_effect=_responder)
    await _fetch()

    epic_body = next(
        body
        for body in _bodies(route)
        if body.get("method") == "CmfTask.list"
        and any(c[0] == "logic_prefix" for c in body["kwargs"]["filter"])
    )
    fields = epic_body["kwargs"]["fields"]
    for expected in (
        "status.code",
        "op_gantt_task.sched_start_date",
        "op_gantt_task.sched_finish_date",
        "parent_id",
    ):
        assert expected in fields
    # Собственные поля задачи не запрашиваем: там устаревшие значения.
    assert "plan_start_date" not in fields
    assert "plan_end_date" not in fields


@respx.mock
async def test_assignee_falls_back_to_executors():
    respx.post(URL).mock(side_effect=_responder)
    portfolio = await _fetch()

    by_code = {t.code: t for t in portfolio.tasks_by_epic["CmfTask:e1"]}
    assert by_code["BLT-31"].assignee == "Иванов Иван"  # responsible
    assert by_code["BLT-32"].assignee == "Петров Пётр"  # executors[0]


@respx.mock
async def test_task_urls_are_built():
    respx.post(URL).mock(side_effect=_responder)
    portfolio = await _fetch()

    assert portfolio.epics[0].url == f"{BASE}/project/List/LBRD-1?obj=Task:BLT-30"


@respx.mock
async def test_status_id_string_is_resolved_via_status_index():
    """Если инстанс отдаёт `status` голой id-строкой, код берётся из справочника."""
    epic = dict(EPIC, status="CmfStatus:s9")

    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload.get("method")
        filt = payload.get("kwargs", {}).get("filter") or []
        if method == "CmfStatus.list":
            return httpx.Response(
                200,
                json={"result": [{"id": "CmfStatus:s9", "code": "pause", "name": "Пауза"}]},
            )
        if method == "CmfTask.list" and any(c[0] == "logic_prefix" for c in filt):
            return httpx.Response(200, json={"result": [epic]})
        return httpx.Response(200, json={"result": []})

    respx.post(URL).mock(side_effect=responder)
    portfolio = await _fetch()

    assert portfolio.epics[0].status_code == "pause"
    assert portfolio.epics[0].status_name == "Пауза"


@respx.mock
async def test_falls_back_when_logic_prefix_filter_rejected():
    """Если сервер не умеет фильтровать по logic_prefix — отбираем эпики на клиенте."""

    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        filt = payload.get("kwargs", {}).get("filter") or []
        if payload.get("method") != "CmfTask.list":
            return httpx.Response(200, json={"result": []})
        if any(c[0] == "logic_prefix" for c in filt):
            return httpx.Response(200, json={"error": {"code": -32602, "message": "bad field"}})
        if any(c[0] == "cache_status_type" and c[1] == "!=" for c in filt):
            return httpx.Response(200, json={"result": [EPIC, ORPHAN]})
        return httpx.Response(200, json={"result": []})

    respx.post(URL).mock(side_effect=responder)
    portfolio = await _fetch()

    assert [e.code for e in portfolio.epics] == ["BLT-30"]


async def test_status_category_of_in_review_is_waiting():
    from evateam_bot.evateam.dto import parse_epic

    epic = parse_epic(dict(EPIC, cache_status_type="IN_REVIEW"))
    assert epic.status_category is StatusCategory.WAITING
