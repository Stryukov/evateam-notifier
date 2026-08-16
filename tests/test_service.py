from datetime import datetime

import pytest

from evateam_bot.core import formatting
from evateam_bot.core.messages import OutgoingDocument, OutgoingMessage, Sender
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
    """Подменяет EvaTeam. `by_telegram` — карта username/id -> Person."""

    def __init__(self, people=None, tasks=None, by_telegram=None, admins=()):
        self._people = people or {}
        self._tasks = tasks or {}
        self._by_telegram = by_telegram or {}
        self._admins = set(admins)
        self.admin_checks: list[str] = []

    async def find_person(self, query):
        return self._people.get(query.strip(), [])

    async def find_person_by_telegram(self, username, user_id=None):
        for key in (username, user_id):
            if key and key.lower() in self._by_telegram:
                return self._by_telegram[key.lower()]
        return None

    async def is_admin(self, person_id, group_code="Admins"):
        self.admin_checks.append(person_id)
        return person_id in self._admins

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


PERSON = Person(id="CmfPerson:1", name="Иван Иванов", email="ivan@x.ru")


def _sender(chat_id="100", username="ivanov", user_id="777"):
    return Sender(chat_id=chat_id, user_id=user_id, username=username)


async def test_start_links_user_known_by_telegram(repo):
    tasks = FakeTasks(by_telegram={"ivanov": PERSON})
    service, transport = _make_service(repo, tasks)

    await service.on_start("telegram", _sender())

    link = repo.get(transport="telegram", chat_id="100")
    assert link is not None
    assert link.person_id == "CmfPerson:1"
    assert "привязаны" in transport.texts


async def test_start_matches_by_numeric_id(repo):
    tasks = FakeTasks(by_telegram={"212737863": PERSON})
    service, transport = _make_service(repo, tasks)

    await service.on_start("telegram", _sender(username=None, user_id="212737863"))

    assert repo.get(transport="telegram", chat_id="100") is not None


async def test_unknown_telegram_is_refused_and_not_stored(repo):
    """Ключевая защита: чужой не привязывается и в базу не попадает."""
    service, transport = _make_service(repo, FakeTasks(by_telegram={"ivanov": PERSON}))

    await service.on_start("telegram", _sender(username="stranger"))

    assert repo.get(transport="telegram", chat_id="100") is None
    assert "Не удалось вас опознать" in transport.texts


async def test_email_in_text_no_longer_links_anyone(repo):
    """Раньше так можно было привязаться к любому сотруднику по его email."""
    service, transport = _make_service(repo, FakeTasks(by_telegram={"ivanov": PERSON}))

    await service.on_text("telegram", _sender(username="stranger"), "ivan@x.ru")

    assert repo.get(transport="telegram", chat_id="100") is None
    assert "/start" in transport.texts


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


def _linked_admin_tasks():
    return FakeTasks(by_telegram={"ivanov": PERSON}, admins={PERSON.id})


async def test_summary_command_sends_text_and_two_documents(repo, report_dir):
    portfolio = Portfolio(
        epics=[_epic(end=datetime(2026, 1, 1))],
        tasks_by_epic={},
        project_names={"p1": "Проект"},
    )
    service, transport = _make_service(
        repo, _linked_admin_tasks(), portfolio=FakePortfolio(portfolio),
        report_dir=report_dir,
    )
    await service.on_start("telegram", _sender())

    await service.on_command("telegram", _sender(), "summary", "")

    assert "Собираю сводку" in transport.texts
    assert "Сводка по проектам" in transport.sent[-1][1].text
    assert [doc.filename.rsplit(".", 1)[1] for _, doc in transport.sent_docs] == ["html", "csv"]
    assert len(list(report_dir.iterdir())) == 3  # html + csv + json


async def test_summary_refused_for_non_admin(repo, report_dir):
    """Сводка по всему портфелю — управленческая информация."""
    portfolio = Portfolio(epics=[_epic(end=datetime(2026, 1, 1))], project_names={"p1": "П"})
    tasks = FakeTasks(by_telegram={"ivanov": PERSON})  # admins пуст
    service, transport = _make_service(
        repo, tasks, portfolio=FakePortfolio(portfolio), report_dir=report_dir
    )
    await service.on_start("telegram", _sender())

    await service.on_command("telegram", _sender(), "summary", "")

    assert "только администраторам" in transport.texts
    assert transport.sent_docs == []
    assert not report_dir.exists()  # портфель даже не собирался


async def test_summary_requires_link_first(repo, report_dir):
    service, transport = _make_service(
        repo, FakeTasks(), portfolio=FakePortfolio(), report_dir=report_dir
    )

    await service.on_command("telegram", _sender(), "summary", "")

    assert "/start" in transport.texts
    assert transport.sent_docs == []


async def test_admin_rights_checked_on_every_call(repo, report_dir):
    """Проверка живая: исключение из группы должно действовать сразу."""
    portfolio = Portfolio(epics=[_epic(end=datetime(2026, 1, 1))], project_names={"p1": "П"})
    tasks = _linked_admin_tasks()
    service, _ = _make_service(
        repo, tasks, portfolio=FakePortfolio(portfolio), report_dir=report_dir
    )
    await service.on_start("telegram", _sender())

    await service.on_command("telegram", _sender(), "summary", "")
    await service.on_command("telegram", _sender(), "summary", "")

    assert tasks.admin_checks == [PERSON.id, PERSON.id]


async def test_summary_falls_back_to_paths_without_document_support(repo, report_dir):
    portfolio = Portfolio(epics=[_epic(end=datetime(2026, 1, 1))], project_names={"p1": "П"})
    service, transport = _make_service(
        repo,
        _linked_admin_tasks(),
        portfolio=FakePortfolio(portfolio),
        report_dir=report_dir,
        transport=TextOnlyTransport(),
    )
    await service.on_start("telegram", _sender())

    await service.on_command("telegram", _sender(), "summary", "")

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
    await service.on_command("telegram", _sender(), "wat", "")
    assert "/summary" in transport.texts


async def test_start_command_routes_to_linking(repo):
    """/start как команда идёт тем же путём, что и кнопка «Начать»."""
    service, transport = _make_service(repo, FakeTasks(by_telegram={"ivanov": PERSON}))

    await service.on_command("telegram", _sender(), "start", "")

    assert repo.get(transport="telegram", chat_id="100") is not None
    assert "привязаны" in transport.texts
