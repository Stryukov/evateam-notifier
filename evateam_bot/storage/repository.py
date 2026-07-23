"""Репозиторий доступа к данным поверх сессий SQLAlchemy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .db import LinkedUser, SentDeadlineReminder


@dataclass(frozen=True)
class UserLink:
    """Read-only снимок привязки (чтобы не таскать ORM-объекты вне сессии)."""

    transport: str
    chat_id: str
    person_id: str
    person_name: str
    enabled: bool


class UserRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def link(
        self, *, transport: str, chat_id: str, person_id: str, person_name: str
    ) -> None:
        """Создать или обновить привязку чата к пользователю EvaTeam."""
        with self._sf() as session:
            existing = session.scalar(
                select(LinkedUser).where(
                    LinkedUser.transport == transport, LinkedUser.chat_id == chat_id
                )
            )
            if existing is None:
                session.add(
                    LinkedUser(
                        transport=transport,
                        chat_id=chat_id,
                        person_id=person_id,
                        person_name=person_name,
                    )
                )
            else:
                existing.person_id = person_id
                existing.person_name = person_name
                existing.enabled = True
            session.commit()

    def get(self, *, transport: str, chat_id: str) -> UserLink | None:
        with self._sf() as session:
            row = session.scalar(
                select(LinkedUser).where(
                    LinkedUser.transport == transport, LinkedUser.chat_id == chat_id
                )
            )
            return _to_link(row) if row else None

    def list_enabled(self) -> list[UserLink]:
        with self._sf() as session:
            rows = session.scalars(
                select(LinkedUser).where(LinkedUser.enabled.is_(True))
            ).all()
            return [_to_link(r) for r in rows]

    # --- дедуп напоминаний о дедлайне ---

    def was_deadline_reminded(
        self, *, transport: str, chat_id: str, task_id: str, on: date
    ) -> bool:
        with self._sf() as session:
            row = session.scalar(
                select(SentDeadlineReminder).where(
                    SentDeadlineReminder.transport == transport,
                    SentDeadlineReminder.chat_id == chat_id,
                    SentDeadlineReminder.task_id == task_id,
                    SentDeadlineReminder.sent_date == on,
                )
            )
            return row is not None

    def mark_deadline_reminded(
        self, *, transport: str, chat_id: str, task_id: str, on: date
    ) -> None:
        with self._sf() as session:
            session.add(
                SentDeadlineReminder(
                    transport=transport, chat_id=chat_id, task_id=task_id, sent_date=on
                )
            )
            session.commit()


def _to_link(row: LinkedUser) -> UserLink:
    return UserLink(
        transport=row.transport,
        chat_id=row.chat_id,
        person_id=row.person_id,
        person_name=row.person_name,
        enabled=row.enabled,
    )
