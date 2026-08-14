from datetime import datetime

import pytest

from evateam_bot.core import formatting
from evateam_bot.core.messages import OutgoingDocument, OutgoingMessage
from evateam_bot.core.models import Epic, Person, Portfolio, StatusCategory, Task
from evateam_bot.core.summary import SummaryOptions
from evateam_bot.service import BotService
from evateam_bot.storage.db import make_session_factory
from evateam_bot.storage.repository import UserRepository
from evateam_bot.transports.base import BotTransport


class FakeTransport(BotTransport):
    name = "telegram"
    supports_documents = True

    def __init__(self):
        super().__init__()
        self.sent: list[tuple[str, OutgoingMessage]] = []
        self.sent_docs: list[tuple[str, OutgoingDocument]] = []

    async def send_message(self, chat_id, message):
        self.sent.append((chat_id, message))

    async def send_document(self, chat_id, document):
        self.sent_docs.append((chat_id, document))

    async def start(self):  # pragma: no cover
        pass

    async def stop(self):  # pragma: no cover
        pass

    @property
    def texts(self) -> str:
        return "\n".join(message.text for _, message in self.sent)


class TextOnlyTransport(FakeTransport):
    """Транспорт, не умеющий файлы — как гипотетический MAX на первых порах."""

    supports_documents = False

    async def send_document(self, chat_id, document):  # pragma: no cover
        raise NotImplementedError


class FakeTasks:
    def __init__(self, people=None, tasks=None):
        self._people = people or {}
        self._tasks = tasks or {}

    async def find_person(self, query):
        return self._people.get(query.strip(), [])

    async def get_tasks_for_person(self, person_id):
        return self._tasks.get(person_id, [])


class FakePortfolio:
    def __init__(self, portfolio=None, error=None):
        self._portfolio = portfolio if portfolio is not None else Portfolio()
        self._error = error

    async def get_portfolio(self):
        if self._error:
            raise self._error
        return self._portfolio


def _epic(id_="e1", *, status="in_progress", end=None):
    return Epic(
        id=id_,
        code=id_.upper(),
        title="Эпик",
        status_code=status,
        status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        project_id="p1",
        project_name="Проект",
        plan_end=end,
    )


@pytest.fixture
def repo(tmp_path):
    sf = make_session_factory(str(tmp_path / "db" / "test.db"))
    return UserRepository(sf)


@pytest.fixture
def report_dir(tmp_path):
    """Отдельный каталог: рядом с БД не видно, что отчёт ничего не записал."""
    return tmp_path / "reports"


