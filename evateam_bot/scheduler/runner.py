"""Настройка cron-заданий поверх AsyncIOScheduler."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import Settings
from ..service import BotService

logger = logging.getLogger(__name__)


def build_scheduler(service: BotService, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    digest_h, digest_m = settings.parsed_digest_time()
    scheduler.add_job(
        service.send_daily_digests,
        CronTrigger(hour=digest_h, minute=digest_m, timezone=settings.timezone),
        id="morning_digest",
        name="Утренний дайджест",
        replace_existing=True,
    )

    dl_h, dl_m = settings.parsed_deadline_time()
    scheduler.add_job(
        service.send_deadline_reminders,
        CronTrigger(hour=dl_h, minute=dl_m, timezone=settings.timezone),
        id="deadline_check",
        name="Проверка просроченных задач",
        replace_existing=True,
    )

    ev_h, ev_m = settings.parsed_evening_time()
    scheduler.add_job(
        service.send_evening_reminders,
        CronTrigger(hour=ev_h, minute=ev_m, timezone=settings.timezone),
        id="evening_check",
        name="Вечернее напоминание закрыть задачи",
        replace_existing=True,
    )

    logger.info(
        "Scheduled digest at %02d:%02d, deadline check at %02d:%02d, "
        "evening reminder at %02d:%02d (%s)",
        digest_h, digest_m, dl_h, dl_m, ev_h, ev_m, settings.timezone,
    )
    return scheduler
