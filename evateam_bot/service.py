"""Оркестратор (application layer): связывает транспорт, EvaTeam, хранилище и ядро.

Реализует UpdateHandler (входящие события) и предоставляет операции для планировщика
(рассылка дайджеста и напоминаний о просрочке).
"""

from __future__ import annotations

import logging
from datetime import datetime

from .core import formatting
from .core.deadlines import find_overdue
from .core.digest import build_digest
from .core.models import Person
from .core.onboarding import handle_person_query
from .evateam.tasks import EvaTeamTasks
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
    ) -> None:
        self._transports = transports
        self._tasks = tasks_api
        self._repo = repo
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
