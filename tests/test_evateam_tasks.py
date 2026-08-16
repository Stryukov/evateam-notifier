"""Поиск сотрудника по Telegram и проверка прав — основа контроля доступа."""

import json

import httpx
import pytest
import respx

from evateam_bot.evateam.client import EvaTeamClient
from evateam_bot.evateam.tasks import PERSON_FIELDS, EvaTeamTasks, normalize_telegram

BASE = "https://eva.example.ru"
URL = f"{BASE}/api/"

IVANOV = {
    "id": "CmfPerson:1",
    "name": "Иванов Иван",
    "login": "ivanov@x.ru",
    "telegram": "https://t.me/ivanov",
}
PETROV = {
    "id": "CmfPerson:2",
    "name": "Петров Пётр",
    "login": "petrov@x.ru",
    "telegram": "https://t.me/2127378",  # хранится числовой id
}
NO_TELEGRAM = {"id": "CmfPerson:3", "name": "Без телеграма", "login": "x@x.ru"}

PEOPLE = [IVANOV, PETROV, NO_TELEGRAM]


async def _api(handler):
    respx.post(URL).mock(side_effect=handler)
    client = EvaTeamClient(BASE, "token", "bearer")
    return EvaTeamTasks(client, base_url=BASE), client


def _people_responder(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"result": PEOPLE})


# --- нормализация --------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["https://t.me/Strk0v", "http://t.me/strk0v", "t.me/STRK0V", "@strk0v",
     "strk0v", "https://t.me/strk0v/", " https://t.me/strk0v "],
)
def test_all_forms_normalize_to_same_tail(value):
    """EvaTeam сама дописывает схему, поэтому в поле лежит ссылка."""
    assert normalize_telegram(value) == "strk0v"


def test_numeric_id_survives_normalization():
    assert normalize_telegram("https://t.me/212737863") == "212737863"
    assert normalize_telegram("212737863") == "212737863"


def test_empty_values_give_none():
    """Иначе сотрудник с пустым полем совпал бы с отправителем без username."""
    for value in (None, "", "   ", "https://t.me/"):
        assert normalize_telegram(value) is None


def test_query_string_and_path_are_trimmed():
    assert normalize_telegram("https://t.me/strk0v?start=1") == "strk0v"


# --- поиск ---------------------------------------------------------------------


@respx.mock
async def test_finds_person_by_username_case_insensitively():
    api, client = await _api(_people_responder)
    async with client:
        person = await api.find_person_by_telegram("IVANOV")
    assert person is not None and person.id == "CmfPerson:1"


@respx.mock
async def test_finds_person_by_numeric_id():
    api, client = await _api(_people_responder)
    async with client:
        person = await api.find_person_by_telegram(None, "2127378")
    assert person is not None and person.id == "CmfPerson:2"


@respx.mock
async def test_substring_does_not_match():
    """«ivan» не должен совпасть с «ivanov», «212» — с «2127378»."""
    api, client = await _api(_people_responder)
    async with client:
        assert await api.find_person_by_telegram("ivan") is None
        assert await api.find_person_by_telegram(None, "212") is None


@respx.mock
async def test_sender_without_identity_matches_nobody():
    api, client = await _api(_people_responder)
    async with client:
        assert await api.find_person_by_telegram(None, None) is None
        assert await api.find_person_by_telegram("", "") is None


@respx.mock
async def test_person_without_telegram_is_never_matched():
    api, client = await _api(_people_responder)
    async with client:
        assert await api.find_person_by_telegram("Без телеграма") is None


@respx.mock
async def test_person_query_asks_for_hidden_fields():
    """`telegram` и `rg_member_of` не приходят в fields:["**"] — запрашиваем явно."""
    route = respx.post(URL).mock(side_effect=_people_responder)
    client = EvaTeamClient(BASE, "token", "bearer")
    async with client:
        await EvaTeamTasks(client, base_url=BASE).find_person_by_telegram("ivanov")

    body = json.loads(route.calls.last.request.content)
    fields = body["kwargs"]["fields"]
    assert "telegram" in fields
    assert "rg_member_of.code" in fields
    assert "telegram" in PERSON_FIELDS


# --- права ---------------------------------------------------------------------


@respx.mock
async def test_is_admin_filters_by_group_code():
    captured: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        conditions = body["kwargs"]["filter"]
        in_group = ["rg_member_of.code", "==", "Admins"] in conditions
        return httpx.Response(200, json={"result": [{"id": "CmfPerson:1"}] if in_group else []})

    api, client = await _api(responder)
    async with client:
        assert await api.is_admin("CmfPerson:1") is True
        assert await api.is_admin("CmfPerson:1", "Curators") is False

    assert ["id", "==", "CmfPerson:1"] in captured[0]["kwargs"]["filter"]


@respx.mock
async def test_is_admin_false_when_nobody_returned():
    api, client = await _api(lambda r: httpx.Response(200, json={"result": []}))
    async with client:
        assert await api.is_admin("CmfPerson:9") is False