def _make_service(repo, tasks, *, portfolio=None, report_dir=None, transport=None):
    transport = transport or FakeTransport()
    kwargs = {}
    if portfolio is not None:
        kwargs["portfolio_api"] = portfolio
        kwargs["summary_options"] = SummaryOptions(status_codes=("in_progress",))
    if report_dir is not None:
        kwargs["report_dir"] = str(report_dir)
    service = BotService(
        transports={transport.name: transport}, tasks_api=tasks, repo=repo, **kwargs
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


async def test_evening_reminder_sent_when_there_is_work(repo):
    tasks = FakeTasks(tasks={"p1": [
        Task(id="t1", code="PRJ-1", title="В работе", status_name="В работе",
             status_category=StatusCategory.IN_PROGRESS),
    ]})
    service, transport = _make_service(repo, tasks)
    repo.link(transport="telegram", chat_id="100", person_id="p1", person_name="Пётр")

    count = await service.send_evening_reminders(now=datetime(2026, 8, 5, 16, 0))
    assert count == 1
    assert "Итоги дня" in transport.texts
    assert "PRJ-1" in transport.texts


async def test_evening_reminder_skips_users_without_active_tasks(repo):
    """Закрывать и двигать нечего — не дёргаем человека."""
    tasks = FakeTasks(tasks={"p1": [
        Task(id="t1", code="PRJ-1", title="Не начата", status_name="TO DO",
             status_category=StatusCategory.OPEN),
    ]})
    service, transport = _make_service(repo, tasks)
    repo.link(transport="telegram", chat_id="100", person_id="p1", person_name="Пётр")

    assert await service.send_evening_reminders() == 0
    assert transport.sent == []


# --- сводка по проектам --------------------------------------------------------


def test_service_still_builds_without_summary_arguments(repo):
    """Регресс: старая сборка на трёх аргументах не должна сломаться."""
    transport = FakeTransport()
    service = BotService(
        transports={transport.name: transport}, tasks_api=FakeTasks(), repo=repo
    )
    assert service is not None


async def test_summary_command_sends_text_and_two_documents(repo, report_dir):
    portfolio = Portfolio(
        epics=[_epic(end=datetime(2026, 1, 1))],
        tasks_by_epic={},
        project_names={"p1": "Проект"},
    )
    service, transport = _make_service(
        repo, FakeTasks(), portfolio=FakePortfolio(portfolio), report_dir=report_dir
    )

    await service.on_command("telegram", "100", "summary", "")

    assert "Собираю сводку" in transport.sent[0][1].text
    assert "Сводка по проектам" in transport.sent[-1][1].text
    assert [doc.filename.rsplit(".", 1)[1] for _, doc in transport.sent_docs] == ["html", "csv"]
    assert len(list(report_dir.iterdir())) == 3  # html + csv + json


async def test_summary_falls_back_to_paths_without_document_support(repo, report_dir):
    portfolio = Portfolio(epics=[_epic(end=datetime(2026, 1, 1))], project_names={"p1": "П"})
    service, transport = _make_service(
        repo,
        FakeTasks(),
        portfolio=FakePortfolio(portfolio),
        report_dir=report_dir,
        transport=TextOnlyTransport(),
    )

    await service.on_command("telegram", "100", "summary", "")

    assert transport.sent_docs == []
    assert "Файлы отчёта сохранены" in transport.texts
    assert ".html" in transport.texts


async def test_empty_summary_explains_and_writes_nothing(repo, report_dir):
    # Эпик есть, но статус не подходит под фильтр.
    portfolio = Portfolio(epics=[_epic(status="open")], project_names={})
    service, transport = _make_service(
        repo, FakeTasks(), portfolio=FakePortfolio(portfolio), report_dir=report_dir
    )

    ok = await service.send_summary("telegram", "100")

    assert ok is False
    assert "SUMMARY_EPIC_STATUS_CODES" in transport.texts
    assert transport.sent_docs == []
    assert not report_dir.exists()


async def test_summary_error_is_reported_not_raised(repo, report_dir):
    service, transport = _make_service(
        repo,
        FakeTasks(),
        portfolio=FakePortfolio(error=RuntimeError("EvaTeam недоступна")),
        report_dir=report_dir,
    )

    ok = await service.send_summary("telegram", "100")

    assert ok is False
    assert "Не удалось собрать сводку" in transport.texts
    assert "EvaTeam недоступна" in transport.texts


async def test_summary_to_all_collects_data_once(repo, report_dir):
    class CountingPortfolio(FakePortfolio):
        calls = 0

        async def get_portfolio(self):
            CountingPortfolio.calls += 1
            return await super().get_portfolio()

    portfolio = Portfolio(epics=[_epic(end=datetime(2026, 1, 1))], project_names={"p1": "П"})
    service, transport = _make_service(
        repo, FakeTasks(), portfolio=CountingPortfolio(portfolio), report_dir=report_dir
    )
    for chat in ("100", "200"):
        repo.link(transport="telegram", chat_id=chat, person_id="p1", person_name="П")

    sent = await service.send_summary_to_all()

    assert sent == 2
    assert CountingPortfolio.calls == 1  # данные тянем один раз на всю рассылку
    assert len(transport.sent_docs) == 4  # по два файла на чат


async def test_unknown_command_lists_available(repo):
    service, transport = _make_service(repo, FakeTasks())
    await service.on_command("telegram", "100", "wat", "")
    assert "/summary" in transport.texts


async def test_start_command_routes_to_welcome(repo):
    service, transport = _make_service(repo, FakeTasks())
    await service.on_command("telegram", "100", "start", "")
    assert "email" in transport.texts
