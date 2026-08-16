"""Настройка cron-заданий поверх AsyncIOScheduler."""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import Settings
from ..service import BotService

logger = logging.getLogger(__name__)

#: Как часто будить планировщик «вхолостую», секунды.
#:
#: AsyncIOScheduler ждёт до ближайшего задания через loop.call_later(), а тот отмеряет
#: время по МОНОТОННЫМ часам. Если машина уснёт (ноутбук, ВМ WSL2), монотонные часы
#: замирают, а настенные идут — и таймер, взведённый на «15 часов до утра», после
#: пробуждения досчитывает те же 15 часов уже реального времени. Наблюдали ровно это:
#: за 75 часов работы контейнера монотонные часы набрали 5, и ни одно задание не
#: сработало. Короткий такт держит любой call_later в пределах минуты, поэтому после
#: пробуждения планировщик почти сразу сверяется с настенным временем.
HEARTBEAT_SECONDS = 60

#: Во сколько раз разрыв между тактами должен превысить норму, чтобы счесть его сном.
_SLEEP_FACTOR = 5

#: Насколько задание может опоздать и всё-таки выполниться, секунды.
#:
#: Осознанно почти ноль: пропущенное не досылаем. «Утренний план дня», пришедший
#: вечером после пробуждения машины, только путает. Задаём явно, а не полагаемся на
#: умолчание APScheduler — это продуктовое решение, а не деталь библиотеки.
MISSED_RUN_GRACE_SECONDS = 1


def build_scheduler(service: BotService, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    days = settings.schedule_days

    digest_h, digest_m = settings.parsed_digest_time()
    scheduler.add_job(
        service.send_daily_digests,
        CronTrigger(
            day_of_week=days, hour=digest_h, minute=digest_m, timezone=settings.timezone
        ),
        id="morning_digest",
        misfire_grace_time=MISSED_RUN_GRACE_SECONDS,
        name="Утренний дайджест",
        replace_existing=True,
    )

    dl_h, dl_m = settings.parsed_deadline_time()
    scheduler.add_job(
        service.send_deadline_reminders,
        CronTrigger(day_of_week=days, hour=dl_h, minute=dl_m, timezone=settings.timezone),
        id="deadline_check",
        misfire_grace_time=MISSED_RUN_GRACE_SECONDS,
        name="Проверка просроченных задач",
        replace_existing=True,
    )

    ev_h, ev_m = settings.parsed_evening_time()
    scheduler.add_job(
        service.send_evening_reminders,
        CronTrigger(day_of_week=days, hour=ev_h, minute=ev_m, timezone=settings.timezone),
        id="evening_check",
        misfire_grace_time=MISSED_RUN_GRACE_SECONDS,
        name="Вечернее напоминание закрыть задачи",
        replace_existing=True,
    )

    # Пульс: сам ничего не рассылает, но не даёт таймерам стать длинными.
    # misfire_grace_time=None — иначе после пробуждения машины APScheduler завалит лог
    # предупреждениями о собственных опозданиях пульса; coalesce схлопывает их в одно.
    scheduler.add_job(
        make_heartbeat(),
        IntervalTrigger(seconds=HEARTBEAT_SECONDS),
        id="heartbeat",
        name="Такт планировщика",
        misfire_grace_time=None,
        coalesce=True,
        replace_existing=True,
    )

    logger.info(
        "Scheduled digest at %02d:%02d, deadline check at %02d:%02d, "
        "evening reminder at %02d:%02d, days=%s (%s)",
        digest_h, digest_m, dl_h, dl_m, ev_h, ev_m, days, settings.timezone,
    )
    return scheduler


def make_heartbeat(now=datetime.now):
    """Такт планировщика: замечает провалы во времени и пишет о них в лог.

    Рассылки, попавшие в провал, считаются пропущенными и не досылаются — так решено
    осознанно: «утренний план дня», пришедший вечером, только путает. Но сам факт
    провала должен быть виден, иначе тишина в логах снова будет необъяснимой.
    """
    state: dict[str, datetime | None] = {"last": None}

    async def heartbeat() -> None:
        current = now()
        previous = state["last"]
        state["last"] = current
        if previous is None:
            return
        gap = (current - previous).total_seconds()
        if gap > HEARTBEAT_SECONDS * _SLEEP_FACTOR:
            logger.warning(
                "Похоже, машина спала: между тактами планировщика прошло %.0f мин. "
                "Задания, попавшие в этот промежуток, пропущены.",
                gap / 60,
            )

    return heartbeat
