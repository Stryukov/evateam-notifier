"""Оркестратор (application layer): связывает транспорт, EvaTeam, хранилище и ядро.

Реализует UpdateHandler (входящие события) и предоставляет операции для планировщика
(рассылка дайджеста и напоминаний о просрочке).
"""

from __future__ import annotations

import logging
from datetime import datetime

from .core import formatting, summary_text
from .core.deadlines import find_overdue
from .core.digest import build_digest
from .core.messages import OutgoingDocument, OutgoingMessage
from .core.models import Person, Summary
from .core.onboarding import handle_person_query
from .core.summary import SummaryOptions, build_summary
from .evateam.portfolio import EvaTeamPortfolio
from .evateam.tasks import EvaTeamTasks
from .reports import ReportFiles, write_report_files
from .storage.repository import UserRepository
from .transports.base import BotTransport, TransportName

logger = logging.getLogger(__name__)


class BotService:
    def __init__(
        self,
        *,
        transports: dict[TransportName, BotTransport],
        tasks_api: EvaTeamTasks,
        repo: UserRepository,
        portfolio_api: EvaTeamPortfolio | None = None,
        summary_options: SummaryOptions | None = None,
        report_dir: str = "data/reports",
    ) -> None:
        self._transports = transports
        self._tasks = tasks_api
        self._repo = repo
        self._portfolio = portfolio_api
        self._summary_options = summary_options or SummaryOptions()
        self._report_dir = report_dir
        # Кандидаты для подтверждения, ключ (transport, chat_id).
        self._pending: dict[tuple[str, str], dict[str, Person]] = {}
        for transport in transports.values():
            transport.set_handler(self)

    def _transport(self, name: TransportName) -> BotTransport:
        return self._transports[name]

    # ---------- UpdateHandler ----------

    async def on_start(self, transport: TransportName, chat_id: str) -> None:
        await self._transport(transport).send_message(
            chat_id, formatting.welcome_message()
        )

    async def on_text(self, transport: TransportName, chat_id: str, text: str) -> None:
        people = await self._tasks.find_person(text)
        result = handle_person_query(text, people)
        if result.candidates:
            self._pending[(transport, chat_id)] = {p.id: p for p in result.candidates}
        await self._transport(transport).send_message(chat_id, result.message)

    async def on_action(self, transport: TransportName, chat_id: str, action: str) -> None:
        tr = self._transport(transport)
        if action == formatting.ACTION_REJECT:
            self._pending.pop((transport, chat_id), None)
            await tr.send_message(chat_id, formatting.rejected_message())
            return

        if action.startswith(formatting.ACTION_CONFIRM_PREFIX):
            person_id = action[len(formatting.ACTION_CONFIRM_PREFIX):]
            person = self._pending.get((transport, chat_id), {}).get(person_id)
            if person is None:
                # Кандидаты потерялись (перезапуск) — попросим ввести заново.
                await tr.send_message(chat_id, formatting.welcome_message())
                return
            self._repo.link(
                transport=transport,
                chat_id=chat_id,
                person_id=person.id,
                person_name=person.name,
            )
            self._pending.pop((transport, chat_id), None)
            await tr.send_message(chat_id, formatting.linked_message(person))

    async def on_command(
        self, transport: TransportName, chat_id: str, command: str, args: str
    ) -> None:
        if command == "summary":
            await self.send_summary(transport, chat_id)
        elif command in {"start", "help"}:
            await self._transport(transport).send_message(
                chat_id, formatting.welcome_message()
            )
        else:
            await self._transport(transport).send_message(
                chat_id, formatting.unknown_command_message(command)
            )

    # ---------- сводка по проектам ----------

    async def build_summary(self, now: datetime | None = None) -> Summary:
        """Собрать управленческую сводку. Требует настроенного portfolio_api."""
        if self._portfolio is None:
            raise RuntimeError("Сводка недоступна: не настроен EvaTeamPortfolio")
        portfolio = await self._portfolio.get_portfolio()
        return build_summary(portfolio, now=now, options=self._summary_options)

    async def send_summary(
        self, transport: TransportName, chat_id: str, now: datetime | None = None
    ) -> bool:
        """Собрать и отправить сводку. True — отчёт содержательный."""
        tr = self._transport(transport)
        try:
            # Сбор занимает несколько запросов к EvaTeam — сразу отвечаем, что работаем.
            await tr.send_message(chat_id, summary_text.building_message())
            summary = await self.build_summary(now)
        except Exception as exc:  # noqa: BLE001 — пользователь должен узнать о сбое
            logger.exception("Не удалось собрать сводку для чата %s", chat_id)
            await tr.send_message(chat_id, summary_text.summary_error_message(str(exc)))
            return False

        if summary.is_empty:
            await tr.send_message(chat_id, summary_text.empty_summary_message(summary))
            return False

        files = write_report_files(summary, output_dir=self._report_dir)
        await self._deliver(tr, chat_id, summary, files)
        return True

    async def send_summary_to_all(self, now: datetime | None = None) -> int:
        """Разослать сводку всем привязанным. Данные собираются один раз на всех."""
        links = self._repo.list_enabled()
        if not links:
            return 0
        summary = await self.build_summary(now)
        files = None if summary.is_empty else write_report_files(
            summary, output_dir=self._report_dir
        )

        sent = 0
        for link in links:
            try:
                tr = self._transport(link.transport)
                if files is None:
                    await tr.send_message(
                        link.chat_id, summary_text.empty_summary_message(summary)
                    )
                else:
                    await self._deliver(tr, link.chat_id, summary, files)
                sent += 1
            except Exception:  # noqa: BLE001 — один сбойный чат не рушит рассылку
                logger.exception("Summary failed for chat %s", link.chat_id)
        return sent

    async def _deliver(
        self, tr: BotTransport, chat_id: str, summary: Summary, files: ReportFiles
    ) -> None:
        await tr.send_message(chat_id, summary_text.summary_message(summary))
        if not tr.supports_documents:
            paths = "\n".join(str(a.path) for a in (files.html, files.csv))
            await tr.send_message(
                chat_id, OutgoingMessage(text=f"Файлы отчёта сохранены:\n{paths}")
            )
            return
        await tr.send_document(
            chat_id,
            OutgoingDocument(
                filename=files.html.filename,
                content=files.html.content,
                mime_type=files.html.mime_type,
                caption="Полный отчёт — откройте в браузере, печать → PDF",
            ),
        )
        await tr.send_document(
            chat_id,
            OutgoingDocument(
                filename=files.csv.filename,
                content=files.csv.content,
                mime_type=files.csv.mime_type,
                caption="Дорожная карта для Google Sheets: Вставка → Таймлайн",
            ),
        )

    # ---------- операции планировщика ----------

    async def send_daily_digests(self) -> int:
        """Разослать утренний дайджест всем привязанным пользователям. Возвращает кол-во."""
        sent = 0
        for link in self._repo.list_enabled():
            try:
                tasks = await self._tasks.get_tasks_for_person(link.person_id)
                digest = build_digest(tasks)
                person = Person(id=link.person_id, name=link.person_name)
                message = formatting.digest_message(person, digest)
                await self._transport(link.transport).send_message(link.chat_id, message)
                sent += 1
            except Exception:  # noqa: BLE001 — один сбойный пользователь не рушит рассылку
                logger.exception("Digest failed for chat %s", link.chat_id)
        return sent

    async def send_evening_reminders(self, now: datetime | None = None) -> int:
        """Напомнить закрыть выполненное и подвинуть сроки. Возвращает кол-во."""
        now = now or datetime.now()
        sent = 0
        for link in self._repo.list_enabled():
            try:
                tasks = await self._tasks.get_tasks_for_person(link.person_id)
                digest = build_digest(tasks)
                # Закрывать и двигать нечего — не дёргаем человека.
                if not digest.in_progress and not digest.waiting:
                    continue
                person = Person(id=link.person_id, name=link.person_name)
                message = formatting.evening_message(person, digest, now)
                await self._transport(link.transport).send_message(link.chat_id, message)
                sent += 1
            except Exception:  # noqa: BLE001 — один сбойный пользователь не рушит рассылку
                logger.exception("Evening reminder failed for chat %s", link.chat_id)
        return sent

    async def send_deadline_reminders(self, now: datetime | None = None) -> int:
        """Разослать напоминания о просроченных задачах (с дедупом за день)."""
        now = now or datetime.now()
        today = now.date()
        sent = 0
        for link in self._repo.list_enabled():
            try:
                tasks = await self._tasks.get_tasks_for_person(link.person_id)
                overdue = find_overdue(tasks, now)
                fresh = [
                    t
                    for t in overdue
                    if not self._repo.was_deadline_reminded(
                        transport=link.transport,
                        chat_id=link.chat_id,
                        task_id=t.id,
                        on=today,
                    )
                ]
                if not fresh:
                    continue
                person = Person(id=link.person_id, name=link.person_name)
                message = formatting.overdue_message(person, fresh, now)
                await self._transport(link.transport).send_message(link.chat_id, message)
                for task in fresh:
                    self._repo.mark_deadline_reminded(
                        transport=link.transport,
                        chat_id=link.chat_id,
                        task_id=task.id,
                        on=today,
                    )
                sent += 1
            except Exception:  # noqa: BLE001
                logger.exception("Deadline reminder failed for chat %s", link.chat_id)
        return sent
