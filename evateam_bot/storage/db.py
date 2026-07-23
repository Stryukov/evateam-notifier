"""Схема БД и фабрика сессий (SQLAlchemy 2.0)."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from sqlalchemy import String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class LinkedUser(Base):
    """Привязка чата мессенджера к пользователю EvaTeam."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("transport", "chat_id", name="uq_transport_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transport: Mapped[str] = mapped_column(String(32), default="telegram")
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    person_id: Mapped[str] = mapped_column(String(64))
    person_name: Mapped[str] = mapped_column(String(256), default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    linked_at: Mapped[datetime] = mapped_column(default=_utcnow)


class SentDeadlineReminder(Base):
    """Дедуп: не слать повторно напоминание по задаче за один день."""

    __tablename__ = "sent_deadline_reminders"
    __table_args__ = (
        UniqueConstraint("transport", "chat_id", "task_id", "sent_date", name="uq_reminder"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transport: Mapped[str] = mapped_column(String(32), default="telegram")
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    sent_date: Mapped[date] = mapped_column(default=date.today)


def make_engine(db_path: str):
    if db_path != ":memory:":
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(db_path: str) -> sessionmaker:
    engine = make_engine(db_path)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)
