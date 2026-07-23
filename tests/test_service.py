from datetime import datetime

import pytest

from evateam_bot.core import formatting
from evateam_bot.core.messages import OutgoingMessage
from evateam_bot.core.models import Person, StatusCategory, Task
from evateam_bot.service import BotService
from evateam_bot.storage.db import make_session_factory
from evateam_bot.storage.repository import UserRepository
from evateam_bot.transports.base import BotTransport


class FakeTransport(BotTransport):
    name = "telegram"

    def __init__(self):
        super().__init__()
        self.sent: list[tuple[str, OutgoingMessage]] = []

    async def send_message(self, chat_id, message):
        self.sent.append((chat_id, message))

    async def start(self):  # pragma: no cover
        pass

    async def stop(self):  # pragma: no cover
        pass


class FakeTasks:
    def __init__(self, people=None, tasks=None):
        self._people = people or {}
        self._tasks = tasks or {}

    async def find_person(self, query):
        return self._people.get(query.strip(), [])

    async def get_tasks_for_person(self, person_id):
        return self._tasks.get(person_id, [])


@pytest.fixture
def repo(tmp_path):
    sf = make_session_factory(str(tmp_path / "test.db"))
    return UserRepository(sf)


def _make_service(repo, tasks):
    transport = FakeTransport()
    service = BotService(
        transports={transport.name: transport}, tasks_api=tasks, repo=repo
    )
    return service, transport


async def test_onboarding_flow_links_user(repo):
    person = Person(id="CmfPerson:1", name="Иван Иванов", email="ivan@x.ru")
    tasks = FakeTasks(people={"ivan@x.ru": [person]})
    service, transport = _make_service(repo, tasks)

    await service.on_start("telegram", "100")
    await service.on_text("telegram", "100", "ivan@x.ru")
    # предложено подтверждение
    confirm_action = transport.sent[-1][1].buttons[0][0].action
    assert confirm_action == f"{formatting.ACTION_CONFIRM_PREFIX}CmfPerson:1"

    await service.on_action("telegram", "100", confirm_action)
    link = repo.get(transport="telegram", chat_id="100")
    assert link is not None
    assert link.person_id == "CmfPerson:1"
    assert "привязаны" in transport.sent[-1][1].text


async def test_daily_digest_sent_to_linked_user(repo):
    person = Person(id="p1", name="Пётр", email="p@x.ru")
    task = Task(
        id="t1", code="PRJ-1", title="Задача", status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
    )
    tasks = FakeTasks(people={"p@x.ru": [person]}, tasks={"p1": [task]})
    service, transport = _make_service(repo, tasks)
    repo.link(transport="telegram", chat_id="100", person_id="p1", person_name="Пётр")

    count = await service.send_daily_digests()
    assert count == 1
    assert "PRJ-1" in transport.sent[-1][1].text


async def test_deadline_reminder_dedup(repo):
    overdue = Task(
        id="t9", code="PRJ-9", title="Просрочка", status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS, deadline=datetime(2026, 1, 1),
    )
    tasks = FakeTasks(tasks={"p1": [overdue]})
    service, transport = _make_service(repo, tasks)
    repo.link(transport="telegram", chat_id="100", person_id="p1", person_name="Пётр")

    now = datetime(2026, 7, 23, 9, 0)
    first = await service.send_deadline_reminders(now=now)
    second = await service.send_deadline_reminders(now=now)
    assert first == 1
    assert second == 0  # дедуп: повторно за тот же день не шлём
    assert len(transport.sent) == 1
